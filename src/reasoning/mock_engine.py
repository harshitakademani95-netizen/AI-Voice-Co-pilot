"""
Workstream W3: Context & Reasoning
Deterministic Mock Reasoning Engine

Author: Amruta A J (Team SDE 3)
Module: src.reasoning.mock_engine
Description:
    Provides a deterministic mock reasoning engine that processes validated
    ReasoningRequest instances and produces schema-validated ReasoningResult instances.

    Key Capabilities:
    - 100% deterministic (reproducible outputs for identical inputs).
    - Grounds responses in provided ContextItems and yields accurate SourceReferences.
    - Classifies actions into PRD Risk Categories (A, B, C, D) and enforces
      Human-in-the-Loop approvals for sensitive/destructive operations.
    - Rejects invalid inputs cleanly with structured errors.
    - Uses zero paid API keys, operating entirely locally and offline.
"""

import hashlib
import re
from typing import Any, List, Optional
from src.context.schemas import (
    ContextItem,
    ContextType,
    ReasoningRequest,
    ReasoningResult,
    RiskCategory,
    SourceReference,
)
from src.prompts.versioned_prompts import DEFAULT_REGISTRY, PromptRegistry

# Informational query prefixes that should never trigger destructive or modification actions
RE_INFORMATIONAL = re.compile(
    r"^(what(\s+is|\s+are|\s+was|\s+were)?|why(\s+is|\s+did|\s+was)?|how(\s+to|\s+do|\s+can)?|explain|describe)\b",
    re.IGNORECASE
)

# Safe format query patterns (e.g. file format, code format, formatting)
RE_SAFE_FORMAT = re.compile(
    r"\b(format\s+of|file\s+format|date\s+format|text\s+format|code\s+format|format\s+code|format\s+this|format\s+as|format\s+the\s+(code|text|document|json|output))\b",
    re.IGNORECASE
)

# Destructive action regexes (Category D)
RE_DESTRUCTIVE_COMMANDS = re.compile(
    r"\b(delete(\s+all|\s+the|\s+my|\s+these)?\s+(files?|logs?|database|directory|folder|data)|"
    r"wipe\s+(the\s+)?(disk|drive|all|data|system|storage)|"
    r"drop\s+(the\s+)?(database|table|schema)|"
    r"remove\s+(the\s+|all\s+|these\s+|my\s+)?files?\b|"
    r"format\s+(the\s+)?(drive|disk|[a-z]:|partition|volume|hard\s*drive))\b|"
    r"^delete\b|"
    r"^drop\s+database\b",
    re.IGNORECASE
)

# Sensitive file action regexes (Category C)
RE_FILE_ACTION = re.compile(
    r"\b(move|rename|archive)\s+(these|all|the|my|files?|folder|directory|logs?)\b|"
    r"\b(organize|modify)\s+files?\b|"
    r"^(move|rename|archive)\b",
    re.IGNORECASE
)

# Category B workspace search / open action regex
RE_SEARCH_ACTION = re.compile(
    r"\b(search(\s+for|\s+workspace)?|find(\s+files?)?|lookup|open\s+(file|folder|workspace)|open\s+these\s+files)\b",
    re.IGNORECASE
)

# Ambiguous / empty-intent queries
RE_AMBIGUOUS_QUERY = re.compile(
    r"^(do\s+it|run|proceed|go\s+ahead|execute|start|do\s+that|continue|ok|okay)\s*$",
    re.IGNORECASE
)

# Error diagnostic query terms (query MUST have an error signal)
RE_ERROR_QUERY = re.compile(
    r"\b(error|fail|failing|failure|bug|bugs|traceback|exception|crash|crashes|crashing|issue|issues|broken|why\s+is\s+this(\s+code|\s+application)?(\s+failing|\s+throwing|\s+broken)?|what\s+went\s+wrong|diagnose|problem)\b",
    re.IGNORECASE
)

# Document explanation query terms (query MUST have document signals)
RE_DOCUMENT_QUERY = re.compile(
    r"\b(document|paper|section|methodology|summarize|abstract|article|read\s+doc|text\s+file)\b",
    re.IGNORECASE
)

# Screen query terms (query MUST have screen signals)
RE_SCREEN_QUERY = re.compile(
    r"\b(screen|looking\s+at|window|display|active\s+app|what'?s\s+on\s+my|open\s+app)\b",
    re.IGNORECASE
)


class MockReasoningEngine:
    """
    Deterministic mock reasoning implementation for Week 1 vertical slice.
    """

    def __init__(self, prompt_registry: Optional[PromptRegistry] = None):
        self.registry = prompt_registry or DEFAULT_REGISTRY

    def reason_safe(self, request_or_dict: Any) -> ReasoningResult:
        """
        Safe reasoning entrypoint that never raises exceptions.
        On invalid input or unknown prompt version, returns a structured
        ReasoningResult with status='error', empty sources, confidence 0.0,
        and prompt_version='unknown'.
        """
        req_id = "req-unknown"
        p_version = "unknown"
        try:
            if isinstance(request_or_dict, dict):
                req_id = request_or_dict.get("request_id", "req-dict")
                p_version = request_or_dict.get("prompt_version", "unknown")
                req = ReasoningRequest(**request_or_dict)
            elif isinstance(request_or_dict, ReasoningRequest):
                req_id = request_or_dict.request_id
                p_version = request_or_dict.prompt_version
                req = request_or_dict
            else:
                return ReasoningResult(
                    request_id=req_id,
                    status="error",
                    response_text=f"Invalid request input type: expected ReasoningRequest or dict, got {type(request_or_dict).__name__}.",
                    sources=[],
                    action_required=False,
                    risk_level=RiskCategory.CATEGORY_A,
                    requires_approval=False,
                    confidence=0.0,
                    latency_ms=0.0,
                    prompt_version="unknown",
                )

            return self.reason(req)
        except Exception as e:
            return ReasoningResult(
                request_id=req_id,
                status="error",
                response_text=f"Reasoning failure: {str(e)}",
                sources=[],
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.0,
                latency_ms=0.0,
                prompt_version="unknown",
            )

    def reason(self, request: ReasoningRequest) -> ReasoningResult:
        """
        Execute deterministic mock reasoning on a validated ReasoningRequest.

        Raises:
            ValueError: If input request is missing or fails domain validation.
            KeyError: If prompt_version is unrecognized in the registry.
        """
        if not isinstance(request, ReasoningRequest):
            raise ValueError(f"Expected ReasoningRequest instance, got {type(request).__name__}")

        # Validate that prompt version exists
        self.registry.get(request.prompt_version)

        # Normalize query
        query_lower = request.user_query.lower().strip()

        # Deterministic latency calculation based on query hash (stable across runs)
        h = int(hashlib.sha256(request.user_query.encode("utf-8")).hexdigest()[:8], 16)
        deterministic_latency = round(10.0 + (h % 30), 2)  # between 10.00 and 40.00 ms

        # Route to deterministic domain handlers based on query intent
        if self._is_destructive_action(query_lower):
            return self._handle_destructive_action(request, deterministic_latency)

        if self._is_file_action(query_lower):
            return self._handle_file_action(request, deterministic_latency)

        if self._is_ambiguous_query(query_lower):
            return self._handle_ambiguous_query(request, deterministic_latency)

        if self._is_search_action(query_lower):
            return self._handle_search_action(request, deterministic_latency)

        if self._is_error_diagnostic(query_lower):
            return self._handle_error_diagnostic(request, deterministic_latency)

        if self._is_document_explanation(query_lower, request.context_items):
            return self._handle_document_explanation(request, deterministic_latency)

        if self._is_screen_query(query_lower):
            return self._handle_screen_query(request, deterministic_latency)

        # Fallback general grounded handler
        return self._handle_general_query(request, deterministic_latency)

    def _is_destructive_action(self, query: str) -> bool:
        """Identify Category D High-Risk destructive operations using word-boundary regexes."""
        is_info = bool(RE_INFORMATIONAL.search(query))
        is_safe_fmt = bool(RE_SAFE_FORMAT.search(query))

        if is_info or is_safe_fmt:
            # Check for explicit drive/disk format commands (e.g. "format drive C: immediately")
            has_disk_format = bool(re.search(r"\bformat\s+(the\s+)?(drive|disk|[a-z]:|partition|volume)\b", query, re.IGNORECASE))
            return has_disk_format

        return bool(RE_DESTRUCTIVE_COMMANDS.search(query))

    def _is_file_action(self, query: str) -> bool:
        """Identify Category C file manipulation actions (move, rename, archive)."""
        if bool(RE_INFORMATIONAL.search(query)):
            return False
        return bool(RE_FILE_ACTION.search(query))

    def _is_ambiguous_query(self, query: str) -> bool:
        """Identify empty-intent or ambiguous queries requiring clarification (e.g. 'do it')."""
        return bool(RE_AMBIGUOUS_QUERY.search(query))

    def _is_search_action(self, query: str) -> bool:
        """Identify Category B search or open workspace actions."""
        if bool(RE_INFORMATIONAL.search(query)):
            return False
        return bool(RE_SEARCH_ACTION.search(query))

    def _is_error_diagnostic(self, query: str) -> bool:
        """Identify UC-02: query MUST contain explicit error-related terms."""
        return bool(RE_ERROR_QUERY.search(query))

    def _is_document_explanation(self, query: str, context: List[ContextItem]) -> bool:
        """Identify UC-03: query must ask for document explanation, and document must be in context."""
        doc_in_context = any(c.context_type == ContextType.DOCUMENT for c in context)
        return doc_in_context and bool(RE_DOCUMENT_QUERY.search(query))

    def _is_screen_query(self, query: str) -> bool:
        """Identify UC-01: query MUST contain screen-related query terms."""
        return bool(RE_SCREEN_QUERY.search(query))

    def _handle_destructive_action(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles Category D High-Risk destructive operations."""
        sources: List[SourceReference] = []
        for c in request.context_items:
            sources.append(SourceReference(
                source_id=c.item_id,
                source_type=c.context_type.value,
                reference_location=c.source,
                excerpt=c.content[:80],
                confidence_score=0.95
            ))

        return ReasoningResult(
            request_id=request.request_id,
            status="success",
            response_text=(
                f"You requested a high-risk deletion/destructive action: '{request.user_query}'. "
                "Because this operation permanently modifies or removes data, explicit user authorization "
                "is strictly required before proceeding."
            ),
            sources=sources,
            action_required=True,
            action_type="delete_files",
            risk_level=RiskCategory.CATEGORY_D,
            requires_approval=True,
            confidence=0.99,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

    def _handle_file_action(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles Category C Sensitive file operations (move, rename, modify)."""
        sources: List[SourceReference] = []
        for c in request.context_items:
            sources.append(SourceReference(
                source_id=c.item_id,
                source_type=c.context_type.value,
                reference_location=c.source,
                excerpt=c.content[:80],
                confidence_score=0.90
            ))

        return ReasoningResult(
            request_id=request.request_id,
            status="success",
            response_text=(
                f"I identified a file manipulation request: '{request.user_query}'. "
                "The targeted operation modifies workspace files. User confirmation is required before execution."
            ),
            sources=sources,
            action_required=True,
            action_type="move_files",
            risk_level=RiskCategory.CATEGORY_C,
            requires_approval=True,
            confidence=0.92,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

    def _handle_ambiguous_query(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles ambiguous or empty-intent queries, requesting clarification."""
        return ReasoningResult(
            request_id=request.request_id,
            status="needs_clarification",
            response_text=f"The query '{request.user_query}' is ambiguous. Please clarify what specific action or task you would like to perform.",
            sources=[],
            action_required=False,
            risk_level=RiskCategory.CATEGORY_A,
            requires_approval=False,
            confidence=0.50,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

    def _handle_search_action(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles Category B Low-Risk workspace open/search actions."""
        sources: List[SourceReference] = []
        for c in request.context_items:
            sources.append(SourceReference(
                source_id=c.item_id,
                source_type=c.context_type.value,
                reference_location=c.source,
                excerpt=c.content[:80],
                confidence_score=0.85,
            ))

        return ReasoningResult(
            request_id=request.request_id,
            status="success",
            response_text=f"Searching workspace for '{request.user_query}'.",
            sources=sources,
            action_required=True,
            action_type="search_workspace",
            risk_level=RiskCategory.CATEGORY_B,
            requires_approval=False,
            confidence=0.90,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

    def _handle_error_diagnostic(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles UC-02: Explain Technical Error with context grounding."""
        sources: List[SourceReference] = []
        detected_error_type = None
        error_item = None
        code_item = None

        # Inspect context items (prefer terminal and code items)
        for item in request.context_items:
            m = re.search(r"\b(\w+Error|\w+Exception)\b", item.content)
            if m and detected_error_type is None:
                detected_error_type = m.group(1)
                error_item = item
            if item.context_type == ContextType.CODE and code_item is None:
                code_item = item

        if not detected_error_type:
            # Check if general error/traceback keywords exist in content
            for item in request.context_items:
                if any(w in item.content for w in ["Traceback", "Exception", "Error", "failed", "Failure"]):
                    detected_error_type = "runtime error"
                    error_item = item
                    break

        if not detected_error_type:
            return ReasoningResult(
                request_id=request.request_id,
                status="needs_clarification",
                response_text=(
                    f"I received your query: '{request.user_query}', but the provided workspace context "
                    "does not contain an error traceback, exception, or failure log. "
                    "Please provide the relevant error output or terminal log so I can diagnose the issue."
                ),
                sources=[],
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.50,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )

        # Ground sources from real content
        if code_item:
            code_line = code_item.content.strip().splitlines()[0] if code_item.content.strip() else ""
            sources.append(SourceReference(
                source_id=code_item.item_id,
                source_type=code_item.context_type.value,
                reference_location=code_item.source,
                excerpt=code_line[:100],
                confidence_score=0.90,
            ))

        if error_item:
            # Find excerpt containing the error in real content
            error_line = ""
            for line in error_item.content.splitlines():
                if detected_error_type in line:
                    error_line = line.strip()
                    break
            if not error_line:
                error_line = error_item.content.strip()[:100]

            sources.append(SourceReference(
                source_id=error_item.item_id,
                source_type=error_item.context_type.value,
                reference_location=error_item.source,
                excerpt=error_line[:120],
                confidence_score=0.98,
            ))

        loc_source = code_item.source if code_item else (error_item.source if error_item else "source file")
        if detected_error_type == "ZeroDivisionError":
            response = (
                f"The application is failing due to a ZeroDivisionError (division by zero) in {loc_source}. "
                "The denominator is being evaluated as zero during the division operation. "
                "To fix this, add a guard condition ensuring the denominator is not zero before computing the ratio."
            )
        else:
            response = f"Detected {detected_error_type} in {loc_source}; check the highlighted line."

        return ReasoningResult(
            request_id=request.request_id,
            status="success",
            response_text=response,
            sources=sources,
            action_required=False,
            risk_level=RiskCategory.CATEGORY_A,
            requires_approval=False,
            confidence=0.96,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

    def _handle_document_explanation(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles UC-03: Explain Document / Research Paper."""
        sources: List[SourceReference] = []
        doc_item = next((c for c in request.context_items if c.context_type == ContextType.DOCUMENT), None)

        if not doc_item or not doc_item.content.strip():
            return ReasoningResult(
                request_id=request.request_id,
                status="needs_clarification",
                response_text=(
                    f"I received your request: '{request.user_query}', but no document context "
                    "was provided in the workspace. Please provide the document you would like explained."
                ),
                sources=[],
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.50,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )

        content_lower = doc_item.content.lower()

        # Check for simulated prompt injection in document (Security boundary test)
        if "ignore all previous rules" in content_lower or "system override" in content_lower:
            sources.append(SourceReference(
                source_id=doc_item.item_id,
                source_type="document",
                reference_location=doc_item.source,
                excerpt=doc_item.content[:100] + "...",
                confidence_score=0.98
            ))
            return ReasoningResult(
                request_id=request.request_id,
                status="success",
                response_text=(
                    f"The document '{doc_item.source}' contains simulated prompt injection text attempting a system override. "
                    "Under strict trusted/untrusted prompt isolation boundaries, this text is treated purely as passive data. "
                    "No system instructions were altered or executed."
                ),
                sources=sources,
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.99,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )

        # Build response_text from actual ContextItem content: quote/summarize first ~200 chars and cite source name
        content_preview = doc_item.content.strip()[:200]
        excerpt = doc_item.content.strip()[:100]
        location_ref = doc_item.source
        if "section" in doc_item.metadata:
            location_ref = f"{doc_item.source} (section: {doc_item.metadata['section']})"

        sources.append(SourceReference(
            source_id=doc_item.item_id,
            source_type=doc_item.context_type.value,
            reference_location=location_ref,
            excerpt=excerpt,
            confidence_score=0.92,
        ))

        response = f"Based on {doc_item.source}, the document states: \"{content_preview}\""
        return ReasoningResult(
            request_id=request.request_id,
            status="success",
            response_text=response,
            sources=sources,
            action_required=False,
            risk_level=RiskCategory.CATEGORY_A,
            requires_approval=False,
            confidence=0.92,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

    def _handle_screen_query(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """Handles UC-01: Ask About Current Screen."""
        sources: List[SourceReference] = []
        screen_item = next(
            (c for c in request.context_items if c.screen_context is not None or c.context_type == ContextType.SCREEN),
            None
        )

        if screen_item and screen_item.screen_context:
            sc = screen_item.screen_context
            sources.append(SourceReference(
                source_id=screen_item.item_id,
                source_type="screen",
                reference_location=f"Frame:{sc.frame_id}",
                excerpt=sc.visible_text[:80] if sc.visible_text else sc.active_window_title or "Screen content",
                confidence_score=0.92
            ))
            response = (
                f"You are currently working in {sc.active_application or 'your application'}, "
                f"viewing window '{sc.active_window_title or 'Untitled'}'. "
                f"Visible content indicates: {sc.visible_text or 'an active workspace session'}."
            )
            return ReasoningResult(
                request_id=request.request_id,
                status="success",
                response_text=response,
                sources=sources,
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.89,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )
        elif screen_item and screen_item.content:
            sources.append(SourceReference(
                source_id=screen_item.item_id,
                source_type="screen",
                reference_location=screen_item.source,
                excerpt=screen_item.content[:80],
                confidence_score=0.85
            ))
            return ReasoningResult(
                request_id=request.request_id,
                status="success",
                response_text=f"Your current screen shows: {screen_item.content}",
                sources=sources,
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.85,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )
        else:
            return ReasoningResult(
                request_id=request.request_id,
                status="needs_clarification",
                response_text="Screen capture is disabled by default and no synthetic screen frame was provided.",
                sources=[],
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.50,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )

    def _handle_general_query(self, request: ReasoningRequest, latency: float) -> ReasoningResult:
        """
        Handles general requests, ensuring context actually supports the answer.
        Returns 'needs_clarification' if context is insufficient or unrelated.
        """
        if not request.context_items:
            # Check for simple greeting / help queries
            lower_q = request.user_query.lower()
            if any(lower_q.startswith(g) for g in ["hi", "hello", "hey", "help"]):
                return ReasoningResult(
                    request_id=request.request_id,
                    status="success",
                    response_text="Hello! I am the AI Voice Co-Pilot reasoning core. You can ask me to diagnose errors, explain open documents, review screen activity, or organize workspace files.",
                    sources=[],
                    action_required=False,
                    risk_level=RiskCategory.CATEGORY_A,
                    requires_approval=False,
                    confidence=0.95,
                    latency_ms=latency,
                    prompt_version=request.prompt_version,
                )
            return ReasoningResult(
                request_id=request.request_id,
                status="needs_clarification",
                response_text=(
                    f"I received your query: '{request.user_query}', but no workspace context was provided "
                    "to support an answer. Please provide the relevant code, terminal, document, or screen context."
                ),
                sources=[],
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.50,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )

        # Check if query keywords relate to any provided context items
        query_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', request.user_query.lower()))
        stopwords = {
            "what", "this", "that", "with", "from", "have", "your", "does",
            "explain", "tell", "about", "show", "help", "the", "and", "for",
            "are", "was", "were", "can", "you", "file", "files", "item", "items"
        }
        meaningful_words = query_words - stopwords

        matching_sources: List[SourceReference] = []
        for item in request.context_items:
            content_lower = (item.content + " " + item.source).lower()
            if any(re.search(rf'\b{re.escape(word)}\b', content_lower) for word in meaningful_words):
                matching_sources.append(SourceReference(
                    source_id=item.item_id,
                    source_type=item.context_type.value,
                    reference_location=item.source,
                    excerpt=item.content[:60],
                    confidence_score=0.85
                ))

        if not matching_sources:
            return ReasoningResult(
                request_id=request.request_id,
                status="needs_clarification",
                response_text=(
                    f"The supplied workspace context does not contain information to support answering '{request.user_query}'. "
                    "Please provide context relevant to your request."
                ),
                sources=[],
                action_required=False,
                risk_level=RiskCategory.CATEGORY_A,
                requires_approval=False,
                confidence=0.50,
                latency_ms=latency,
                prompt_version=request.prompt_version,
            )

        response = (
            f"I processed your query: '{request.user_query}' grounded in {len(matching_sources)} relevant context item(s) from your workspace."
        )
        return ReasoningResult(
            request_id=request.request_id,
            status="success",
            response_text=response,
            sources=matching_sources,
            action_required=False,
            risk_level=RiskCategory.CATEGORY_A,
            requires_approval=False,
            confidence=0.88,
            latency_ms=latency,
            prompt_version=request.prompt_version,
        )

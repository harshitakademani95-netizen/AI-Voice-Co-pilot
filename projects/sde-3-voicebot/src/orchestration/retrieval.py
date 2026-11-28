"""Context Retrieval and Management Service for Week 3 Agentic Integration."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional

from src.context.schemas import ContextItem, ContextType

logger = logging.getLogger("backend.orchestration.retrieval")

# Sensitive patterns to redact from retrieved context
SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|bearer\s+[a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(r"(?i)(password|secret|token)\s*[:=]\s*['\"]?([^\s'\"]+)", re.IGNORECASE),
]


class ContextRetrievalService:
    """Manages retrieval, validation, and sanitization of context for agent planning and execution."""

    def __init__(self, in_memory_store: Optional[Dict[str, List[ContextItem]]] = None) -> None:
        self._store: Dict[str, List[ContextItem]] = in_memory_store or {}

    def add_context(self, session_id: str, item: ContextItem) -> None:
        """Stores a contextual item associated with a session."""
        if session_id not in self._store:
            self._store[session_id] = []
        self._store[session_id].append(item)

    def retrieve(
        self,
        session_id: str,
        query: str,
        max_items: int = 5,
        filter_type: Optional[ContextType] = None,
    ) -> List[ContextItem]:
        """Retrieves and sanitizes relevant contextual items for the current task.

        Gracefully handles empty results and service errors.
        """
        try:
            items = self._store.get(session_id, [])
            if not items:
                return []

            matched: List[ContextItem] = []
            query_terms = [t.lower() for t in query.split() if len(t) > 2]

            for it in items:
                if filter_type and it.context_type != filter_type:
                    continue

                # Content relevancy scoring
                content_str = str(it.content).lower()
                score = sum(1 for term in query_terms if term in content_str)

                # Sanitize any sensitive tokens from content
                sanitized_content = self._sanitize_content(it.content)
                sanitized_item = ContextItem(
                    item_id=it.item_id,
                    context_type=it.context_type,
                    source=it.source,
                    content=sanitized_content,
                    timestamp=it.timestamp,
                    metadata=it.metadata,
                )

                if not query_terms or score > 0:
                    matched.append((score, sanitized_item))

            # Sort by relevance score descending
            matched.sort(key=lambda x: x[0], reverse=True)
            return [m[1] for m in matched[:max_items]]
        except Exception as err:
            logger.error("Failed to retrieve context for session %s: %s", session_id, err)
            # Safe degradation: return empty context on retrieval service failure
            return []

    def _sanitize_content(self, content: Any) -> Any:
        """Redacts credentials, secrets, and authorization tokens from retrieved context."""
        if isinstance(content, str):
            sanitized = content
            for pat in SENSITIVE_PATTERNS:
                sanitized = pat.sub("[REDACTED_CREDENTIAL]", sanitized)
            return sanitized
        elif isinstance(content, dict):
            return {k: self._sanitize_content(v) for k, v in content.items()}
        elif isinstance(content, list):
            return [self._sanitize_content(x) for x in content]
        return content

    def clear(self, session_id: Optional[str] = None) -> None:
        """Clears stored context."""
        if session_id:
            self._store.pop(session_id, None)
        else:
            self._store.clear()


# Default singleton instance
retrieval_service = ContextRetrievalService()

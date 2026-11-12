"""
Workstream W3: Context & Reasoning
Context Schemas: ScreenContext, ContextItem, SourceReference, ReasoningRequest, ReasoningResult

Author: Amruta A J (Team SDE 3)
Module: src.context.schemas
Description:
    Provides strictly-typed Pydantic v2 data models for the context and reasoning
    layer of AI Voice Co-Pilot. All fields are explicitly typed, documented with
    constraints and units, and validate incoming/outgoing payloads.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _ensure_timezone_aware(dt: datetime, field_name: str) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"'{field_name}' must be a timezone-aware datetime.")
    return dt


class RiskCategory(str, Enum):
    """
    Risk classification defined in PRD Section 18:
    Category A - Informational (No confirmation required)
    Category B - Low-Risk Interaction (Configured policy)
    Category C - Sensitive (Requires user confirmation)
    Category D - High-Risk / Destructive (Explicit confirmation required)
    """
    CATEGORY_A = "A"
    CATEGORY_B = "B"
    CATEGORY_C = "C"
    CATEGORY_D = "D"


class ContextType(str, Enum):
    """Allowed context types supported by the Context Engine."""
    SCREEN = "screen"
    APPLICATION = "application"
    CODE = "code"
    TERMINAL = "terminal"
    DOCUMENT = "document"
    CONVERSATION = "conversation"
    RETRIEVAL = "retrieval"


class SourceReference(BaseModel):
    """
    Reference to a verified context item or ground-truth evidence supporting reasoning.
    """
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, description="Identifier of the context item or source artifact.")
    source_type: str = Field(..., min_length=1, description="Type/category of source (code, doc, terminal, etc.).")
    reference_location: Optional[str] = Field(None, description="Location pointer, e.g., 'main.py:12-18'.")
    excerpt: Optional[str] = Field(None, description="Extract or snippet demonstrating ground-truth evidence.")
    confidence_score: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Probability score [0.0, 1.0] indicating relevance/confidence."
    )


ALLOW_REAL_FRAMES = False


class ScreenContext(BaseModel):
    """
    Represents visual screen context captured or simulated from the user's workspace.
    Screen capture defaults to False and is enforced by a validator.
    Only synthetic frames (is_synthetic=True, capture_enabled=False) are allowed.
    """
    model_config = ConfigDict(extra="forbid")

    capture_enabled: bool = Field(
        False,
        description="Safety flag: screen capture is disabled by default."
    )
    is_synthetic: bool = Field(
        True,
        description="True if this is a synthetic test fixture frame, False if real hardware capture."
    )
    frame_id: str = Field(..., min_length=1, description="Unique frame identifier.")
    width: int = Field(1920, gt=0, description="Screen width in pixels.")
    height: int = Field(1080, gt=0, description="Screen height in pixels.")
    active_window_title: Optional[str] = Field(None, description="Title of the active foreground window.")
    active_application: Optional[str] = Field(None, description="Name of the active software application.")
    visible_text: Optional[str] = Field(None, description="Simulated OCR or visual text content visible on screen.")
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the frame capture/generation."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary additional frame metadata.")

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at_tz(cls, v: datetime) -> datetime:
        return _ensure_timezone_aware(v, "captured_at")

    @model_validator(mode="after")
    def validate_synthetic_only(self) -> "ScreenContext":
        if (not ALLOW_REAL_FRAMES and not self.is_synthetic) or self.capture_enabled:
            raise ValueError("Week 1: only synthetic frames are allowed (is_synthetic=True, capture_enabled=False).")
        return self


class ContextItem(BaseModel):
    """
    A single piece of context ingested by the Context Engine for reasoning.
    """
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., min_length=1, description="Unique context item identifier.")
    context_type: ContextType = Field(..., description="Category of context item.")
    source: str = Field(..., min_length=1, description="Source origin, e.g., 'src/calculator.py' or 'Terminal'.")
    content: str = Field(..., max_length=100_000, description="Untrusted contextual content treated strictly as data.")
    screen_context: Optional[ScreenContext] = Field(
        None,
        description="Optional visual screen context if item represents a screen frame."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of context item collection."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Structured metadata dictionary.")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_tz(cls, v: datetime) -> datetime:
        return _ensure_timezone_aware(v, "timestamp")


class ReasoningRequest(BaseModel):
    """
    Input contract submitted to the AI Reasoning Layer.
    """
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, description="Traceable request ID.")
    session_id: str = Field(..., min_length=1, description="Active user session ID.")
    user_query: str = Field(..., min_length=1, max_length=2000, description="User spoken or typed query.")
    context_items: List[ContextItem] = Field(
        default_factory=list,
        max_length=50,
        description="List of context items supplied by Context Engine (max 50)."
    )
    prompt_version: str = Field(
        "v1.0.0",
        pattern=r"^v\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$",
        description="Target versioned prompt template identifier."
    )
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Reasoning control parameters.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the request."
    )

    @field_validator("user_query")
    @classmethod
    def validate_user_query_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_query cannot be empty or purely whitespace.")
        return v.strip()

    @field_validator("context_items")
    @classmethod
    def validate_unique_item_ids(cls, items: List[ContextItem]) -> List[ContextItem]:
        seen = set()
        for item in items:
            if item.item_id in seen:
                raise ValueError(f"Duplicate item_id '{item.item_id}' detected in context_items.")
            seen.add(item.item_id)
        return items

    @field_validator("created_at")
    @classmethod
    def validate_created_at_tz(cls, v: datetime) -> datetime:
        return _ensure_timezone_aware(v, "created_at")


class ReasoningResult(BaseModel):
    """
    Output contract returned by the Reasoning Layer.
    """
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, description="Correlation ID matching ReasoningRequest.")
    status: Literal["success", "error", "needs_clarification"] = Field(
        "success",
        description="Outcome status of the reasoning pipeline."
    )
    response_text: str = Field(..., min_length=1, max_length=10_000, description="Answer or explanation text for the user.")
    sources: List[SourceReference] = Field(
        default_factory=list,
        description="Context sources cited to ground the answer."
    )
    action_required: bool = Field(False, description="Flag indicating if a tool execution is proposed.")
    action_type: Optional[str] = Field(None, description="Name of tool if action is required.")
    risk_level: RiskCategory = Field(RiskCategory.CATEGORY_A, description="PRD Risk classification (A, B, C, D).")
    requires_approval: bool = Field(False, description="Human-in-the-loop approval gate requirement.")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Reasoning confidence score [0.0, 1.0].")
    latency_ms: float = Field(0.0, ge=0.0, description="Latency in milliseconds.")
    prompt_version: str = Field(..., description="Prompt version used for reasoning.")

    @model_validator(mode="after")
    def validate_reasoning_result_rules(self) -> "ReasoningResult":
        """
        Enforce PRD Section 18 safety policies and schema consistency:
        - action_type required if action_required is True
        - action_required must be True if action_type is set
        - Category C and D require action_required=True and enforce requires_approval=True
        - status 'error' must have confidence <= 0.5
        """
        if self.action_required and not self.action_type:
            raise ValueError("action_type must be set when action_required is True.")
        if self.action_type and not self.action_required:
            raise ValueError("action_required must be True when action_type is set.")

        if self.risk_level in (RiskCategory.CATEGORY_C, RiskCategory.CATEGORY_D):
            if not self.action_required:
                raise ValueError(f"Category {self.risk_level.value} actions require action_required=True.")
            if not self.requires_approval:
                self.requires_approval = True

        if self.status == "error" and self.confidence > 0.5:
            raise ValueError("Confidence must be <= 0.5 when status is 'error'.")

        return self

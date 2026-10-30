"""
Workflow State Machine for the Agentic Workflow Engine (W4).

Manages the lifecycle states of a workflow:
    [draft]
      │
      ├──> [awaiting_approval] <──┐
      │          │                 │ (consequential action)
      │          ├──> [running] ───┘
      │          │        │
      │          │        ├──> [paused] ──> [running]
      │          │        │       │
      │          │        │       ├──> [cancelled]
      │          │        │       └──> [failed]
      │          │        │
      │          │        ├──> [succeeded] (Terminal)
      │          │        ├──> [failed]    (Terminal)
      │          │        └──> [cancelled] (Terminal)
      │          │
      │          └──> [cancelled] / [failed]
      │
      └──> [cancelled] / [failed]

All illegal state transitions are strictly rejected with InvalidStateTransitionError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from agentic_workflow.schemas import WorkflowState


class InvalidStateTransitionError(Exception):
    """Raised when an illegal transition between workflow states is requested."""

    def __init__(self, from_state: WorkflowState, to_state: WorkflowState, reason: str = ""):
        message = f"Illegal state transition from '{from_state.value}' to '{to_state.value}'."
        if reason:
            message += f" Reason: {reason}"
        super().__init__(message)
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason


@dataclass
class StateTransitionRecord:
    """Audit record of a state machine transition."""
    from_state: WorkflowState
    to_state: WorkflowState
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: Optional[str] = None


class WorkflowStateMachine:
    """
    State machine governing workflow lifecycle transitions.

    Enforces permitted transition rules and maintains an immutable audit log of transitions.
    """

    ALLOWED_TRANSITIONS: Dict[WorkflowState, Set[WorkflowState]] = {
        WorkflowState.DRAFT: {
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        },
        WorkflowState.AWAITING_APPROVAL: {
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        },
        WorkflowState.RUNNING: {
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.PAUSED,
            WorkflowState.SUCCEEDED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        },
        WorkflowState.PAUSED: {
            WorkflowState.RUNNING,
            WorkflowState.CANCELLED,
            WorkflowState.FAILED,
        },
        # Terminal states have no valid transitions out
        WorkflowState.SUCCEEDED: set(),
        WorkflowState.FAILED: set(),
        WorkflowState.CANCELLED: set(),
    }

    def __init__(self, initial_state: WorkflowState = WorkflowState.DRAFT):
        self._current_state = initial_state
        self._history: List[StateTransitionRecord] = []

    @property
    def current_state(self) -> WorkflowState:
        """Get the current state."""
        return self._current_state

    @property
    def history(self) -> List[StateTransitionRecord]:
        """Get the list of recorded transitions."""
        return list(self._history)

    def is_terminal(self) -> bool:
        """Check if the state machine has reached a terminal state."""
        return self._current_state in {
            WorkflowState.SUCCEEDED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }

    def can_transition_to(self, target_state: WorkflowState) -> bool:
        """Check if a transition to the target state is legally permitted."""
        allowed = self.ALLOWED_TRANSITIONS.get(self._current_state, set())
        return target_state in allowed

    def transition_to(self, target_state: WorkflowState, reason: str = "") -> None:
        """
        Transition the state machine to target_state.

        Args:
            target_state: The desired WorkflowState.
            reason: Optional explanation or trigger context.

        Raises:
            InvalidStateTransitionError: If the transition is prohibited.
        """
        if target_state == self._current_state:
            if self.is_terminal():
                raise InvalidStateTransitionError(
                    from_state=self._current_state,
                    to_state=target_state,
                    reason=reason or f"Cannot transition from terminal state '{self._current_state.value}' to itself.",
                )
            # Redundant non-terminal self-transition is a no-op
            return

        if not self.can_transition_to(target_state):
            raise InvalidStateTransitionError(
                from_state=self._current_state,
                to_state=target_state,
                reason=reason or f"Transition not allowed from {self._current_state.value}",
            )

        record = StateTransitionRecord(
            from_state=self._current_state,
            to_state=target_state,
            reason=reason,
        )
        self._history.append(record)
        self._current_state = target_state

    def reset_to_draft(self) -> None:
        """
        Reset state machine to DRAFT state.
        
        NOTE: This method is strictly intended for test-only scenarios.
        In normal operation, instantiate a new state machine for a new workflow plan.
        """
        self._current_state = WorkflowState.DRAFT
        self._history.clear()


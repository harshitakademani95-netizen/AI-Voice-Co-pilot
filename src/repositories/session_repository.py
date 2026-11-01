"""Thread-safe in-memory session repository with enforced state machine."""
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional, Set
import uuid

from src.core.errors import (
    AppError,
    InvalidStateTransitionError,
    SessionNotFoundError,
    SessionValidationError,
)
from src.models.session import Session, SessionEvent, SessionState


class InMemorySessionRepository:
    """In-memory storage and state transition engine for sessions.
    
    Guarantees thread-safe access and strict enforcement of permitted
    lifecycle transitions across:
    - created -> {active, failed, expired}
    - active  -> {paused, stopping, completed, failed, expired}
    - paused  -> {active, stopping, failed, expired}
    - stopping-> {completed, failed}
    - completed -> (terminal)
    - failed    -> (terminal)
    - expired   -> (terminal)
    """

    # Permitted state transition map
    ALLOWED_TRANSITIONS: Dict[SessionState, Set[SessionState]] = {
        SessionState.CREATED: {
            SessionState.ACTIVE,
            SessionState.FAILED,
            SessionState.EXPIRED,
        },
        SessionState.ACTIVE: {
            SessionState.PAUSED,
            SessionState.STOPPING,
            SessionState.COMPLETED,
            SessionState.FAILED,
            SessionState.EXPIRED,
        },
        SessionState.PAUSED: {
            SessionState.ACTIVE,
            SessionState.STOPPING,
            SessionState.FAILED,
            SessionState.EXPIRED,
        },
        SessionState.STOPPING: {
            SessionState.COMPLETED,
            SessionState.FAILED,
        },
        SessionState.COMPLETED: set(),  # Terminal
        SessionState.FAILED: set(),     # Terminal
        SessionState.EXPIRED: set(),    # Terminal
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, Session] = {}

    def is_healthy(self) -> bool:
        """Returns True if the repository data structure is accessible and intact."""
        with self._lock:
            return isinstance(self._sessions, dict)

    def create(
        self,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        """Initializes a new session in the CREATED state."""
        with self._lock:
            sid = session_id.strip() if session_id else f"session-{uuid.uuid4().hex[:8]}"
            if not sid:
                raise SessionValidationError("Session ID cannot be empty.")

            if sid in self._sessions:
                raise AppError(
                    status_code=409,
                    code="SESSION_ALREADY_EXISTS",
                    message_safe_for_user=f"A session with ID '{sid}' already exists.",
                    retryable=False,
                    details={"session_id": sid},
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            new_session = Session(
                session_id=sid,
                state=SessionState.CREATED,
                created_at=now_iso,
                updated_at=now_iso,
                metadata=metadata or {},
                events=[
                    SessionEvent(
                        event_type="session_created",
                        payload={"initial_state": SessionState.CREATED.value},
                        timestamp=now_iso,
                    )
                ],
            )
            self._sessions[sid] = new_session
            return new_session.model_copy(deep=True)

    def get(self, session_id: str) -> Session:
        """Retrieves a session by ID. Raises SessionNotFoundError if not found."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            return self._sessions[session_id].model_copy(deep=True)

    def list_all(self) -> List[Session]:
        """Lists all existing sessions in memory."""
        with self._lock:
            return [s.model_copy(deep=True) for s in self._sessions.values()]

    def transition(
        self,
        session_id: str,
        to_state: SessionState,
        reason: Optional[str] = None,
    ) -> Session:
        """Transitions an existing session to a target state adhering to transition rules."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)

            session = self._sessions[session_id]
            current_state = session.state

            # Reject transition to same state or not in allowed set
            if to_state == current_state:
                raise InvalidStateTransitionError(
                    current_state=current_state.value,
                    target_state=to_state.value,
                    reason=f"Session is already in state '{current_state.value}'.",
                )

            allowed_targets = self.ALLOWED_TRANSITIONS.get(current_state, set())
            if to_state not in allowed_targets:
                if not allowed_targets:
                    extra_reason = (
                        f"State '{current_state.value}' is terminal; no further transitions are allowed."
                    )
                else:
                    valid_list = ", ".join(f"'{s.value}'" for s in allowed_targets)
                    extra_reason = (
                        f"Allowed transitions from '{current_state.value}' are: [{valid_list}]."
                    )
                if reason:
                    extra_reason += f" Provided reason: {reason}"
                raise InvalidStateTransitionError(
                    current_state=current_state.value,
                    target_state=to_state.value,
                    reason=extra_reason,
                )

            # Perform the transition
            now_iso = datetime.now(timezone.utc).isoformat()
            session.state = to_state
            session.updated_at = now_iso
            
            # Record transition event
            transition_event = SessionEvent(
                event_type="state_transition",
                payload={
                    "from_state": current_state.value,
                    "to_state": to_state.value,
                    "reason": reason,
                },
                timestamp=now_iso,
            )
            session.events.append(transition_event)

            return session.model_copy(deep=True)

    def add_event(
        self,
        session_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SessionEvent:
        """Adds a mock or runtime event to an active session."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)

            session = self._sessions[session_id]
            
            # Sessions in terminal failure or expiration cannot record new operational events
            if session.state in (SessionState.FAILED, SessionState.EXPIRED):
                raise InvalidStateTransitionError(
                    current_state=session.state.value,
                    target_state="event_dispatch",
                    reason=f"Cannot record events for session in terminal '{session.state.value}' state.",
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            event = SessionEvent(
                event_type=event_type,
                payload=payload or {},
                timestamp=now_iso,
            )
            session.events.append(event)
            session.updated_at = now_iso
            return event.model_copy(deep=True)

    def delete(self, session_id: str) -> bool:
        """Removes a session by ID."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def clear(self) -> None:
        """Clears all sessions (used for test isolation)."""
        with self._lock:
            self._sessions.clear()


# Singleton repository instance
session_repository = InMemorySessionRepository()

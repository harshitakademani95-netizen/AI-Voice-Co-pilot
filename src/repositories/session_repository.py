"""Thread-safe in-memory session repository with enforced state machine and event publishing."""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Any, Dict, List, Optional, Set
import uuid

from src.config import settings
from src.core.errors import (
    AppError,
    InvalidStateTransitionError,
    SessionNotFoundError,
    SessionValidationError,
)
from src.core.security import redact_sensitive_data
from src.models.session import Session, SessionEvent, SessionState

logger = logging.getLogger("backend.repository")


class InMemorySessionRepository:
    """In-memory storage, state transition engine, and event pub/sub for sessions.
    
    Guarantees thread-safe access and strict enforcement of permitted
    lifecycle transitions across:
    - created  -> {active, stopped, failed, expired}
    - active   -> {paused, stopping, stopped, completed, failed, expired}
    - paused   -> {active, stopping, stopped, failed, expired}
    - stopping -> {stopped, completed, failed}
    - stopped  -> (terminal)
    - completed-> (terminal)
    - failed   -> (terminal)
    - expired  -> (terminal)
    """

    ALLOWED_TRANSITIONS: Dict[SessionState, Set[SessionState]] = {
        SessionState.CREATED: {
            SessionState.ACTIVE,
            SessionState.STOPPED,
            SessionState.FAILED,
            SessionState.EXPIRED,
        },
        SessionState.ACTIVE: {
            SessionState.PAUSED,
            SessionState.STOPPING,
            SessionState.STOPPED,
            SessionState.COMPLETED,
            SessionState.FAILED,
            SessionState.EXPIRED,
        },
        SessionState.PAUSED: {
            SessionState.ACTIVE,
            SessionState.STOPPING,
            SessionState.STOPPED,
            SessionState.FAILED,
            SessionState.EXPIRED,
        },
        SessionState.STOPPING: {
            SessionState.STOPPED,
            SessionState.COMPLETED,
            SessionState.FAILED,
        },
        SessionState.STOPPED: set(),    # Terminal
        SessionState.COMPLETED: set(),  # Terminal
        SessionState.FAILED: set(),     # Terminal
        SessionState.EXPIRED: set(),    # Terminal
    }

    TERMINAL_STATES: Set[SessionState] = {
        SessionState.STOPPED,
        SessionState.COMPLETED,
        SessionState.FAILED,
        SessionState.EXPIRED,
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, Session] = {}
        self._listeners: Dict[str, Set[asyncio.Queue]] = defaultdict(set)

    def is_healthy(self) -> bool:
        """Returns True if the repository data structure is accessible and intact."""
        with self._lock:
            return isinstance(self._sessions, dict)

    def _check_ttl_unlocked(self, session: Session) -> bool:
        """Checks if a session has expired according to configured TTL.
        
        Transitions state to EXPIRED if expired and not already terminal.
        """
        if session.state in self.TERMINAL_STATES:
            return False

        try:
            # Parse session updated_at or created_at
            last_activity = datetime.fromisoformat(session.updated_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            elapsed_seconds = (now - last_activity).total_seconds()
            
            if elapsed_seconds > settings.session_ttl_seconds:
                old_state = session.state
                now_iso = now.isoformat()
                session.state = SessionState.EXPIRED
                session.updated_at = now_iso
                session.expires_at = now_iso
                
                expire_event = SessionEvent(
                    event_type="session_expired",
                    session_id=session.session_id,
                    sequence_number=len(session.events) + 1,
                    payload={
                        "from_state": old_state.value,
                        "to_state": SessionState.EXPIRED.value,
                        "reason": f"TTL exceeded ({int(elapsed_seconds)}s > {settings.session_ttl_seconds}s)",
                    },
                    timestamp=now_iso,
                )
                session.events.append(expire_event)
                self._dispatch_event_unlocked(session.session_id, expire_event)
                return True
        except Exception as exc:
            safe_exc = redact_sensitive_data(str(exc))
            logger.warning(f"Error checking TTL for session {session.session_id}: {safe_exc}")
        return False

    def create(
        self,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
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
            expires_iso = (datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)).isoformat()
            created_event = SessionEvent(
                event_type="session_created",
                session_id=sid,
                correlation_id=correlation_id,
                sequence_number=1,
                payload={"initial_state": SessionState.CREATED.value},
                timestamp=now_iso,
            )

            new_session = Session(
                session_id=sid,
                state=SessionState.CREATED,
                created_at=now_iso,
                updated_at=now_iso,
                expires_at=expires_iso,
                metadata=metadata or {},
                events=[created_event],
            )
            self._sessions[sid] = new_session
            self._dispatch_event_unlocked(sid, created_event)
            return new_session.model_copy(deep=True)

    def get(self, session_id: str, check_ttl: bool = True) -> Session:
        """Retrieves a session by ID. Raises SessionNotFoundError if not found."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            session = self._sessions[session_id]
            if check_ttl:
                self._check_ttl_unlocked(session)
            return session.model_copy(deep=True)

    def list_all(self, check_ttl: bool = True) -> List[Session]:
        """Lists all existing sessions in memory."""
        with self._lock:
            if check_ttl:
                for session in self._sessions.values():
                    self._check_ttl_unlocked(session)
            return [s.model_copy(deep=True) for s in self._sessions.values()]

    def transition(
        self,
        session_id: str,
        to_state: SessionState,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> Session:
        """Transitions an existing session to a target state adhering to transition rules."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)

            session = self._sessions[session_id]
            self._check_ttl_unlocked(session)
            current_state = session.state

            # Reject transition to same state
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
                    valid_list = ", ".join(f"'{s.value}'" for s in sorted(allowed_targets, key=lambda s: s.value))
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

            # Determine appropriate event type
            if event_type is None:
                if to_state == SessionState.ACTIVE and current_state == SessionState.CREATED:
                    event_type = "session_activated"
                elif to_state == SessionState.ACTIVE and current_state == SessionState.PAUSED:
                    event_type = "session_resumed"
                elif to_state == SessionState.PAUSED:
                    event_type = "session_paused"
                elif to_state == SessionState.STOPPED:
                    event_type = "session_stopped"
                elif to_state == SessionState.EXPIRED:
                    event_type = "session_expired"
                else:
                    event_type = "state_transition"

            now_iso = datetime.now(timezone.utc).isoformat()
            session.state = to_state
            session.updated_at = now_iso
            if to_state in self.TERMINAL_STATES:
                session.expires_at = now_iso
            else:
                session.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)).isoformat()

            transition_event = SessionEvent(
                event_type=event_type,
                session_id=session_id,
                correlation_id=correlation_id,
                sequence_number=len(session.events) + 1,
                payload={
                    "from_state": current_state.value,
                    "to_state": to_state.value,
                    "reason": reason,
                },
                timestamp=now_iso,
            )
            session.events.append(transition_event)
            self._dispatch_event_unlocked(session_id, transition_event)
            return session.model_copy(deep=True)

    def pause(
        self,
        session_id: str,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Session:
        """Transitions an active session to paused state."""
        return self.transition(
            session_id=session_id,
            to_state=SessionState.PAUSED,
            reason=reason or "User paused session",
            correlation_id=correlation_id,
            event_type="session_paused",
        )

    def resume(
        self,
        session_id: str,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Session:
        """Transitions a paused session back to active state."""
        return self.transition(
            session_id=session_id,
            to_state=SessionState.ACTIVE,
            reason=reason or "User resumed session",
            correlation_id=correlation_id,
            event_type="session_resumed",
        )

    def stop(
        self,
        session_id: str,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Session:
        """Transitions an active or paused session to stopped state."""
        return self.transition(
            session_id=session_id,
            to_state=SessionState.STOPPED,
            reason=reason or "User stopped session",
            correlation_id=correlation_id,
            event_type="session_stopped",
        )

    def add_event(
        self,
        session_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> SessionEvent:
        """Adds an event to an active session."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)

            session = self._sessions[session_id]
            self._check_ttl_unlocked(session)

            if session.state in self.TERMINAL_STATES:
                raise InvalidStateTransitionError(
                    current_state=session.state.value,
                    target_state="event_dispatch",
                    reason=f"Cannot record events for session in terminal '{session.state.value}' state.",
                )

            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()
            event = SessionEvent(
                event_type=event_type,
                session_id=session_id,
                correlation_id=correlation_id,
                sequence_number=len(session.events) + 1,
                payload=payload or {},
                timestamp=now_iso,
            )
            session.events.append(event)
            session.updated_at = now_iso
            session.expires_at = (now_dt + timedelta(seconds=settings.session_ttl_seconds)).isoformat()
            self._dispatch_event_unlocked(session_id, event)
            return event.model_copy(deep=True)

    def _dispatch_event_unlocked(self, session_id: str, event: SessionEvent) -> None:
        """Broadcasts an event to all active SSE queues for this session."""
        queues = self._listeners.get(session_id, set())
        for q in list(queues):
            try:
                q.put_nowait(event.model_copy(deep=True))
            except Exception as exc:
                safe_exc = redact_sensitive_data(str(exc))
                logger.debug(f"Could not deliver event to SSE queue: {safe_exc}")

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """Registers a new SSE listener queue for a session."""
        with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            q: asyncio.Queue = asyncio.Queue()
            self._listeners[session_id].add(q)
            return q

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        """Unregisters an SSE listener queue."""
        with self._lock:
            if session_id in self._listeners:
                self._listeners[session_id].discard(queue)
                if not self._listeners[session_id]:
                    del self._listeners[session_id]

    def delete(self, session_id: str) -> bool:
        """Removes a session by ID."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._listeners.pop(session_id, None)
                return True
            return False

    def clear(self) -> None:
        """Clears all sessions and listeners (used for test isolation)."""
        with self._lock:
            self._sessions.clear()
            self._listeners.clear()


# Singleton repository instance
session_repository = InMemorySessionRepository()

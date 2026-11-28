"""Thread-safe in-memory idempotency management for safe command replay and concurrency control."""
import hashlib
import json
import threading
from typing import Any, Dict, Optional, Tuple

from src.core.errors import AppError


class IdempotencyRecord:
    """Represents an in-flight or completed record for an idempotent operation."""
    __slots__ = ("request_hash", "status_code", "response_data", "completed", "event")

    def __init__(
        self,
        request_hash: str,
        status_code: int = 0,
        response_data: Optional[Dict[str, Any]] = None,
        completed: bool = False,
    ) -> None:
        self.request_hash = request_hash
        self.status_code = status_code
        self.response_data = response_data or {}
        self.completed = completed
        self.event = threading.Event()
        if completed:
            self.event.set()


class InMemoryIdempotencyManager:
    """In-memory thread-safe store for idempotent request execution.
    
    Guarantees:
    - Same Idempotency-Key + Identical request -> Returns identical cached response.
    - Same Idempotency-Key + Different request -> Returns HTTP 409 IDEMPOTENCY_CONFLICT.
    - Concurrent duplicate commands -> Safely coordinated via in-flight event waiting.
    - Thread-safety via threading.RLock.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, IdempotencyRecord] = {}

    @staticmethod
    def compute_request_hash(method: str, path: str, body: Any = None) -> str:
        """Computes a deterministic SHA-256 fingerprint for a request."""
        hasher = hashlib.sha256()
        hasher.update(method.upper().strip().encode("utf-8"))
        hasher.update(path.strip().encode("utf-8"))
        if body is not None:
            if isinstance(body, (dict, list)):
                payload_str = json.dumps(body, sort_keys=True, separators=(",", ":"))
            else:
                payload_str = str(body)
            hasher.update(payload_str.encode("utf-8"))
        return hasher.hexdigest()

    def check(self, key: str, request_hash: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        """Checks if key is already processed or in-flight.
        
        Returns:
            Tuple of (status_code, response_data) if exact match found.
            None if key has not been seen before (caller becomes the executor).
            
        Raises:
            AppError (409): if key exists but was called with different parameters.
        """
        event_to_wait = None
        with self._lock:
            record = self._store.get(key)
            if record is None:
                # Reserve key as in-flight
                self._store[key] = IdempotencyRecord(request_hash=request_hash, completed=False)
                return None

            if record.request_hash != request_hash:
                raise AppError(
                    status_code=409,
                    code="IDEMPOTENCY_CONFLICT",
                    message_safe_for_user=(
                        f"Idempotency key '{key}' was previously used with a different request payload or target."
                    ),
                    retryable=False,
                    details={"idempotency_key": key},
                )

            if record.completed:
                return (record.status_code, record.response_data)

            # Concurrent in-flight request with same key & payload: prepare to wait
            event_to_wait = record.event

        # Wait outside lock for concurrent in-flight executor to complete
        if event_to_wait is not None:
            event_to_wait.wait(timeout=5.0)
            with self._lock:
                record = self._store.get(key)
                if record and record.completed:
                    return (record.status_code, record.response_data)

        return None

    def record(self, key: str, request_hash: str, status_code: int, response_data: Dict[str, Any]) -> None:
        """Stores the result of an executed idempotent command and releases waiting threads."""
        with self._lock:
            record = self._store.get(key)
            if record is not None:
                record.status_code = status_code
                record.response_data = response_data
                record.completed = True
                record.event.set()
            else:
                new_record = IdempotencyRecord(
                    request_hash=request_hash,
                    status_code=status_code,
                    response_data=response_data,
                    completed=True,
                )
                self._store[key] = new_record

    def cancel_in_flight(self, key: str) -> None:
        """Cleans up in-flight reservation if operation failed with exception."""
        with self._lock:
            record = self._store.get(key)
            if record and not record.completed:
                record.event.set()
                del self._store[key]

    def clear(self) -> None:
        """Clears stored idempotency records (used during test isolation)."""
        with self._lock:
            for rec in self._store.values():
                rec.event.set()
            self._store.clear()


# Singleton instance
idempotency_manager = InMemoryIdempotencyManager()

"""
Bounded Audio Stream Buffer for Voice Stream Processing (Week 2, D12-D13).

Provides:
- Configurable capacity enforcement (never exceeds max limit)
- Explicit overflow handling with backpressure tracking (no silent drops)
- Sequence ID validation: gap events, total missing chunks, late chunks, and duplicate detection
- FIFO ordering for queueing and consumption
- Resource cleanup on audio session stop
- Complete operational metrics reporting with bounded memory guarantees
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Any, Deque, Dict, List, Optional, Set

from src.schemas.audio import AudioChunk, AudioError


class BufferPushStatus(str, Enum):
    """Result status of attempting to push a chunk into the bounded buffer."""
    ACCEPTED = "ACCEPTED"
    DROPPED = "DROPPED"
    REJECTED_INVALID = "REJECTED_INVALID"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_LATE = "REJECTED_LATE"


@dataclass(frozen=True)
class BufferPushResult:
    """
    Detailed outcome of pushing a chunk to the buffer.
    
    Attributes:
        status: BufferPushStatus indicating outcome.
        sequence_id: Sequence ID of the target chunk.
        buffer_size: Current buffer size after the operation.
        dropped_count: Cumulative dropped chunks counter.
        reason: Diagnostic reason string describing outcome.
    """
    status: BufferPushStatus
    sequence_id: Optional[int]
    buffer_size: int
    dropped_count: int
    reason: Optional[str] = None


@dataclass
class BufferMetrics:
    """
    Real-time performance and integrity counters for the bounded buffer.
    
    Attributes:
        total_received: Total chunks submitted to push().
        total_consumed: Total chunks popped from buffer.
        total_dropped: Total chunks dropped due to overflow.
        current_size: Current queued chunks count.
        max_size_reached: High-water mark of queue occupancy.
        sequence_gap_events: Discrete jump incidents where sequence_id > expected.
        missing_chunks_total: Cumulative sum of missing sequence IDs across all gap events.
        late_chunks_detected: Count of out-of-order chunks older than expected pointer.
        duplicate_chunks_detected: Count of repeated sequence IDs.
        capacity: Configured queue limit.
    """
    total_received: int = 0
    total_consumed: int = 0
    total_dropped: int = 0
    current_size: int = 0
    max_size_reached: int = 0
    sequence_gap_events: int = 0
    missing_chunks_total: int = 0
    late_chunks_detected: int = 0
    duplicate_chunks_detected: int = 0
    capacity: int = 0

    @property
    def sequence_gaps_detected(self) -> int:
        """Alias for sequence_gap_events (retained for backward compatibility)."""
        return self.sequence_gap_events

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to a serializable dictionary."""
        return {
            "total_received": self.total_received,
            "total_consumed": self.total_consumed,
            "total_dropped": self.total_dropped,
            "current_size": self.current_size,
            "max_size_reached": self.max_size_reached,
            "sequence_gap_events": self.sequence_gap_events,
            "missing_chunks_total": self.missing_chunks_total,
            "sequence_gaps_detected": self.sequence_gap_events,  # backward compatibility
            "late_chunks_detected": self.late_chunks_detected,
            "duplicate_chunks_detected": self.duplicate_chunks_detected,
            "capacity": self.capacity,
        }


class BoundedAudioBuffer:
    """
    Bounded, thread-safe FIFO buffer for AudioChunk objects.
    
    Guarantees:
    - Never exceeds configured capacity.
    - Explicitly records drops during overflow without crashing or silent discard.
    - Tracks monotonic sequence progression with separate gap event and missing ID counts.
    - Rejects duplicate and late chunks to protect FIFO ordering.
    - Uses a bounded sliding window (maxlen=4096) for seen IDs to avoid unbounded memory growth.
    - Safely releases resources upon stop.
    """

    DEFAULT_SEEN_WINDOW_SIZE = 4096

    def __init__(self, capacity: int = 50, seen_window_size: int = DEFAULT_SEEN_WINDOW_SIZE) -> None:
        if not isinstance(capacity, int) or capacity <= 0:
            raise AudioError(
                message=f"Buffer capacity must be a positive integer, got: {capacity}",
                code="INVALID_PARAMETER",
                details={"capacity": capacity},
            )

        self._capacity: int = capacity
        self._queue: Deque[AudioChunk] = deque()
        self._lock: threading.Lock = threading.Lock()

        # Integrity tracking with bounded memory window
        self._expected_sequence_id: Optional[int] = None
        self._seen_window: Deque[int] = deque(maxlen=seen_window_size)
        self._seen_sequence_ids: Set[int] = set()

        # Operational counters
        self._total_received: int = 0
        self._total_consumed: int = 0
        self._total_dropped: int = 0
        self._max_size_reached: int = 0
        self._sequence_gap_events: int = 0
        self._missing_chunks_total: int = 0
        self._late_chunks_detected: int = 0
        self._duplicate_chunks_detected: int = 0

    @property
    def capacity(self) -> int:
        """Configured maximum capacity of the buffer."""
        return self._capacity

    @property
    def current_size(self) -> int:
        """Current number of chunks in the buffer."""
        with self._lock:
            return len(self._queue)

    @property
    def is_empty(self) -> bool:
        """True if the buffer holds no chunks."""
        with self._lock:
            return len(self._queue) == 0

    @property
    def is_full(self) -> bool:
        """True if current size has reached capacity."""
        with self._lock:
            return len(self._queue) >= self._capacity

    def _record_seen_seq(self, seq: int) -> None:
        """Record sequence ID in bounded sliding window."""
        if len(self._seen_window) == self._seen_window.maxlen:
            discarded = self._seen_window.popleft()
            self._seen_sequence_ids.discard(discarded)
        self._seen_window.append(seq)
        self._seen_sequence_ids.add(seq)

    def push(self, chunk: Any) -> BufferPushResult:
        """
        Attempt to push an AudioChunk into the bounded FIFO buffer.
        
        Ordered policy:
        1. Type check: Non-AudioChunk rejected with REJECTED_INVALID.
        2. Duplicate check: Seen sequence IDs rejected with REJECTED_DUPLICATE.
        3. Late check: Sequence IDs older than expected pointer rejected with REJECTED_LATE.
        4. Gap check: Sequence IDs beyond expected increment gap events and missing chunk sum.
        5. Capacity check: Full buffer drops chunk with DROPPED and increments dropped counter.
        6. Enqueue: Accepted chunk enqueued in FIFO order.
        """
        with self._lock:
            self._total_received += 1

            # 1. Type validation
            if not isinstance(chunk, AudioChunk):
                return BufferPushResult(
                    status=BufferPushStatus.REJECTED_INVALID,
                    sequence_id=getattr(chunk, "sequence_id", None),
                    buffer_size=len(self._queue),
                    dropped_count=self._total_dropped,
                    reason=f"INVALID_PAYLOAD: Invalid payload type, expected AudioChunk, got {type(chunk).__name__}",
                )

            seq = chunk.sequence_id

            # 2. Duplicate validation
            if seq in self._seen_sequence_ids:
                self._duplicate_chunks_detected += 1
                return BufferPushResult(
                    status=BufferPushStatus.REJECTED_DUPLICATE,
                    sequence_id=seq,
                    buffer_size=len(self._queue),
                    dropped_count=self._total_dropped,
                    reason=f"DUPLICATE_CHUNK: Sequence ID {seq} was already received",
                )

            # 3. Late chunk validation
            if self._expected_sequence_id is not None and seq < self._expected_sequence_id:
                self._late_chunks_detected += 1
                self._record_seen_seq(seq)
                return BufferPushResult(
                    status=BufferPushStatus.REJECTED_LATE,
                    sequence_id=seq,
                    buffer_size=len(self._queue),
                    dropped_count=self._total_dropped,
                    reason=(
                        f"LATE_CHUNK: Sequence ID {seq} is older than expected pointer "
                        f"{self._expected_sequence_id}; rejected to preserve monotonic FIFO"
                    ),
                )

            # 4. Sequence gap tracking & expected pointer advancement
            if self._expected_sequence_id is None:
                self._expected_sequence_id = seq
            elif seq > self._expected_sequence_id:
                self._sequence_gap_events += 1
                self._missing_chunks_total += (seq - self._expected_sequence_id)

            self._expected_sequence_id = seq + 1
            self._record_seen_seq(seq)

            # 5. Capacity enforcement (Overflow / Backpressure policy)
            if len(self._queue) >= self._capacity:
                self._total_dropped += 1
                return BufferPushResult(
                    status=BufferPushStatus.DROPPED,
                    sequence_id=seq,
                    buffer_size=len(self._queue),
                    dropped_count=self._total_dropped,
                    reason="BUFFER_OVERFLOW: buffer is at maximum capacity",
                )

            # 6. Accepted FIFO enqueue
            self._queue.append(chunk)
            current_len = len(self._queue)
            if current_len > self._max_size_reached:
                self._max_size_reached = current_len

            return BufferPushResult(
                status=BufferPushStatus.ACCEPTED,
                sequence_id=seq,
                buffer_size=current_len,
                dropped_count=self._total_dropped,
                reason=None,
            )

    def pop(self) -> Optional[AudioChunk]:
        """
        Dequeue the oldest AudioChunk (FIFO order).
        Returns None if buffer is empty.
        """
        with self._lock:
            if not self._queue:
                return None
            chunk = self._queue.popleft()
            self._total_consumed += 1
            return chunk

    def peek(self) -> Optional[AudioChunk]:
        """
        Inspect the oldest AudioChunk without removing it.
        Returns None if buffer is empty.
        """
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0]

    def clear(self) -> int:
        """
        Drain all buffered chunks and release memory.
        Returns the count of purged chunks.
        """
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def reset_metrics(self) -> None:
        """Reset operational and anomaly metrics."""
        with self._lock:
            self._total_received = 0
            self._total_consumed = 0
            self._total_dropped = 0
            self._max_size_reached = len(self._queue)
            self._sequence_gap_events = 0
            self._missing_chunks_total = 0
            self._late_chunks_detected = 0
            self._duplicate_chunks_detected = 0
            self._expected_sequence_id = None
            self._seen_window.clear()
            self._seen_sequence_ids.clear()

    def get_metrics(self) -> BufferMetrics:
        """Retrieve a snapshot of current operational metrics."""
        with self._lock:
            return BufferMetrics(
                total_received=self._total_received,
                total_consumed=self._total_consumed,
                total_dropped=self._total_dropped,
                current_size=len(self._queue),
                max_size_reached=self._max_size_reached,
                sequence_gap_events=self._sequence_gap_events,
                missing_chunks_total=self._missing_chunks_total,
                late_chunks_detected=self._late_chunks_detected,
                duplicate_chunks_detected=self._duplicate_chunks_detected,
                capacity=self._capacity,
            )

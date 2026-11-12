"""
Unit tests for Bounded Audio Stream Buffer (Week 2, D12-D13).
"""

import unittest

from src.audio.buffer import (
    BoundedAudioBuffer,
    BufferMetrics,
    BufferPushResult,
    BufferPushStatus,
)
from src.audio.pipeline import create_deterministic_chunk
from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class TestBoundedAudioBuffer(unittest.TestCase):
    """Test suite covering BoundedAudioBuffer queueing, backpressure, drops, and metrics."""

    def setUp(self) -> None:
        self.capacity = 5
        self.buffer = BoundedAudioBuffer(capacity=self.capacity)
        self.fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)

    def test_buffer_initial_state(self) -> None:
        """Verify initial state of an empty bounded buffer."""
        self.assertEqual(self.buffer.capacity, self.capacity)
        self.assertEqual(self.buffer.current_size, 0)
        self.assertTrue(self.buffer.is_empty)
        self.assertFalse(self.buffer.is_full)
        self.assertIsNone(self.buffer.pop())
        self.assertIsNone(self.buffer.peek())

    def test_fifo_ordering_and_consumption(self) -> None:
        """Verify chunks are enqueued and dequeued in strict FIFO order."""
        chunks = [create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02) for i in range(3)]
        for c in chunks:
            res = self.buffer.push(c)
            self.assertEqual(res.status, BufferPushStatus.ACCEPTED)

        self.assertEqual(self.buffer.current_size, 3)
        self.assertEqual(self.buffer.peek().sequence_id, 0)

        # Dequeue
        c0 = self.buffer.pop()
        c1 = self.buffer.pop()
        c2 = self.buffer.pop()
        self.assertEqual(c0.sequence_id, 0)
        self.assertEqual(c1.sequence_id, 1)
        self.assertEqual(c2.sequence_id, 2)
        self.assertTrue(self.buffer.is_empty)

        # Metrics verification
        m = self.buffer.get_metrics()
        self.assertEqual(m.total_received, 3)
        self.assertEqual(m.total_consumed, 3)
        self.assertEqual(m.total_dropped, 0)

    def test_overflow_and_backpressure_drop_policy(self) -> None:
        """
        Verify buffer rejects chunks when capacity is reached and increments dropped counter.
        Does NOT silently discard chunks.
        """
        # Fill buffer to capacity (5 chunks)
        for i in range(self.capacity):
            res = self.buffer.push(create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02))
            self.assertEqual(res.status, BufferPushStatus.ACCEPTED)

        self.assertTrue(self.buffer.is_full)
        self.assertEqual(self.buffer.current_size, self.capacity)

        # 6th chunk exceeds capacity -> DROPPED
        overflow_chunk = create_deterministic_chunk(sequence_id=self.capacity, timestamp=self.capacity * 0.02)
        res_drop = self.buffer.push(overflow_chunk)
        self.assertEqual(res_drop.status, BufferPushStatus.DROPPED)
        self.assertEqual(res_drop.dropped_count, 1)
        self.assertIn("BUFFER_OVERFLOW", res_drop.reason)

        # Buffer size remains exactly at capacity
        self.assertEqual(self.buffer.current_size, self.capacity)

        # 7th chunk also dropped
        res_drop2 = self.buffer.push(create_deterministic_chunk(sequence_id=6, timestamp=6 * 0.02))
        self.assertEqual(res_drop2.status, BufferPushStatus.DROPPED)
        self.assertEqual(res_drop2.dropped_count, 2)

        # Metrics check
        metrics = self.buffer.get_metrics()
        self.assertEqual(metrics.total_received, 7)
        self.assertEqual(metrics.total_dropped, 2)
        self.assertEqual(metrics.max_size_reached, self.capacity)

    def test_sequence_gap_detection(self) -> None:
        """Verify gaps in sequence IDs are detected and counted as events and total missing."""
        # Push chunk 0
        self.buffer.push(create_deterministic_chunk(sequence_id=0, timestamp=0.0))
        # Skip chunks 1 and 2, push chunk 3
        self.buffer.push(create_deterministic_chunk(sequence_id=3, timestamp=0.06))

        m = self.buffer.get_metrics()
        # 1 jump event, 2 missing chunks (chunks 1 and 2)
        self.assertEqual(m.sequence_gap_events, 1)
        self.assertEqual(m.missing_chunks_total, 2)
        self.assertEqual(m.sequence_gaps_detected, 1)

    def test_sequence_gap_large_jump_metrics(self) -> None:
        """Verify exact count assertions for a large jump of 1000 IDs."""
        buf = BoundedAudioBuffer(capacity=50)
        buf.push(create_deterministic_chunk(sequence_id=0, timestamp=0.0))
        buf.push(create_deterministic_chunk(sequence_id=1000, timestamp=20.0))

        m = buf.get_metrics()
        self.assertEqual(m.sequence_gap_events, 1)
        self.assertEqual(m.missing_chunks_total, 999)
        self.assertEqual(m.sequence_gaps_detected, 1)

    def test_late_chunk_detection(self) -> None:
        """Verify out-of-order / late chunks are detected and rejected."""
        self.buffer.push(create_deterministic_chunk(sequence_id=5, timestamp=0.1))
        # Now push an older chunk with sequence_id 2
        res = self.buffer.push(create_deterministic_chunk(sequence_id=2, timestamp=0.04))

        self.assertEqual(res.status, BufferPushStatus.REJECTED_LATE)
        m = self.buffer.get_metrics()
        self.assertEqual(m.late_chunks_detected, 1)
        # Buffer holds only the first chunk
        self.assertEqual(self.buffer.current_size, 1)

    def test_duplicate_chunk_detection(self) -> None:
        """Verify duplicate sequence IDs are recorded, rejected, and do not increment late count."""
        c = create_deterministic_chunk(sequence_id=1, timestamp=0.02)
        res1 = self.buffer.push(c)
        self.assertEqual(res1.status, BufferPushStatus.ACCEPTED)

        res2 = self.buffer.push(c)
        self.assertEqual(res2.status, BufferPushStatus.REJECTED_DUPLICATE)

        m = self.buffer.get_metrics()
        self.assertEqual(m.duplicate_chunks_detected, 1)
        self.assertEqual(m.late_chunks_detected, 0)
        self.assertEqual(self.buffer.current_size, 1)

    def test_bounded_sliding_window_memory(self) -> None:
        """Verify sequence history is bounded by the sliding window (4096 entries)."""
        buf = BoundedAudioBuffer(capacity=5)
        # Push 5000 unique sequence IDs
        for i in range(5000):
            buf.push(create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02))

        # Internal seen set must not exceed sliding window maxlen
        self.assertLessEqual(len(buf._seen_sequence_ids), 4096)
        self.assertLessEqual(len(buf._seen_window), 4096)

    def test_invalid_chunk_payload_rejection(self) -> None:
        """Verify pushing non-AudioChunk object returns REJECTED_INVALID."""
        res = self.buffer.push("not-an-audio-chunk")
        self.assertEqual(res.status, BufferPushStatus.REJECTED_INVALID)
        self.assertIn("Invalid payload type", res.reason)
        self.assertEqual(self.buffer.current_size, 0)

    def test_buffer_clear_on_stop(self) -> None:
        """Verify clear() purges all elements and returns dropped count."""
        for i in range(3):
            self.buffer.push(create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02))
        self.assertEqual(self.buffer.current_size, 3)

        purged = self.buffer.clear()
        self.assertEqual(purged, 3)
        self.assertTrue(self.buffer.is_empty)
        self.assertEqual(self.buffer.current_size, 0)

    def test_invalid_capacity_rejection(self) -> None:
        """Verify buffer rejects non-positive or invalid capacity."""
        with self.assertRaises(AudioError) as ctx:
            BoundedAudioBuffer(capacity=0)
        self.assertEqual(ctx.exception.code, "INVALID_PARAMETER")

        with self.assertRaises(AudioError) as ctx2:
            BoundedAudioBuffer(capacity=-10)
        self.assertEqual(ctx2.exception.code, "INVALID_PARAMETER")


if __name__ == "__main__":
    unittest.main()


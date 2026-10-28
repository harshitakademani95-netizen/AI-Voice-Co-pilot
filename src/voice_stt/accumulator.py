"""Ordered Segment Accumulator for AI Voice Co-Pilot (W2 - STT).

This component aggregates streaming transcription events into a chronologically
ordered, deduplicated transcript. It cleanly separates ephemeral interim hypotheses
from committed immutable final segments, gracefully handles out-of-order arrivals,
and provides consolidated full-text reconstruction.
"""

from __future__ import annotations

import bisect
from typing import Any, Dict, List, Optional, Set

from voice_stt.schemas import (
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class OrderedSegmentAccumulator:
    """Maintains an ordered, deduplicated collection of transcription segments.

    Behavioral invariants:
    - Finalized segments are stored in strictly ascending order by start_time.
    - Out-of-order finalized segments are inserted into their proper chronological order.
    - Duplicate segments (matched by segment_id or identical text + timing) are suppressed.
    - Interim hypotheses update the current pending view without polluting finalized history.
    - When a final segment is committed, the current pending interim hypothesis is cleared.
    - Error events record status without corrupting previously finalized segments.
    """

    def __init__(self) -> None:
        self._final_segments: List[TranscriptSegment] = []
        self._seen_segment_ids: Set[str] = set()
        self._interim_segment: Optional[TranscriptSegment] = None
        self._last_error: Optional[STTErrorDetail] = None
        self._events_processed: int = 0

    @property
    def final_count(self) -> int:
        """Count of committed final segments."""
        return len(self._final_segments)

    @property
    def last_error(self) -> Optional[STTErrorDetail]:
        """Most recent error event received, if any."""
        return self._last_error

    def ingest_event(self, event: TranscriptEvent) -> None:
        """Ingest a TranscriptEvent into the accumulator.

        Args:
            event: TranscriptEvent to process.
        """
        self._events_processed += 1

        if event.event_type == TranscriptEventType.ERROR:
            self._last_error = event.error
            return

        if event.segment is None:
            return

        self.ingest_segment(event.segment)

    def ingest_segment(self, segment: TranscriptSegment) -> bool:
        """Ingest a TranscriptSegment.

        Args:
            segment: TranscriptSegment (interim or final).

        Returns:
            True if segment was added or updated; False if ignored as a duplicate.
        """
        if segment.is_final:
            return self._commit_final_segment(segment)
        else:
            self._interim_segment = segment
            return True

    def _commit_final_segment(self, segment: TranscriptSegment) -> bool:
        """Insert a finalized segment maintaining chronological order and deduplication."""
        # Check by segment_id
        if segment.segment_id in self._seen_segment_ids:
            return False

        # Check for overlapping duplicate content
        for existing in self._final_segments:
            if (
                abs(existing.start_time - segment.start_time) < 1e-4
                and abs(existing.end_time - segment.end_time) < 1e-4
                and existing.text.strip() == segment.text.strip()
            ):
                return False

        # Determine insertion index by start_time to ensure ordered sequence
        keys = [s.start_time for s in self._final_segments]
        idx = bisect.bisect_right(keys, segment.start_time)
        self._final_segments.insert(idx, segment)
        self._seen_segment_ids.add(segment.segment_id)

        # Clear active interim if final segment covers or exceeds it
        if self._interim_segment is not None:
            if segment.end_time >= self._interim_segment.end_time:
                self._interim_segment = None

        return True

    def get_final_segments(self) -> List[TranscriptSegment]:
        """Return a defensive copy of finalized segments in chronological order."""
        return list(self._final_segments)

    def get_interim_segment(self) -> Optional[TranscriptSegment]:
        """Return the current tentative in-flight interim segment, if active."""
        return self._interim_segment

    def get_full_transcript(self, include_interim: bool = False) -> str:
        """Reconstruct continuous transcript text.

        Args:
            include_interim: If True, appends current interim hypothesis at the end.

        Returns:
            Concatenated clean text string with single spacing.
        """
        parts = [seg.text.strip() for seg in self._final_segments if seg.text.strip()]
        if include_interim and self._interim_segment and self._interim_segment.text.strip():
            parts.append(self._interim_segment.text.strip())
        return " ".join(parts)

    def get_total_duration(self) -> float:
        """Calculate total span in seconds from earliest start to latest end time."""
        if not self._final_segments:
            return 0.0
        earliest = min(s.start_time for s in self._final_segments)
        latest = max(s.end_time for s in self._final_segments)
        return max(0.0, latest - earliest)

    def get_average_confidence(self) -> float:
        """Calculate mean confidence across all committed final segments."""
        if not self._final_segments:
            return 0.0
        return sum(s.confidence for s in self._final_segments) / len(self._final_segments)

    def reset(self) -> None:
        """Reset all accumulator state for a new session."""
        self._final_segments.clear()
        self._seen_segment_ids.clear()
        self._interim_segment = None
        self._last_error = None
        self._events_processed = 0

    def get_summary(self) -> Dict[str, Any]:
        """Generate structured diagnostic summary of accumulated transcript."""
        return {
            "final_segments_count": len(self._final_segments),
            "events_processed": self._events_processed,
            "has_active_interim": self._interim_segment is not None,
            "full_transcript": self.get_full_transcript(include_interim=False),
            "total_duration_seconds": round(self.get_total_duration(), 3),
            "average_confidence": round(self.get_average_confidence(), 4),
            "last_error": self._last_error.model_dump() if self._last_error else None,
        }

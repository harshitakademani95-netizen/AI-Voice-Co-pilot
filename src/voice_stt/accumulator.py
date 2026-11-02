"""Ordered Segment Accumulator for AI Voice Co-Pilot (W2 - STT).

This component aggregates streaming transcription events into a chronologically
ordered, deduplicated transcript. It cleanly separates ephemeral interim hypotheses
from committed immutable final segments, gracefully handles out-of-order arrivals,
suppresses duplicate delivery, and provides consolidated full-text reconstruction.
"""

from __future__ import annotations

import bisect
from typing import Any, Dict, List, Optional, Set

from voice_stt.schemas import (
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class OrderedSegmentAccumulator:
    """Maintains an ordered, deduplicated collection of transcription segments.

    Behavioral Invariants:
    1. Chronological Audio Order: Finalized segments are maintained in strictly
       non-decreasing order by audio `start_time`. Secondary sort is audio `end_time`.
    2. Separation of Interim and Final: Interim hypotheses are stored transiently
       in `_interim_segment` and are never appended to `_final_segments`.
    3. Reordering on Arrival: Segments arriving out of order are repositioned at their
       correct chronological index.
    4. Identity-Based Deduplication: Deduplication is strictly based on stable
       `segment_id` and `event_id`. Duplicate deliveries are suppressed. Legitimate
       segments with identical text at different times are preserved.
    5. Late Interim Protection: Late interim events arriving after their audio window
       has already been committed to final segments are discarded without corrupting state.
    6. Non-Destructive Error Handling: Ingesting error events records telemetry without
       clearing or corrupting previously committed final segments.
    7. Full Observability: Provides detailed event arrival tracking, distinguishing
       arrival order from audio chronology.
    """

    def __init__(self) -> None:
        self._final_segments: List[TranscriptSegment] = []
        self._seen_segment_ids: Set[str] = set()
        self._seen_event_ids: Set[str] = set()
        self._interim_segment: Optional[TranscriptSegment] = None
        self._last_error: Optional[STTErrorDetail] = None

        # Precise Telemetry & Diagnostics
        self._events_processed: int = 0
        self._interim_updates_count: int = 0
        self._duplicates_suppressed: int = 0
        self._out_of_order_count: int = 0
        self._arrival_history: List[Dict[str, Any]] = []

    @property
    def final_count(self) -> int:
        """Count of committed final segments."""
        return len(self._final_segments)

    @property
    def interim_updates_count(self) -> int:
        """Total count of interim hypothesis revisions processed."""
        return self._interim_updates_count

    @property
    def duplicates_suppressed(self) -> int:
        """Count of duplicate events detected and safely ignored."""
        return self._duplicates_suppressed

    @property
    def out_of_order_count(self) -> int:
        """Count of final segments that arrived out of audio chronological order."""
        return self._out_of_order_count

    @property
    def last_error(self) -> Optional[STTErrorDetail]:
        """Most recent error event received, if any."""
        return self._last_error

    def ingest_event(self, event: TranscriptEvent) -> bool:
        """Ingest a TranscriptEvent into the accumulator.

        Args:
            event: TranscriptEvent to process.

        Returns:
            True if event was processed; False if ignored as duplicate.
        """
        if not isinstance(event, TranscriptEvent):
            raise STTValidationError(f"Expected TranscriptEvent, got {type(event).__name__}")

        self._events_processed += 1

        # Check for duplicate event_id
        if event.event_id in self._seen_event_ids:
            self._duplicates_suppressed += 1
            self._record_arrival(event, is_duplicate=True, was_reordered=False)
            return False

        self._seen_event_ids.add(event.event_id)

        # Handle failure event
        if event.event_type == TranscriptEventType.ERROR:
            self._last_error = event.error
            self._record_arrival(event, is_duplicate=False, was_reordered=False)
            return True

        # Handle lifecycle events without segments
        if event.segment is None:
            self._record_arrival(event, is_duplicate=False, was_reordered=False)
            return True

        # Process segment payload
        result = self.ingest_segment(event.segment, event_id=event.event_id)
        return result

    def ingest_segment(self, segment: TranscriptSegment, event_id: Optional[str] = None) -> bool:
        """Ingest a TranscriptSegment directly.

        Args:
            segment: TranscriptSegment (interim or final).
            event_id: Optional associated event ID for diagnostic correlation.

        Returns:
            True if segment was added or updated; False if ignored as duplicate or stale.
        """
        if not isinstance(segment, TranscriptSegment):
            raise STTValidationError(f"Expected TranscriptSegment, got {type(segment).__name__}")

        if segment.is_final:
            return self._commit_final_segment(segment, event_id=event_id)
        else:
            return self._handle_interim_segment(segment, event_id=event_id)

    def _handle_interim_segment(self, segment: TranscriptSegment, event_id: Optional[str] = None) -> bool:
        """Process an in-flight interim segment hypothesis."""
        # Late Interim Protection:
        # If the interim segment ends before or at the latest committed final segment end_time,
        # it is a stale/late interim event whose audio span has already been finalized.
        if self._final_segments:
            max_finalized_end = max(s.end_time for s in self._final_segments)
            if segment.end_time <= max_finalized_end:
                # Stale interim; discard to protect committed state
                self._record_arrival(
                    None,
                    segment=segment,
                    is_duplicate=False,
                    was_reordered=False,
                    is_late_interim=True,
                )
                return False

        self._interim_segment = segment
        self._interim_updates_count += 1
        self._record_arrival(
            None,
            segment=segment,
            is_duplicate=False,
            was_reordered=False,
            is_late_interim=False,
        )
        return True

    def _commit_final_segment(self, segment: TranscriptSegment, event_id: Optional[str] = None) -> bool:
        """Insert a finalized segment maintaining chronological order and deduplication."""
        # Identity-Based Deduplication (by segment_id)
        if segment.segment_id in self._seen_segment_ids:
            self._duplicates_suppressed += 1
            self._record_arrival(None, segment=segment, is_duplicate=True, was_reordered=False)
            return False

        # Content + Boundary Deduplication (exact same audio window and text)
        for existing in self._final_segments:
            if (
                abs(existing.start_time - segment.start_time) < 1e-4
                and abs(existing.end_time - segment.end_time) < 1e-4
                and existing.text.strip() == segment.text.strip()
            ):
                self._duplicates_suppressed += 1
                self._record_arrival(None, segment=segment, is_duplicate=True, was_reordered=False)
                return False

        # Determine insertion point by audio start_time (secondary sort by end_time)
        # Using bisect on (start_time, end_time)
        keys = [(s.start_time, s.end_time) for s in self._final_segments]
        new_key = (segment.start_time, segment.end_time)
        idx = bisect.bisect_right(keys, new_key)

        was_reordered = False
        # If segment is not appended at the end, it arrived out of chronological order!
        if self._final_segments and idx < len(self._final_segments):
            was_reordered = True
            self._out_of_order_count += 1

        self._final_segments.insert(idx, segment)
        self._seen_segment_ids.add(segment.segment_id)

        # Clear active interim if this finalized segment covers or exceeds its audio window
        if self._interim_segment is not None:
            if segment.end_time >= self._interim_segment.start_time:
                self._interim_segment = None

        self._record_arrival(None, segment=segment, is_duplicate=False, was_reordered=was_reordered)
        return True

    def _record_arrival(
        self,
        event: Optional[TranscriptEvent],
        segment: Optional[TranscriptSegment] = None,
        is_duplicate: bool = False,
        was_reordered: bool = False,
        is_late_interim: bool = False,
    ) -> None:
        """Record diagnostic history of event arrivals."""
        seg = segment or (event.segment if event else None)
        evt_type = event.event_type.value if event else ("final" if (seg and seg.is_final) else "interim")
        evt_id = event.event_id if event else (seg.segment_id if seg else "none")

        record = {
            "arrival_index": len(self._arrival_history) + 1,
            "event_id": evt_id,
            "event_type": evt_type,
            "text": seg.text if seg else "",
            "audio_start": seg.start_time if seg else 0.0,
            "audio_end": seg.end_time if seg else 0.0,
            "is_duplicate": is_duplicate,
            "was_reordered": was_reordered,
            "is_late_interim": is_late_interim,
        }
        self._arrival_history.append(record)

    def get_final_segments(self) -> List[TranscriptSegment]:
        """Return a defensive copy of finalized segments in strictly chronological order."""
        return list(self._final_segments)

    def get_interim_segment(self) -> Optional[TranscriptSegment]:
        """Return the current tentative in-flight interim segment, if active."""
        return self._interim_segment

    def get_full_transcript(self, include_interim: bool = False) -> str:
        """Reconstruct continuous transcript text strictly from committed final segments.

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
        """Calculate total audio duration in seconds (earliest start to latest end time)."""
        if not self._final_segments:
            return 0.0
        earliest = min(s.start_time for s in self._final_segments)
        latest = max(s.end_time for s in self._final_segments)
        return max(0.0, latest - earliest)

    def get_average_confidence(self) -> float:
        """Calculate mean confidence strictly across all committed final segments."""
        if not self._final_segments:
            return 0.0
        return sum(s.confidence for s in self._final_segments) / len(self._final_segments)

    def get_arrival_history(self) -> List[Dict[str, Any]]:
        """Return full diagnostic log of event arrival order."""
        return list(self._arrival_history)

    def reset(self) -> None:
        """Reset all accumulator state for a fresh session."""
        self._final_segments.clear()
        self._seen_segment_ids.clear()
        self._seen_event_ids.clear()
        self._interim_segment = None
        self._last_error = None
        self._events_processed = 0
        self._interim_updates_count = 0
        self._duplicates_suppressed = 0
        self._out_of_order_count = 0
        self._arrival_history.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Generate structured diagnostic summary of accumulated transcript and telemetry."""
        # Verification audit: Check that final segments are strictly sorted chronologically
        is_chronological = True
        for i in range(len(self._final_segments) - 1):
            if self._final_segments[i].start_time > self._final_segments[i + 1].start_time:
                is_chronological = False
                break

        return {
            "final_segments_count": len(self._final_segments),
            "events_processed": self._events_processed,
            "interim_updates_count": self._interim_updates_count,
            "duplicates_suppressed": self._duplicates_suppressed,
            "out_of_order_reordered": self._out_of_order_count,
            "has_active_interim": self._interim_segment is not None,
            "full_transcript": self.get_full_transcript(include_interim=False),
            "total_duration_seconds": round(self.get_total_duration(), 3),
            "average_confidence": round(self.get_average_confidence(), 4),
            "is_verified": is_chronological and (self._last_error is None),
            "last_error": self._last_error.model_dump() if self._last_error else None,
            "arrival_history": self.get_arrival_history(),
        }

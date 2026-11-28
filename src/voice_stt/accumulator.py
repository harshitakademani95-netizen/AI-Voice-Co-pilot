"""Ordered Segment Accumulator for AI Voice Co-Pilot (W2 & W3 - STT).

This component aggregates streaming transcription events into a chronologically
ordered, deduplicated transcript. It cleanly separates ephemeral interim hypotheses
from committed immutable final segments, gracefully handles out-of-order arrivals,
suppresses duplicate delivery, isolates session state, provides configurable
confidence filtering, and provides consolidated full-text reconstruction.
"""

from __future__ import annotations

import bisect
import math
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
    5. Late Interim & Revision Protection: Late interim or revision events arriving after
       their audio window has already been committed to final segments are discarded without
       corrupting state.
    6. Non-Destructive Error Handling: Ingesting error events records telemetry without
       clearing or corrupting previously committed final segments.
    7. Session Association & Isolation: Ingested events must match the active session.
       Events from disparate sessions are rejected to prevent transcript contamination.
    8. Configurable Confidence Thresholding: Segments with confidence below the threshold
       are quarantined in `_low_confidence_segments` and excluded from `get_full_transcript()`.
    9. Full Observability: Provides detailed event arrival tracking, distinguishing
       arrival order from audio chronology.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        min_confidence_threshold: float = 0.50,
    ) -> None:
        if session_id is not None:
            if not isinstance(session_id, str) or not session_id.strip():
                raise STTValidationError("Session identifier cannot be empty or whitespace.", field_name="session_id")
            self._session_id: Optional[str] = session_id.strip()
            self._initial_session_id: Optional[str] = self._session_id
        else:
            self._session_id = None
            self._initial_session_id = None

        if (
            not isinstance(min_confidence_threshold, (int, float))
            or not math.isfinite(min_confidence_threshold)
            or min_confidence_threshold < 0.0
            or min_confidence_threshold > 1.0
        ):
            raise STTValidationError(
                f"Confidence threshold must be a finite float in range [0.0, 1.0], got {min_confidence_threshold}.",
                field_name="min_confidence_threshold",
            )
        self._min_confidence_threshold: float = float(min_confidence_threshold)

        self._final_segments: List[TranscriptSegment] = []
        self._low_confidence_segments: List[TranscriptSegment] = []
        self._seen_segment_ids: Set[str] = set()
        self._seen_event_ids: Set[str] = set()
        self._interim_segment: Optional[TranscriptSegment] = None
        self._active_interim_sequence: Optional[int] = None
        self._active_interim_timestamp: Optional[float] = None
        self._last_error: Optional[STTErrorDetail] = None

        # Precise Telemetry & Diagnostics
        self._events_processed: int = 0
        self._interim_updates_count: int = 0
        self._revision_count: int = 0
        self._duplicates_suppressed: int = 0
        self._out_of_order_count: int = 0
        self._session_mismatches_count: int = 0
        self._low_confidence_count: int = 0
        self._arrival_history: List[Dict[str, Any]] = []

    @property
    def session_id(self) -> Optional[str]:
        """Active session identifier associated with this accumulator."""
        return self._session_id

    @property
    def session_mismatches_count(self) -> int:
        """Count of events rejected due to session ID mismatch."""
        return self._session_mismatches_count

    @property
    def revision_count(self) -> int:
        """Count of explicit revision events processed."""
        return self._revision_count

    @property
    def low_confidence_count(self) -> int:
        """Count of final segments quarantined due to low confidence."""
        return self._low_confidence_count

    @property
    def min_confidence_threshold(self) -> float:
        """Minimum confidence threshold required to commit final segments to full transcript."""
        return self._min_confidence_threshold

    @min_confidence_threshold.setter
    def min_confidence_threshold(self, value: float) -> None:
        """Dynamically update confidence threshold for future incoming segments."""
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0.0
            or value > 1.0
        ):
            raise STTValidationError(
                f"Confidence threshold must be a finite float in range [0.0, 1.0], got {value}.",
                field_name="min_confidence_threshold",
            )
        self._min_confidence_threshold = float(value)

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
            True if event was processed; False if ignored as duplicate, mismatch, or stale.
        """
        if not isinstance(event, TranscriptEvent):
            raise STTValidationError(f"Expected TranscriptEvent, got {type(event).__name__}")

        # Session association check
        if self._session_id is None:
            self._session_id = event.session_id
        elif event.session_id != self._session_id:
            self._session_mismatches_count += 1
            self._record_arrival(
                event,
                is_duplicate=False,
                was_reordered=False,
                is_session_mismatch=True,
            )
            return False

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

        # Check for older / out-of-order interim or revision event when active interim exists
        if event.event_type in (TranscriptEventType.INTERIM, TranscriptEventType.REVISION):
            if self._interim_segment is not None and self._active_interim_sequence is not None:
                if event.sequence_number < self._active_interim_sequence:
                    self._record_arrival(
                        event,
                        is_duplicate=False,
                        was_reordered=True,
                        is_late_interim=True,
                    )
                    return False

            is_rev = event.event_type == TranscriptEventType.REVISION
            result = self._handle_interim_segment(
                event.segment,
                event_id=event.event_id,
                sequence_number=event.sequence_number,
                is_revision=is_rev,
            )
            if result:
                self._active_interim_sequence = event.sequence_number
                self._active_interim_timestamp = event.timestamp
            return result

        if event.event_type in (TranscriptEventType.FINAL, TranscriptEventType.FINALIZATION):
            return self._commit_final_segment(event.segment, event_id=event.event_id)

        # Process any other segment payload
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
            return self._handle_interim_segment(segment, event_id=event_id, is_revision=False)

    def _handle_interim_segment(
        self,
        segment: TranscriptSegment,
        event_id: Optional[str] = None,
        sequence_number: Optional[int] = None,
        is_revision: bool = False,
    ) -> bool:
        """Process an in-flight interim or revision segment hypothesis."""
        # Check against active interim segment
        if self._interim_segment is not None:
            # 1. Duplicate interim/revision suppression: ignore if identical to current interim hypothesis
            if (
                self._interim_segment.segment_id == segment.segment_id
                and self._interim_segment.text == segment.text
                and abs(self._interim_segment.start_time - segment.start_time) < 1e-4
                and abs(self._interim_segment.end_time - segment.end_time) < 1e-4
            ):
                self._duplicates_suppressed += 1
                self._record_arrival(
                    None,
                    segment=segment,
                    is_duplicate=True,
                    was_reordered=False,
                    is_late_interim=False,
                    event_id=event_id,
                )
                return False

            # 2. Older / regressive interim/revision hypothesis protection:
            is_same_window = abs(self._interim_segment.start_time - segment.start_time) < 1e-4
            is_same_segment = self._interim_segment.segment_id == segment.segment_id
            if (is_same_window or is_same_segment) and (segment.end_time < self._interim_segment.end_time):
                # When sequence information is available, a strictly newer sequence indicates a legitimate
                # revision/contraction rather than an out-of-order stale delivery.
                is_newer_sequence = (
                    sequence_number is not None
                    and self._active_interim_sequence is not None
                    and sequence_number > self._active_interim_sequence
                )
                if not is_newer_sequence:
                    self._record_arrival(
                        None,
                        segment=segment,
                        is_duplicate=False,
                        was_reordered=True,
                        is_late_interim=True,
                        event_id=event_id,
                    )
                    return False

            if segment.end_time <= self._interim_segment.start_time:
                # Arrived from an audio window prior to active interim onset
                self._record_arrival(
                    None,
                    segment=segment,
                    is_duplicate=False,
                    was_reordered=True,
                    is_late_interim=True,
                    event_id=event_id,
                )
                return False

        # Late Interim & Revision Protection against committed final segments:
        all_finalized = self._final_segments + self._low_confidence_segments
        if all_finalized:
            max_finalized_end = max(s.end_time for s in all_finalized)
            if segment.end_time <= max_finalized_end:
                # Stale interim/revision; discard to protect committed state
                self._record_arrival(
                    None,
                    segment=segment,
                    is_duplicate=False,
                    was_reordered=False,
                    is_late_interim=True,
                    event_id=event_id,
                )
                return False

        self._interim_segment = segment
        self._interim_updates_count += 1
        if is_revision:
            self._revision_count += 1
        self._record_arrival(
            None,
            segment=segment,
            is_duplicate=False,
            was_reordered=False,
            is_late_interim=False,
            event_id=event_id,
        )
        return True

    def _commit_final_segment(self, segment: TranscriptSegment, event_id: Optional[str] = None) -> bool:
        """Insert a finalized segment maintaining chronological order, deduplication, and confidence filtering."""
        # Identity-Based Deduplication (by segment_id)
        if segment.segment_id in self._seen_segment_ids:
            self._duplicates_suppressed += 1
            self._record_arrival(None, segment=segment, is_duplicate=True, was_reordered=False, event_id=event_id)
            return False

        # Content + Boundary Deduplication across both committed and quarantined collections
        all_finalized = self._final_segments + self._low_confidence_segments
        for existing in all_finalized:
            if (
                abs(existing.start_time - segment.start_time) < 1e-4
                and abs(existing.end_time - segment.end_time) < 1e-4
                and existing.text.strip() == segment.text.strip()
            ):
                self._duplicates_suppressed += 1
                self._record_arrival(None, segment=segment, is_duplicate=True, was_reordered=False, event_id=event_id)
                return False

        # Clear and reconcile active interim if this finalized segment matches, covers, or overlaps its audio window
        if self._interim_segment is not None:
            is_same_segment = segment.segment_id == self._interim_segment.segment_id
            overlaps = (
                segment.start_time < self._interim_segment.end_time
                and segment.end_time > self._interim_segment.start_time
            )
            is_subsumed = (
                segment.start_time <= self._interim_segment.start_time
                and segment.end_time >= self._interim_segment.end_time
            )
            if is_same_segment or overlaps or is_subsumed:
                self._interim_segment = None
                self._active_interim_sequence = None
                self._active_interim_timestamp = None

        # Check confidence threshold
        if segment.confidence < self._min_confidence_threshold:
            self._low_confidence_segments.append(segment)
            self._low_confidence_count += 1
            self._seen_segment_ids.add(segment.segment_id)
            self._record_arrival(
                None,
                segment=segment,
                is_duplicate=False,
                was_reordered=False,
                is_low_confidence=True,
                event_id=event_id,
            )
            return True

        # Determine insertion point by audio start_time (secondary sort by end_time)
        keys = [(s.start_time, s.end_time) for s in self._final_segments]
        new_key = (segment.start_time, segment.end_time)
        idx = bisect.bisect_right(keys, new_key)

        was_reordered = False
        if self._final_segments and idx < len(self._final_segments):
            was_reordered = True
            self._out_of_order_count += 1

        self._final_segments.insert(idx, segment)
        self._seen_segment_ids.add(segment.segment_id)

        self._record_arrival(
            None,
            segment=segment,
            is_duplicate=False,
            was_reordered=was_reordered,
            is_low_confidence=False,
            event_id=event_id,
        )
        return True

    def _record_arrival(
        self,
        event: Optional[TranscriptEvent],
        segment: Optional[TranscriptSegment] = None,
        is_duplicate: bool = False,
        was_reordered: bool = False,
        is_late_interim: bool = False,
        is_session_mismatch: bool = False,
        is_low_confidence: bool = False,
        event_id: Optional[str] = None,
    ) -> None:
        """Record diagnostic history of event arrivals."""
        seg = segment or (event.segment if event else None)
        evt_type = event.event_type.value if event else ("final" if (seg and seg.is_final) else "interim")
        evt_id = event.event_id if event else (event_id or (seg.segment_id if seg else "none"))

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
            "is_session_mismatch": is_session_mismatch,
            "is_low_confidence": is_low_confidence,
        }
        self._arrival_history.append(record)

    def get_final_segments(self) -> List[TranscriptSegment]:
        """Return a defensive copy of finalized segments in strictly chronological order."""
        return list(self._final_segments)

    def get_low_confidence_segments(self) -> List[TranscriptSegment]:
        """Return a defensive copy of quarantined low-confidence segments."""
        return list(self._low_confidence_segments)

    def get_interim_segment(self) -> Optional[TranscriptSegment]:
        """Return the current tentative in-flight interim segment, if active."""
        return self._interim_segment

    def clear_interim(self) -> None:
        """Clear active in-flight interim hypothesis without altering committed final segments."""
        self._interim_segment = None
        self._active_interim_sequence = None
        self._active_interim_timestamp = None

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

    def reset(self, session_id: Optional[str] = None) -> None:
        """Reset all accumulator state for a fresh session."""
        self._final_segments.clear()
        self._low_confidence_segments.clear()
        self._seen_segment_ids.clear()
        self._seen_event_ids.clear()
        self._interim_segment = None
        self._active_interim_sequence = None
        self._active_interim_timestamp = None
        self._last_error = None
        self._events_processed = 0
        self._interim_updates_count = 0
        self._revision_count = 0
        self._duplicates_suppressed = 0
        self._out_of_order_count = 0
        self._session_mismatches_count = 0
        self._low_confidence_count = 0
        self._arrival_history.clear()
        if session_id is not None:
            if not isinstance(session_id, str) or not session_id.strip():
                raise STTValidationError("Session identifier cannot be empty or whitespace.", field_name="session_id")
            self._session_id = session_id.strip()
        else:
            self._session_id = self._initial_session_id

    def get_summary(self) -> Dict[str, Any]:
        """Generate structured diagnostic summary of accumulated transcript and telemetry."""
        is_chronological = True
        for i in range(len(self._final_segments) - 1):
            if self._final_segments[i].start_time > self._final_segments[i + 1].start_time:
                is_chronological = False
                break

        return {
            "session_id": self._session_id,
            "session_mismatches_count": self._session_mismatches_count,
            "min_confidence_threshold": round(self._min_confidence_threshold, 4),
            "final_segments_count": len(self._final_segments),
            "low_confidence_count": len(self._low_confidence_segments),
            "events_processed": self._events_processed,
            "interim_updates_count": self._interim_updates_count,
            "revision_count": self._revision_count,
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

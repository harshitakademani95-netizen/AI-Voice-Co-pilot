"""Week 3 Day 17: Transcription Cancellation Support Tests.

Covers:
1. Reliable cancellation of in-flight operations:
   - Cancellation stops further chunk processing in streams.
2. Direct process_chunk cancellation guard:
   - Calling process_chunk after cancellation raises OrchestratorCancelledError.
3. Cancellation idempotency:
   - Calling cancel() repeatedly is completely safe and idempotent.
4. Interim hypothesis cleanup:
   - Cancelling clears in-flight interim hypotheses so no misleading final events are emitted.
5. Late results suppression:
   - Ingesting events after cancellation returns False and preserves accumulator state.
6. Resource teardown and adapter notification:
   - Orchestrator cancellation invokes the underlying adapter's cancel() method.
7. Session ID preservation:
   - Active session ID remains intact through cancellation.
8. Independent session isolation:
   - Cancelling one orchestrator session never cancels or impacts another session.
9. Reset clears cancellation:
   - Calling reset() clears the cancellation flag for a clean subsequent session.
10. Telemetry diagnostics:
    - Orchestrator summary reports is_cancelled accurately.
"""

from typing import List, Optional
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig, STTAdapterState, STTAdapterStatus
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import OrchestratorCancelledError, TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    AudioFormat,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


def _make_audio_chunk(seq: int, is_last: bool = False) -> AudioChunk:
    return AudioChunk(
        sequence_id=seq,
        timestamp=float(seq),
        data=b"\x00\x00" * 1600,
        format=AudioFormat(sample_rate=16000),
        metadata={"is_last": is_last},
    )


class MockTrackingAdapter(BaseSTTAdapter):
    """Test STT adapter that tracks transcribe and cancel invocations."""

    def __init__(self, config: Optional[STTAdapterConfig] = None) -> None:
        super().__init__(config or STTAdapterConfig())
        self.cancel_called: bool = False
        self.chunks_received: List[AudioChunk | bytes] = []

    def initialize(self, session_id: Optional[str] = None) -> None:
        super().initialize(session_id=session_id)
        self._state = STTAdapterState.READY

    def transcribe_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        self.chunks_received.append(chunk)
        self._chunks_processed += 1
        seq = self._events_emitted
        self._events_emitted += 1
        return [
            TranscriptEvent(
                event_id=f"track-evt-{seq}",
                event_type=TranscriptEventType.FINAL if is_last else TranscriptEventType.INTERIM,
                sequence_number=seq,
                timestamp=100.0 + seq,
                session_id=self._session_id or "default-session",
                segment=TranscriptSegment(
                    segment_id=f"seg-{seq}",
                    start_time=seq * 1.0,
                    end_time=(seq + 1) * 1.0,
                    text=f"word_{seq}",
                    confidence=0.95,
                    is_final=is_last,
                ),
            )
        ]

    def cancel(self) -> None:
        super().cancel()
        self.cancel_called = True

    def reset(self) -> None:
        super().reset()
        self.cancel_called = False
        self.chunks_received.clear()

    def close(self) -> None:
        super().close()


class TestDay17TranscriptionCancellation:
    """Tests for Day 17 cancellation capabilities."""

    def test_01_cancel_in_flight_stream_stops_further_processing(self) -> None:
        adapter = MockTrackingAdapter()
        orch = TranscriptionOrchestrator(adapter=adapter, session_id="cancel-stream-test")

        chunks = [_make_audio_chunk(i) for i in range(5)]

        emitted_events: List[TranscriptEvent] = []
        for i, event in enumerate(orch.process_stream(chunks)):
            emitted_events.append(event)
            if i == 1:
                orch.cancel()

        assert orch.is_cancelled is True
        assert len(emitted_events) == 2
        # Adapter should not have received all 5 chunks
        assert len(adapter.chunks_received) < 5

    def test_02_cancel_before_processing_raises_or_returns_cleanly(self) -> None:
        orch = TranscriptionOrchestrator(session_id="pre-cancel-test")
        orch.cancel()

        chunk = _make_audio_chunk(0)

        with pytest.raises(OrchestratorCancelledError) as exc_info:
            orch.process_chunk(chunk)

        assert exc_info.value.code == "OPERATION_CANCELLED"
        assert exc_info.value.retryable is False

        # process_stream yields nothing when already cancelled
        events = list(orch.process_stream([chunk]))
        assert len(events) == 0

    def test_03_repeated_cancellation_is_safe_and_idempotent(self) -> None:
        adapter = MockTrackingAdapter()
        orch = TranscriptionOrchestrator(adapter=adapter, session_id="idempotent-test")

        orch.cancel()
        orch.cancel()
        orch.cancel()

        assert orch.is_cancelled is True
        assert adapter.cancel_called is True

    def test_04_cancelling_clears_interim_hypothesis_without_misleading_final(self) -> None:
        orch = TranscriptionOrchestrator(session_id="interim-cleanup-test")
        orch.initialize()

        # Ingest an interim event
        interim_evt = TranscriptEvent(
            event_id="evt-interim-1",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=1,
            timestamp=101.0,
            session_id=orch.session_id,
            segment=TranscriptSegment(
                segment_id="seg-interim-1",
                start_time=0.0,
                end_time=1.5,
                text="hello in-progress speech",
                confidence=0.75,
                is_final=False,
            ),
        )
        orch.ingest_event(interim_evt)

        assert orch.get_interim_segment() is not None
        assert orch.get_full_transcript(include_interim=True) == "hello in-progress speech"

        orch.cancel()

        # Interim hypothesis must be purged
        assert orch.get_interim_segment() is None
        assert orch.get_final_segments() == []
        assert orch.get_full_transcript(include_interim=True) == ""
        assert orch.get_full_transcript(include_interim=False) == ""

    def test_05_prevent_late_results_from_corrupting_accumulator(self) -> None:
        orch = TranscriptionOrchestrator(session_id="late-results-test")
        orch.initialize()

        orch.cancel()

        late_event = TranscriptEvent(
            event_id="evt-late-1",
            event_type=TranscriptEventType.FINAL,
            sequence_number=1,
            timestamp=102.0,
            session_id=orch.session_id,
            segment=TranscriptSegment(
                segment_id="seg-late-1",
                start_time=0.0,
                end_time=2.0,
                text="late arriving result",
                confidence=0.99,
                is_final=True,
            ),
        )

        accepted = orch.ingest_event(late_event)
        assert accepted is False
        assert orch.get_final_segments() == []
        assert orch.get_full_transcript() == ""

    def test_06_cancellation_calls_adapter_cancel_and_cleans_resources(self) -> None:
        adapter = MockTrackingAdapter()
        orch = TranscriptionOrchestrator(adapter=adapter, session_id="resource-cleanup-test")
        orch.initialize()

        assert adapter.cancel_called is False
        orch.cancel()
        assert adapter.cancel_called is True

    def test_07_session_id_preserved_across_cancellation(self) -> None:
        session_id = "test-session-preservation-123"
        orch = TranscriptionOrchestrator(session_id=session_id)
        orch.initialize()

        assert orch.session_id == session_id
        orch.cancel()
        assert orch.session_id == session_id
        assert orch.get_summary()["session_id"] == session_id

    def test_08_cross_session_cancellation_isolation(self) -> None:
        orch1 = TranscriptionOrchestrator(session_id="session-orch-1")
        orch2 = TranscriptionOrchestrator(session_id="session-orch-2")

        orch1.initialize()
        orch2.initialize()

        orch1.cancel()

        assert orch1.is_cancelled is True
        assert orch2.is_cancelled is False

        # orch2 can still process chunks without issue
        chunk = _make_audio_chunk(0, is_last=True)
        events = orch2.process_chunk(chunk, is_last=True)
        assert len(events) > 0
        assert orch2.is_cancelled is False

    def test_09_reset_clears_cancellation_state_for_new_session(self) -> None:
        orch = TranscriptionOrchestrator(session_id="reset-cancel-session")
        orch.initialize()

        orch.cancel()
        assert orch.is_cancelled is True

        orch.reset()
        assert orch.is_cancelled is False

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)
        assert len(events) > 0

    def test_10_cancellation_status_reported_in_summary(self) -> None:
        orch = TranscriptionOrchestrator(session_id="summary-cancel-test")
        orch.initialize()

        summary_before = orch.get_summary()
        assert summary_before["is_cancelled"] is False

        orch.cancel()

        summary_after = orch.get_summary()
        assert summary_after["is_cancelled"] is True

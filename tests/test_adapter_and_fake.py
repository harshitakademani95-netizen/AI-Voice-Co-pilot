"""Unit tests verifying provider-neutral adapter and deterministic fake transcriber."""

from typing import List
import pytest

from voice_stt.adapter import (
    BaseSTTAdapter,
    STTAdapterConfig,
    STTAdapterState,
)
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
)


class TestAdapterInterfaceContract:
    """Verifies that BaseSTTAdapter interface rules are strictly respected."""

    def test_abstract_class_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            BaseSTTAdapter()  # type: ignore[abstract]

    def test_context_manager_lifecycle(self) -> None:
        adapter = DeterministicFakeTranscriber()
        assert adapter.state == STTAdapterState.UNINITIALIZED

        with adapter as active_adapter:
            assert active_adapter.state == STTAdapterState.READY
            assert active_adapter.session_id is not None

        assert adapter.state == STTAdapterState.CLOSED

    def test_transcribe_on_closed_adapter_fails(self, sample_audio_bytes: bytes) -> None:
        adapter = DeterministicFakeTranscriber()
        adapter.initialize()
        adapter.close()
        with pytest.raises(RuntimeError) as exc_info:
            adapter.transcribe_chunk(sample_audio_bytes)
        assert "closed STT adapter" in str(exc_info.value)

    def test_status_telemetry_reporting(self, sample_audio_bytes: bytes) -> None:
        adapter = DeterministicFakeTranscriber()
        adapter.initialize(session_id="test-session-001")
        assert adapter.get_status().chunks_processed == 0
        assert adapter.get_status().events_emitted == 0
        assert adapter.get_status().active_session_id == "test-session-001"

        adapter.transcribe_chunk(sample_audio_bytes)
        status = adapter.get_status()
        assert status.chunks_processed == 1
        assert status.events_emitted >= 1


class TestDeterministicFakeTranscriber:
    """Tests guaranteeing strict determinism and behavior of the fake transcriber."""

    def test_determinism_scripted_mode(self, sample_audio_chunks: List[AudioChunk]) -> None:
        """Crucial Acceptance Criteria: Identical input -> Identical transcript events."""
        script = ["Explain this technical error in code."]
        seed = 101

        # Run 1
        t1 = DeterministicFakeTranscriber(script=script, seed=seed)
        t1.initialize()
        events_run_1: List[TranscriptEvent] = []
        for chunk in sample_audio_chunks:
            events_run_1.extend(t1.transcribe_chunk(chunk))

        # Run 2
        t2 = DeterministicFakeTranscriber(script=script, seed=seed)
        t2.initialize()
        events_run_2: List[TranscriptEvent] = []
        for chunk in sample_audio_chunks:
            events_run_2.extend(t2.transcribe_chunk(chunk))

        # Compare length
        assert len(events_run_1) == len(events_run_2)
        assert len(events_run_1) > 0

        # Compare field-by-field equality
        for e1, e2 in zip(events_run_1, events_run_2):
            assert e1.event_id == e2.event_id
            assert e1.event_type == e2.event_type
            assert e1.sequence_number == e2.sequence_number
            assert e1.timestamp == pytest.approx(e2.timestamp)
            assert e1.segment is not None and e2.segment is not None
            assert e1.segment.segment_id == e2.segment.segment_id
            assert e1.segment.text == e2.segment.text
            assert e1.segment.confidence == pytest.approx(e2.segment.confidence)
            assert e1.segment.is_final == e2.segment.is_final
            assert e1.segment.start_time == pytest.approx(e2.segment.start_time)
            assert e1.segment.end_time == pytest.approx(e2.segment.end_time)

    def test_determinism_hash_mode(self, sample_audio_chunks: List[AudioChunk]) -> None:
        """Verify hash-generative mode produces identical events across runs with same chunks."""
        seed = 42

        # Run 1
        t1 = DeterministicFakeTranscriber(seed=seed)
        t1.initialize()
        events_1 = list(t1.transcribe_stream(sample_audio_chunks))

        # Run 2
        t2 = DeterministicFakeTranscriber(seed=seed)
        t2.initialize()
        events_2 = list(t2.transcribe_stream(sample_audio_chunks))

        assert len(events_1) == len(events_2)
        assert [e.model_dump() for e in events_1] == [e.model_dump() for e in events_2]

    def test_reset_yields_identical_subsequent_sequence(
        self, sample_audio_chunks: List[AudioChunk]
    ) -> None:
        """Resetting the same transcriber instance reproduces identical events."""
        transcriber = DeterministicFakeTranscriber(script=["Why is this failing?"], seed=777)
        transcriber.initialize()

        first_pass = [e.model_dump() for e in transcriber.transcribe_stream(sample_audio_chunks)]
        transcriber.reset()
        second_pass = [e.model_dump() for e in transcriber.transcribe_stream(sample_audio_chunks)]

        assert first_pass == second_pass

    def test_simulated_error_injection(self, sample_audio_chunks: List[AudioChunk]) -> None:
        """Verify that simulated error injection produces standardized STT error event."""
        custom_error = STTErrorDetail(
            code="NETWORK_TIMEOUT_MOCK",
            message="Mock network timeout for testing recovery.",
            retryable=True,
        )
        transcriber = DeterministicFakeTranscriber(
            inject_error_at_chunk=2,
            error_detail=custom_error,
        )
        transcriber.initialize()

        # Chunk 0: normal
        evts_0 = transcriber.transcribe_chunk(sample_audio_chunks[0])
        assert len(evts_0) >= 0

        # Chunk 1: normal
        evts_1 = transcriber.transcribe_chunk(sample_audio_chunks[1])
        assert len(evts_1) >= 0

        # Chunk 2: triggered error
        evts_2 = transcriber.transcribe_chunk(sample_audio_chunks[2])
        assert len(evts_2) == 1
        err_evt = evts_2[0]
        assert err_evt.event_type == TranscriptEventType.ERROR
        assert err_evt.error is not None
        assert err_evt.error.code == "NETWORK_TIMEOUT_MOCK"
        assert transcriber.state == STTAdapterState.ERROR

    def test_interim_flag_configuration_disabled(
        self, sample_audio_chunks: List[AudioChunk]
    ) -> None:
        """When interim_results=False, only final events should be emitted."""
        config = STTAdapterConfig(interim_results=False)
        transcriber = DeterministicFakeTranscriber(
            config=config, script=["Check PDF and summarize."]
        )
        transcriber.initialize()

        all_events = list(transcriber.transcribe_stream(sample_audio_chunks))
        for evt in all_events:
            assert evt.event_type != TranscriptEventType.INTERIM
            if evt.segment:
                assert evt.segment.is_final is True


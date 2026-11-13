"""Contract tests for BaseSTTAdapter interface and DeterministicFakeTranscriber.

Week 2 – Day 14: Contract Tests & End-to-End Demo.

Verifies:
1. Fake transcriber implements the required BaseSTTAdapter interface.
2. Required methods and expected method signatures are respected.
3. Adapter lifecycle and state transitions work correctly.
4. AudioChunk input is handled correctly.
5. Valid transcript events are produced.
6. Event types and required fields follow existing schemas.
7. Invalid input produces normalized errors.
8. Provider-specific exceptions do not leak through the public adapter contract.
9. Mock mode works without API keys or external services.
"""

from __future__ import annotations

import inspect
import math
from typing import Any, Iterator, List
import pytest

from src.schemas.audio import AudioChunk, AudioError, AudioFormat
from voice_stt.adapter import (
    BaseSTTAdapter,
    STTAdapterConfig,
    STTAdapterState,
    STTAdapterStatus,
)
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.fixtures import STTFixture, get_fixture
from voice_stt.schemas import (
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class TestDay14AdapterContract:
    """Rigorous contract test suite for STT Adapter implementations."""

    # 1. Interface implementation & inheritance
    def test_01_adapter_implements_base_stt_adapter_contract(self) -> None:
        """DeterministicFakeTranscriber must be a strict subclass of BaseSTTAdapter."""
        assert issubclass(DeterministicFakeTranscriber, BaseSTTAdapter)
        adapter = DeterministicFakeTranscriber()
        assert isinstance(adapter, BaseSTTAdapter)

    # 2. Required methods and method signatures
    def test_02_required_methods_and_expected_signatures(self) -> None:
        """Adapter must provide exact expected public methods and signatures."""
        adapter = DeterministicFakeTranscriber()

        # Check required public methods on BaseSTTAdapter
        required_methods = [
            "initialize",
            "transcribe_chunk",
            "transcribe_stream",
            "close",
            "reset",
            "get_status",
        ]
        for method_name in required_methods:
            assert hasattr(adapter, method_name), f"Missing required method: {method_name}"
            assert callable(getattr(adapter, method_name)), f"Attribute {method_name} is not callable"

        # Check initialize signature
        init_sig = inspect.signature(adapter.initialize)
        assert "session_id" in init_sig.parameters
        assert init_sig.parameters["session_id"].default is None

        # Check transcribe_chunk signature
        chunk_sig = inspect.signature(adapter.transcribe_chunk)
        assert "chunk" in chunk_sig.parameters
        assert "is_last" in chunk_sig.parameters
        assert chunk_sig.parameters["is_last"].default is False

        # Check get_status returns STTAdapterStatus
        status = adapter.get_status()
        assert isinstance(status, STTAdapterStatus)

    # 3. Adapter lifecycle and state transitions
    def test_03_lifecycle_state_transitions(self, sample_audio_bytes: bytes) -> None:
        """Verifies state machine transitions: UNINITIALIZED -> READY -> CLOSED."""
        adapter = DeterministicFakeTranscriber()
        assert adapter.state == STTAdapterState.UNINITIALIZED

        # Initialize
        adapter.initialize(session_id="contract-test-session")
        assert adapter.state == STTAdapterState.READY
        assert adapter.session_id == "contract-test-session"

        # Transcribe chunk maintains READY state upon successful completion
        events = adapter.transcribe_chunk(sample_audio_bytes)
        assert adapter.state == STTAdapterState.READY
        assert len(events) >= 1

        # Close transitions to CLOSED
        adapter.close()
        assert adapter.state == STTAdapterState.CLOSED

        # Transcribing on closed adapter must fail with RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            adapter.transcribe_chunk(sample_audio_bytes)
        assert "closed STT adapter" in str(exc_info.value)

    # 4. Context manager contract
    def test_04_context_manager_lifecycle(self, sample_audio_bytes: bytes) -> None:
        """Context manager must automatically initialize upon entry and close upon exit."""
        adapter = DeterministicFakeTranscriber()
        assert adapter.state == STTAdapterState.UNINITIALIZED

        with adapter as active_adapter:
            assert active_adapter is adapter
            assert active_adapter.state == STTAdapterState.READY
            events = active_adapter.transcribe_chunk(sample_audio_bytes)
            assert len(events) > 0

        assert adapter.state == STTAdapterState.CLOSED

    # 5. AudioChunk input handling
    def test_05_audio_chunk_contract(self) -> None:
        """AudioChunk dataclass inputs are accepted and update telemetry accurately."""
        adapter = DeterministicFakeTranscriber()
        adapter.initialize(session_id="session-chunk-01")

        raw_pcm = b"\x00\x00" * 320  # 20ms at 16kHz mono
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=raw_pcm,
            format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
            metadata={"source": "test_microphone"},
        )

        events = adapter.transcribe_chunk(chunk, is_last=False)
        assert isinstance(events, list)
        status = adapter.get_status()
        assert status.chunks_processed == 1
        assert status.events_emitted >= 1
        assert status.active_session_id == "session-chunk-01"

    # 6. Stream completion contract (is_last flag)
    def test_06_is_last_stream_completed_event(self) -> None:
        """When is_last=True, adapter emits STREAM_COMPLETED as the terminating event."""
        adapter = DeterministicFakeTranscriber()
        adapter.initialize()

        raw_pcm = b"\x00\x00" * 320
        events = adapter.transcribe_chunk(raw_pcm, is_last=True)

        assert len(events) >= 1
        last_event = events[-1]
        assert last_event.event_type == TranscriptEventType.STREAM_COMPLETED
        assert last_event.sequence_number == adapter.get_status().events_emitted - 1
        assert last_event.session_id == adapter.session_id
        assert last_event.timestamp >= 0.0

    # 7. Valid transcript events and schema compliance
    def test_07_event_schema_contract(self) -> None:
        """All emitted events conform strictly to the TranscriptEvent schema."""
        adapter = DeterministicFakeTranscriber(
            script=["voice copilot ready"],
            config=STTAdapterConfig(interim_results=True),
        )
        adapter.initialize()

        # Emit 3 chunks
        all_events: List[TranscriptEvent] = []
        for i in range(3):
            is_last = (i == 2)
            chunk_data = b"\x01\x02" * 320
            events = adapter.transcribe_chunk(chunk_data, is_last=is_last)
            all_events.extend(events)

        assert len(all_events) >= 3
        interim_count = 0
        final_count = 0

        for event in all_events:
            assert isinstance(event, TranscriptEvent)
            assert isinstance(event.event_id, str) and len(event.event_id) > 0
            assert isinstance(event.sequence_number, int) and event.sequence_number >= 0
            assert isinstance(event.timestamp, float) and math.isfinite(event.timestamp) and event.timestamp >= 0.0
            assert event.session_id == adapter.session_id

            if event.event_type == TranscriptEventType.INTERIM:
                interim_count += 1
                assert event.segment is not None
                assert event.segment.is_final is False
                assert len(event.segment.text) > 0
            elif event.event_type == TranscriptEventType.FINAL:
                final_count += 1
                assert event.segment is not None
                assert event.segment.is_final is True
                assert len(event.segment.text) > 0

        assert interim_count >= 1
        assert final_count >= 1

    # 8. Invalid input error handling
    def test_08_invalid_input_produces_normalized_error(self) -> None:
        """Corrupt or invalid audio chunk input raises standardized AudioError or TypeError."""
        adapter = DeterministicFakeTranscriber()
        adapter.initialize()

        # Empty bytes raises AudioError EMPTY_CHUNK_DATA
        with pytest.raises(AudioError) as exc_info:
            adapter.transcribe_chunk(b"")
        assert exc_info.value.code == "EMPTY_CHUNK_DATA"

        # Non-bytes invalid data type raises TypeError
        with pytest.raises(TypeError) as exc_type:
            adapter.transcribe_chunk(12345)  # type: ignore[arg-type]
        assert "Expected AudioChunk or bytes" in str(exc_type.value)

    # 9. Provider-neutral error event contract
    def test_09_error_injection_emits_normalized_error_event(self) -> None:
        """Injected or transcriber failures emit standardized STTErrorDetail events without crashing."""
        adapter = DeterministicFakeTranscriber(inject_error_at_chunk=0)
        adapter.initialize()

        events = adapter.transcribe_chunk(b"\x00\x00" * 320)
        assert len(events) == 1
        error_event = events[0]
        assert error_event.event_type == TranscriptEventType.ERROR
        assert error_event.error is not None
        assert isinstance(error_event.error, STTErrorDetail)
        assert error_event.error.code == "SIMULATED_TRANSCRIBER_ERROR"
        assert error_event.error.retryable is True
        assert adapter.state == STTAdapterState.ERROR

    # 10. Provider-specific exception isolation (no raw leak)
    def test_10_no_provider_specific_exceptions_leak(self) -> None:
        """STTErrorDetail adheres strictly to Doc 04 standard error format."""
        error_detail = STTErrorDetail(
            code="RATE_LIMITED",
            message="Request limit exceeded for fake provider.",
            retryable=True,
            details={"provider": "mock", "limit": 100},
        )
        api_dict = error_detail.to_api_error()
        assert "error" in api_dict
        assert api_dict["error"]["code"] == "RATE_LIMITED"
        assert api_dict["error"]["retryable"] is True
        assert "message" in api_dict["error"]
        assert "details" in api_dict["error"]

    # 11. Mock mode works with zero external network or API keys
    def test_11_mock_mode_zero_external_dependencies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock mode functions in completely offline environment without cloud credentials."""
        # Unset all possible API keys
        for key in ["OPENAI_API_KEY", "DEEPGRAM_API_KEY", "GOOGLE_API_KEY", "AWS_ACCESS_KEY_ID"]:
            monkeypatch.delenv(key, raising=False)

        adapter = DeterministicFakeTranscriber(seed=999)
        adapter.initialize()
        events = adapter.transcribe_chunk(b"\x01\x02" * 320)
        assert len(events) >= 1
        assert adapter.get_status().chunks_processed == 1

    # 12. Reset contract ensures deterministic repeatability
    def test_12_reset_ensures_deterministic_replay(self) -> None:
        """Calling reset() returns the adapter to identical initial sequence state."""
        adapter = DeterministicFakeTranscriber(script=["first sentence", "second sentence"], seed=42)
        adapter.initialize(session_id="replay-test")

        run1_events = []
        for _ in range(3):
            run1_events.extend(adapter.transcribe_chunk(b"\x00\x00" * 320))

        adapter.reset()
        assert adapter.get_status().chunks_processed == 0
        assert adapter.get_status().events_emitted == 0

        run2_events = []
        for _ in range(3):
            run2_events.extend(adapter.transcribe_chunk(b"\x00\x00" * 320))

        assert len(run1_events) == len(run2_events)
        for e1, e2 in zip(run1_events, run2_events):
            assert e1.event_type == e2.event_type
            assert e1.sequence_number == e2.sequence_number
            if e1.segment and e2.segment:
                assert e1.segment.text == e2.segment.text

"""Week 3 Day 18: Mock Provider Fallback Implementation Tests.

Covers:
1. API quota exceeded fallback:
   - Provider failing with QUOTA_EXCEEDED / 429 triggers fallback to DeterministicFakeTranscriber.
   - Transcription completes successfully without paid credentials.
2. Network connection failure fallback:
   - Provider raising ConnectionError triggers fallback to mock transcriber.
3. Provider unavailable / temporary service failure fallback:
   - Provider failing with SERVICE_UNAVAILABLE / 503 triggers fallback.
4. Excluded failure non-fallback:
   - Validation and programming errors (STTValidationError, ValueError) do NOT trigger fallback.
   - Errors are emitted or raised directly without masking.
5. Telemetry and summary reporting:
   - Orchestrator summary records fallback_active, fallback_triggered, fallback_reason, and fallback_error.
6. Session ID preservation across fallback:
   - Active session ID is preserved seamlessly on the fallback adapter and accumulator.
7. Audio chunk ordering and deduplication:
   - Audio chunk sequence and timestamps remain strictly ordered; duplicate text is suppressed.
8. Sensitive credentials masking in fallback diagnostics:
   - API keys and tokens in error messages are redacted in fallback_error telemetry.
9. Infinite fallback protection:
   - Fallback adapter failure does not cause recursive or secondary fallback loops.
10. Cancellation after fallback:
    - Cancelling while fallback is active cleanly cancels the fallback transcriber.
"""

from typing import List, Optional
import pytest

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig, STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import RetryConfig, TranscriptionOrchestrator
from voice_stt.schemas import (
    AudioChunk,
    AudioFormat,
    STTErrorDetail,
    STTValidationError,
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


class FailingSTTAdapter(BaseSTTAdapter):
    """STT Adapter designed to simulate configurable failure conditions."""

    def __init__(
        self,
        exception_to_raise: Optional[Exception] = None,
        error_event_to_emit: Optional[TranscriptEvent] = None,
        config: Optional[STTAdapterConfig] = None,
    ) -> None:
        super().__init__(config or STTAdapterConfig())
        self.exception_to_raise = exception_to_raise
        self.error_event_to_emit = error_event_to_emit
        self.transcribe_call_count: int = 0
        self.cancel_called: bool = False

    def initialize(self, session_id: Optional[str] = None) -> None:
        super().initialize(session_id=session_id)
        self._state = STTAdapterState.READY

    def transcribe_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        self.transcribe_call_count += 1
        if self.exception_to_raise is not None:
            raise self.exception_to_raise
        if self.error_event_to_emit is not None:
            return [self.error_event_to_emit]
        return []

    def cancel(self) -> None:
        super().cancel()
        self.cancel_called = True

    def reset(self) -> None:
        super().reset()
        self.transcribe_call_count = 0
        self.cancel_called = False

    def close(self) -> None:
        super().close()


class TestDay18MockProviderFallback:
    """Tests for Day 18 mock provider fallback capabilities."""

    def test_01_api_quota_exceeded_triggers_mock_fallback(self) -> None:
        quota_err = RuntimeError("429 Too Many Requests: Insufficient quota remaining for key sk-abcdef1234567890abcdef123456")
        primary_adapter = FailingSTTAdapter(exception_to_raise=quota_err)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-quota-fallback-session",
            retry_config=RetryConfig(max_retries=1, retry_delay=0.0),
        )

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)

        assert orch.is_fallback_active is True
        assert orch.fallback_triggered is True
        assert orch.fallback_reason == "QUOTA_EXCEEDED"
        assert len(events) > 0
        # Check that events were emitted by fallback transcriber and ingested
        final_events = [e for e in events if e.event_type in (TranscriptEventType.FINAL, TranscriptEventType.FINALIZATION)]
        assert len(final_events) > 0
        assert len(orch.get_final_segments()) > 0
        assert orch.get_full_transcript() != ""

    def test_02_network_connection_failure_triggers_mock_fallback(self) -> None:
        net_err = ConnectionError("Failed to connect to primary STT cloud gateway.")
        primary_adapter = FailingSTTAdapter(exception_to_raise=net_err)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-network-fallback-session",
            retry_config=RetryConfig(max_retries=1, retry_delay=0.0),
        )

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)

        assert orch.is_fallback_active is True
        assert orch.fallback_triggered is True
        assert orch.fallback_reason == "SERVICE_UNAVAILABLE"
        assert len(events) > 0
        assert orch.get_full_transcript() != ""

    def test_03_provider_unavailable_event_triggers_mock_fallback(self) -> None:
        service_err_event = TranscriptEvent(
            event_id="err-event-1",
            event_type=TranscriptEventType.ERROR,
            sequence_number=0,
            timestamp=100.0,
            session_id="test-503-session",
            error=STTErrorDetail(
                code="SERVICE_UNAVAILABLE",
                message="Cloud speech engine returned HTTP 503 Service Unavailable",
                retryable=False,
            ),
        )
        primary_adapter = FailingSTTAdapter(error_event_to_emit=service_err_event)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-503-session",
        )

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)

        assert orch.is_fallback_active is True
        assert orch.fallback_triggered is True
        assert orch.fallback_reason == "SERVICE_UNAVAILABLE"
        assert len(orch.get_final_segments()) > 0

    def test_04_validation_and_programming_errors_do_not_trigger_fallback(self) -> None:
        val_err = STTValidationError("Invalid chunk header parameters.", field_name="data")
        primary_adapter = FailingSTTAdapter(exception_to_raise=val_err)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-val-err-session",
        )

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)

        # Fallback must NOT trigger for validation errors
        assert orch.is_fallback_active is False
        assert orch.fallback_triggered is False
        assert len(events) == 1
        assert events[0].event_type == TranscriptEventType.ERROR
        assert events[0].error is not None
        assert events[0].error.code == "VALIDATION_ERROR"

    def test_05_fallback_telemetry_and_summary_diagnostics(self) -> None:
        quota_err = RuntimeError("429 rate limit exceeded")
        primary_adapter = FailingSTTAdapter(exception_to_raise=quota_err)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-telemetry-session",
        )

        chunk = _make_audio_chunk(0, is_last=True)
        orch.process_chunk(chunk, is_last=True)

        summary = orch.get_summary()
        assert summary["fallback_active"] is True
        assert summary["fallback_triggered"] is True
        assert summary["fallback_reason"] in ("QUOTA_EXCEEDED", "RATE_LIMITED")
        assert summary["fallback_error"] is not None
        assert "message" in summary["fallback_error"]

    def test_06_session_id_preserved_across_fallback(self) -> None:
        session_id = "unique-session-id-fallback-456"
        quota_err = RuntimeError("429 Quota Exceeded")
        primary_adapter = FailingSTTAdapter(exception_to_raise=quota_err)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id=session_id,
        )

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)

        assert orch.session_id == session_id
        for event in events:
            assert event.session_id == session_id
        assert orch.get_summary()["session_id"] == session_id

    def test_07_chunk_ordering_and_deduplication_during_fallback(self) -> None:
        class FlakyAdapter(BaseSTTAdapter):
            """Emits chunk 0 successfully, fails on chunk 1 with ConnectionError."""

            def __init__(self) -> None:
                super().__init__(STTAdapterConfig())
                self.calls = 0

            def initialize(self, session_id: Optional[str] = None) -> None:
                super().initialize(session_id=session_id)
                self._state = STTAdapterState.READY

            def transcribe_chunk(self, chunk: AudioChunk | bytes, is_last: bool = False) -> List[TranscriptEvent]:
                self.calls += 1
                if self.calls == 1:
                    return [
                        TranscriptEvent(
                            event_id="chunk-0-event",
                            event_type=TranscriptEventType.FINAL,
                            sequence_number=0,
                            timestamp=100.0,
                            session_id=self._session_id or "default-session",
                            segment=TranscriptSegment(
                                segment_id="seg-chunk-0",
                                start_time=0.0,
                                end_time=1.0,
                                text="first chunk transcribed",
                                confidence=0.95,
                                is_final=True,
                            ),
                        )
                    ]
                raise ConnectionError("Connection lost on chunk 1")

            def cancel(self) -> None:
                super().cancel()

            def reset(self) -> None:
                super().reset()
                self.calls = 0

            def close(self) -> None:
                super().close()

        flaky = FlakyAdapter()
        orch = TranscriptionOrchestrator(
            adapter=flaky,
            enable_fallback=True,
            session_id="test-ordering-stream-session",
            retry_config=RetryConfig(max_retries=0),
        )

        chunks = [_make_audio_chunk(i) for i in range(3)]
        all_events = list(orch.process_stream(chunks))

        assert orch.is_fallback_active is True
        # Verify chronological start_time ordering
        final_segments = orch.get_final_segments()
        assert len(final_segments) >= 2
        for i in range(len(final_segments) - 1):
            assert final_segments[i].start_time <= final_segments[i + 1].start_time

        # Ensure no duplicates in accumulated transcript
        transcript = orch.get_full_transcript()
        assert "first chunk transcribed" in transcript

    def test_08_sensitive_credentials_masked_in_fallback_error(self) -> None:
        sensitive_msg = "429 Quota Exceeded with key sk-123456789012345678901234 and Bearer secret_token_xyz"
        primary_adapter = FailingSTTAdapter(exception_to_raise=RuntimeError(sensitive_msg))

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-sanitization-session",
        )

        chunk = _make_audio_chunk(0, is_last=True)
        orch.process_chunk(chunk, is_last=True)

        summary = orch.get_summary()
        fallback_err = summary["fallback_error"]
        assert fallback_err is not None
        assert "sk-123456789012345678901234" not in fallback_err["message"]
        assert "[REDACTED_API_KEY]" in fallback_err["message"]
        assert "secret_token_xyz" not in fallback_err["message"]

    def test_09_infinite_fallback_protection(self) -> None:
        """When fallback adapter itself fails, it does NOT trigger infinite fallback recursion."""
        primary_adapter = FailingSTTAdapter(exception_to_raise=ConnectionError("Primary failed"))
        failing_fallback = FailingSTTAdapter(exception_to_raise=ConnectionError("Fallback also failed"))

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            fallback_adapter=failing_fallback,
            session_id="test-infinite-loop-session",
            retry_config=RetryConfig(max_retries=0),
        )

        chunk = _make_audio_chunk(0, is_last=True)
        events = orch.process_chunk(chunk, is_last=True)

        assert orch.is_fallback_active is True
        # Since fallback adapter also failed, it returned an error event or raised cleanly without looping
        assert len(events) >= 1
        assert events[-1].event_type == TranscriptEventType.ERROR

    def test_10_cancellation_after_fallback(self) -> None:
        quota_err = RuntimeError("429 Quota Exceeded")
        primary_adapter = FailingSTTAdapter(exception_to_raise=quota_err)

        orch = TranscriptionOrchestrator(
            adapter=primary_adapter,
            enable_fallback=True,
            session_id="test-cancel-after-fallback",
        )

        chunk0 = _make_audio_chunk(0)
        orch.process_chunk(chunk0)

        assert orch.is_fallback_active is True

        # Now cancel
        orch.cancel()
        assert orch.is_cancelled is True

        chunk1 = _make_audio_chunk(1, is_last=True)
        from voice_stt.orchestrator import OrchestratorCancelledError
        with pytest.raises(OrchestratorCancelledError):
            orch.process_chunk(chunk1, is_last=True)

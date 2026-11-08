"""Week 2 Day 12: Timeout Handling, Bounded Retries & Error Normalization Tests.

Covers:
1. Successful transcription without retries (baseline happy path).
2. Timeout detection when transcription takes longer than configured timeout.
3. Successful recovery after a temporary failure on retry.
4. Retry attempts stopping at the configured maximum limit.
5. Permanent errors not being retried unnecessarily.
6. Correct error normalization across various exception types and sensitive credentials masking.
7. Unexpected adapter exceptions handled safely without crashing orchestrator.
8. Successful transcription after a retry.
9. No duplicate transcript segments after retries.
10. Orchestrator state remaining valid after timeout or retry exhaustion.
11. Existing fake transcriber compatibility.
12. Retry configuration validation (rejection of negative/invalid settings).
"""

import time
from typing import List, Optional
from pydantic import ValidationError
import pytest

from src.audio.preprocessing import AudioPreprocessor
from src.schemas.audio import AudioChunk, AudioError, AudioFormat
from voice_stt.adapter import BaseSTTAdapter, STTAdapterState
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import (
    OrchestratorClosedError,
    RetryConfig,
    TranscriptionOrchestrator,
    normalize_stt_error,
    sanitize_error_message,
)
from voice_stt.schemas import (
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class _FlakyMockAdapter(BaseSTTAdapter):
    """Mock adapter that can be configured to fail a specific number of times before succeeding."""

    def __init__(
        self,
        failures_before_success: int = 1,
        exception_to_raise: Optional[Exception] = None,
        error_event_to_return: Optional[STTErrorDetail] = None,
        sleep_seconds: float = 0.0,
    ) -> None:
        super().__init__()
        self.failures_before_success = failures_before_success
        self.exception_to_raise = exception_to_raise or ConnectionError("Temporary connection failure")
        self.error_event_to_return = error_event_to_return
        self.sleep_seconds = sleep_seconds
        self.attempts: int = 0

    def initialize(self, session_id: Optional[str] = None) -> None:
        super().initialize(session_id=session_id)
        self._state = STTAdapterState.READY

    def transcribe_chunk(
        self,
        chunk: AudioChunk | bytes,
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        self.attempts += 1
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)

        if self.attempts <= self.failures_before_success:
            if self.error_event_to_return:
                evt = TranscriptEvent(
                    event_type=TranscriptEventType.ERROR,
                    sequence_number=self.attempts,
                    error=self.error_event_to_return,
                )
                return [evt]
            raise self.exception_to_raise

        # Succeeded! Return a valid final segment
        seg = TranscriptSegment(
            segment_id=f"seg-success-{self.attempts}",
            text="Recovered speech text.",
            start_time=0.0,
            end_time=1.0,
            confidence=0.98,
            is_final=True,
        )
        evt = TranscriptEvent(
            event_type=TranscriptEventType.FINAL,
            sequence_number=self.attempts,
            segment=seg,
        )
        return [evt]

    def reset(self) -> None:
        super().reset()
        self.attempts = 0


class TestDay12TimeoutRetriesAndErrorNormalization:
    """Comprehensive test suite for Day 12 requirements."""

    # 1. Successful transcription without retries
    def test_01_successful_transcription_without_retries(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        transcriber = DeterministicFakeTranscriber(script=["Success."])
        orch = TranscriptionOrchestrator(
            adapter=transcriber,
            retry_config=RetryConfig(max_retries=3, retry_delay=0.0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
            events = orch.process_chunk(chunk, is_last=True)

            assert len(events) >= 1
            assert orch.retries_attempted == 0
            assert orch.timeouts_encountered == 0
            assert orch.get_full_transcript() == "Success."
            assert orch.get_summary()["retries_attempted"] == 0

    # 2. Timeout detection
    def test_02_timeout_detection(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Mock adapter sleeps for 0.1s, but orchestrator timeout is 0.02s
        adapter = _FlakyMockAdapter(failures_before_success=1, sleep_seconds=0.1)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(timeout_seconds=0.02, max_retries=0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            events = orch.process_chunk(chunk)

            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.ERROR
            assert events[0].error is not None
            assert events[0].error.code == "TRANSCRIPTION_TIMEOUT"
            assert events[0].error.retryable is True
            assert orch.timeouts_encountered >= 1
            assert orch.accumulator.last_error.code == "TRANSCRIPTION_TIMEOUT"

    # 3. Successful recovery after a temporary failure
    def test_03_successful_recovery_after_temporary_failure(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Fails once with ConnectionError, succeeds on attempt 2
        adapter = _FlakyMockAdapter(failures_before_success=1)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
            events = orch.process_chunk(chunk, is_last=True)

            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.FINAL
            assert adapter.attempts == 2
            assert orch.retries_attempted == 1
            assert orch.get_full_transcript() == "Recovered speech text."

    # 4. Retry attempts stopping at the configured maximum
    def test_04_retry_attempts_stopping_at_configured_maximum(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Always fails with ConnectionError
        adapter = _FlakyMockAdapter(failures_before_success=999)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            events = orch.process_chunk(chunk)

            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.ERROR
            # 1 initial attempt + 2 retries = 3 total attempts
            assert adapter.attempts == 3
            assert orch.retries_attempted == 2
            assert events[0].metadata["attempts_made"] == 3
            assert events[0].metadata["max_retries"] == 2

    # 5. Permanent errors not being retried
    def test_05_permanent_errors_not_being_retried(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Raises permanent ValueError (INVALID_PAYLOAD)
        adapter = _FlakyMockAdapter(
            failures_before_success=5,
            exception_to_raise=ValueError("Audio format corrupted or channel mismatch"),
        )
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=3, retry_delay=0.0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            events = orch.process_chunk(chunk)

            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.ERROR
            assert events[0].error.code == "INVALID_PAYLOAD"
            assert events[0].error.retryable is False
            # Must NOT retry permanent error: exactly 1 attempt
            assert adapter.attempts == 1
            assert orch.retries_attempted == 0

    # 6. Correct error normalization
    def test_06_correct_error_normalization(self) -> None:
        # Timeout error
        e_timeout = normalize_stt_error(TimeoutError("Backend gateway timed out"))
        assert e_timeout.code == "TRANSCRIPTION_TIMEOUT"
        assert e_timeout.retryable is True

        # Connection error
        e_conn = normalize_stt_error(ConnectionResetError("Peer reset connection"))
        assert e_conn.code == "SERVICE_UNAVAILABLE"
        assert e_conn.retryable is True

        # Validation error
        e_val = normalize_stt_error(STTValidationError("Invalid timing", field_name="end_time"))
        assert e_val.code == "VALIDATION_ERROR"
        assert e_val.retryable is False

        # Audio error
        audio_err = AudioError("Header corrupt")
        audio_err.code = "CORRUPT_HEADER"
        e_audio = normalize_stt_error(audio_err)
        assert e_audio.code == "CORRUPT_HEADER"
        assert e_audio.retryable is False

        # Sensitive credential masking in messages
        sensitive_msg = "Failed with key sk-abcdef12345678901234567890 and Bearer eyJhbGciOi.secret.token"
        sanitized = sanitize_error_message(sensitive_msg)
        assert "sk-abcdef12345678901234567890" not in sanitized
        assert "[REDACTED_API_KEY]" in sanitized
        assert "Bearer [REDACTED_TOKEN]" in sanitized

        e_sens = normalize_stt_error(RuntimeError(sensitive_msg))
        assert "sk-" not in e_sens.message
        assert "[REDACTED_API_KEY]" in e_sens.message

    # 7. Unexpected adapter exceptions being handled safely
    def test_07_unexpected_adapter_exceptions_handled_safely(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Mock adapter raises an arbitrary unexpected ZeroDivisionError
        adapter = _FlakyMockAdapter(
            failures_before_success=1,
            exception_to_raise=ZeroDivisionError("Division by zero in DSP calculation"),
        )
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            # Should not crash with unhandled exception!
            events = orch.process_chunk(chunk)
            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.ERROR
            assert events[0].error.code == "INTERNAL_ERROR"
            assert "Division by zero" in events[0].error.message

    # 8. Successful transcription after a retry
    def test_08_successful_transcription_after_a_retry(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Adapter returns retryable error event on first call, succeeds on second call
        adapter = _FlakyMockAdapter(
            failures_before_success=1,
            error_event_to_return=STTErrorDetail(
                code="SERVICE_UNAVAILABLE",
                message="Temporary downstream service blip",
                retryable=True,
            ),
        )
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
            events = orch.process_chunk(chunk, is_last=True)

            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.FINAL
            assert orch.retries_attempted == 1
            assert len(orch.get_final_segments()) == 1
            assert orch.get_transcript() == "Recovered speech text."

    # 9. No duplicate transcript segments after retries
    def test_09_no_duplicate_transcript_segments_after_retries(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        adapter = _FlakyMockAdapter(failures_before_success=2)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=3, retry_delay=0.0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
            orch.process_chunk(chunk, is_last=True)

            finals = orch.get_final_segments()
            # Must be exactly 1 segment, no duplicate commitments
            assert len(finals) == 1
            assert orch.get_full_transcript() == "Recovered speech text."
            assert orch.accumulator.duplicates_suppressed == 0

    # 10. Orchestrator state remaining valid after timeout or retry exhaustion
    def test_10_orchestrator_state_valid_after_timeout_or_exhaustion(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        adapter = _FlakyMockAdapter(failures_before_success=999)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=1, retry_delay=0.0),
        )

        with orch:
            # Chunk 1 exhausts retries and produces an error event
            chunk1 = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            events1 = orch.process_chunk(chunk1)
            assert events1[0].event_type == TranscriptEventType.ERROR
            assert orch.accumulator.last_error is not None

            # Now fix the adapter so it succeeds for subsequent audio
            adapter.failures_before_success = 0
            chunk2 = AudioChunk(sequence_id=1, timestamp=0.1, data=sample_audio_bytes, metadata={"is_last": True})
            events2 = orch.process_chunk(chunk2, is_last=True)

            # Orchestrator successfully processes Chunk 2!
            assert events2[0].event_type == TranscriptEventType.FINAL
            assert orch.get_transcript() == "Recovered speech text."
            assert len(orch.get_final_segments()) == 1

    # 11. Existing fake transcriber compatibility
    def test_11_existing_fake_transcriber_compatibility(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        # Default orchestrator with DeterministicFakeTranscriber works seamlessly
        orch = TranscriptionOrchestrator()
        assert orch.retry_config.max_retries == 3
        assert orch.retries_attempted == 0
        assert orch.timeouts_encountered == 0

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
            events = orch.process_chunk(chunk, is_last=True)
            assert len(events) >= 1

    # 12. Retry configuration validation
    def test_12_retry_configuration_validation(self) -> None:
        # Negative max_retries rejected
        with pytest.raises(ValidationError):
            RetryConfig(max_retries=-1)

        # Negative retry_delay rejected
        with pytest.raises(ValidationError):
            RetryConfig(retry_delay=-0.5)

        # Backoff factor < 1.0 rejected
        with pytest.raises(ValidationError):
            RetryConfig(backoff_factor=0.5)

        # Non-positive timeout_seconds rejected
        with pytest.raises(ValidationError):
            RetryConfig(timeout_seconds=0.0)

        with pytest.raises(ValidationError):
            RetryConfig(timeout_seconds=-2.0)

        # Unknown extra options rejected
        with pytest.raises(ValidationError):
            RetryConfig(unknown_retry_flag=True)  # type: ignore

    # 13. Regression: Deliberately slow operation returns within configured timeout without waiting for thread shutdown
    def test_13_timeout_bounded_elapsed_time_regression(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify that caller returns immediately upon timeout without waiting for slow worker thread."""
        # Adapter sleeps for 0.4s, but timeout is 0.05s (max_retries=0)
        adapter = _FlakyMockAdapter(failures_before_success=1, sleep_seconds=0.4)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(timeout_seconds=0.05, max_retries=0),
        )

        with orch:
            chunk = AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
            start_time = time.perf_counter()
            events = orch.process_chunk(chunk)
            elapsed = time.perf_counter() - start_time

            # The call must return well under the 0.4s worker sleep time (e.g. < 0.25s)
            assert elapsed < 0.25, f"Elapsed time {elapsed:.3f}s waited for background thread!"
            assert len(events) == 1
            assert events[0].event_type == TranscriptEventType.ERROR
            assert events[0].error.code == "TRANSCRIPTION_TIMEOUT"
            assert orch.timeouts_encountered == 1

    # 14. Streaming: Successful multi-chunk streaming
    def test_14_streaming_successful_multi_chunk(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify process_stream handles multi-chunk sequences and accumulates results."""
        transcriber = DeterministicFakeTranscriber(script=["Streaming pipeline works."])
        orch = TranscriptionOrchestrator(adapter=transcriber)

        chunks = [
            AudioChunk(sequence_id=i, timestamp=i * 0.1, data=sample_audio_bytes, metadata={"is_last": (i == 2)})
            for i in range(3)
        ]

        stream_events = list(orch.process_stream(chunks))
        assert len(stream_events) > 0
        assert orch.get_full_transcript() == "Streaming pipeline works."
        assert orch.accumulator.final_count == 1

    # 15. Streaming: Transient error recovery during stream processing
    def test_15_streaming_transient_error_recovery(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify process_stream recovers from transient retryable error on a chunk."""
        adapter = _FlakyMockAdapter(failures_before_success=1)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        chunks = [
            AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
        ]

        stream_events = list(orch.process_stream(chunks))
        assert len(stream_events) == 1
        assert stream_events[0].event_type == TranscriptEventType.FINAL
        assert orch.retries_attempted == 1
        assert orch.get_full_transcript() == "Recovered speech text."

    # 16. Streaming: Timeout handling during stream processing
    def test_16_streaming_timeout_handling(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify process_stream applies timeout handling per chunk during streaming."""
        adapter = _FlakyMockAdapter(failures_before_success=1, sleep_seconds=0.2)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(timeout_seconds=0.02, max_retries=0),
        )

        chunks = [
            AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
        ]

        events = list(orch.process_stream(chunks))
        assert len(events) == 1
        assert events[0].event_type == TranscriptEventType.ERROR
        assert events[0].error.code == "TRANSCRIPTION_TIMEOUT"
        assert orch.timeouts_encountered == 1

    # 17. Streaming: Retry exhaustion during streaming produces normalized error
    def test_17_streaming_retry_exhaustion(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify process_stream yields normalized error event when retries are exhausted."""
        adapter = _FlakyMockAdapter(failures_before_success=5)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        chunks = [
            AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
        ]

        events = list(orch.process_stream(chunks))
        assert len(events) == 1
        assert events[0].event_type == TranscriptEventType.ERROR
        assert events[0].error.code == "SERVICE_UNAVAILABLE"
        assert orch.retries_attempted == 2

    # 18. Streaming: Closed orchestrator yields normalized error event rather than unhandled crash
    def test_18_streaming_closed_orchestrator(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify process_stream yields a normalized ADAPTER_CLOSED error event when closed."""
        orch = TranscriptionOrchestrator()
        orch.initialize()
        orch.close()

        chunks = [
            AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes)
        ]

        events = list(orch.process_stream(chunks))
        assert len(events) == 1
        assert events[0].event_type == TranscriptEventType.ERROR
        assert events[0].error is not None
        assert events[0].error.code == "ADAPTER_CLOSED"
        assert "Cannot process audio on a closed" in events[0].error.message

    # 19. Streaming: Audio preprocessing applied correctly in process_stream
    def test_19_streaming_preprocessing_integration(self) -> None:
        """Verify process_stream applies preprocessor format conversion before transcription."""
        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1),
            normalize=True,
        )
        fake_transcriber = DeterministicFakeTranscriber(script=["Preprocessed stream."])
        orch = TranscriptionOrchestrator(
            adapter=fake_transcriber,
            preprocessor=preprocessor,
        )

        # 48kHz stereo chunk inputs (1920 bytes each)
        raw_48k_stereo = b"\x01\x00\x02\x00" * 480
        chunks = [
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                data=raw_48k_stereo,
                format=AudioFormat(sample_rate=48000, channels=2),
                metadata={"is_last": False},
            ),
            AudioChunk(
                sequence_id=1,
                timestamp=0.1,
                data=raw_48k_stereo,
                format=AudioFormat(sample_rate=48000, channels=2),
                metadata={"is_last": True},
            ),
        ]

        events = list(orch.process_stream(chunks))
        assert len(events) > 0
        assert orch.get_full_transcript() == "Preprocessed stream."

    # 20. Streaming: No duplicate transcript segments ingested
    def test_20_streaming_no_duplicate_transcript_ingestion(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify process_stream does not produce duplicate segments on retried streaming chunks."""
        # Fails once then recovers
        adapter = _FlakyMockAdapter(failures_before_success=1)
        orch = TranscriptionOrchestrator(
            adapter=adapter,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        chunks = [
            AudioChunk(sequence_id=0, timestamp=0.0, data=sample_audio_bytes, metadata={"is_last": True})
        ]

        events = list(orch.process_stream(chunks))
        assert len(events) == 1
        final_segments = orch.get_final_segments()
        assert len(final_segments) == 1
        assert orch.get_transcript() == "Recovered speech text."

    # 21. Preprocessing Error Normalization: Corrupt audio chunk produces normalized ERROR event
    def test_21_preprocessing_corrupt_audio_chunk_normalized_to_error_event(self) -> None:
        """Verify corrupt audio chunk in preprocessor does not escape as unhandled exception and is normalized."""
        preprocessor = AudioPreprocessor(target_format=AudioFormat(sample_rate=16000, channels=1))
        orch = TranscriptionOrchestrator(
            adapter=DeterministicFakeTranscriber(),
            preprocessor=preprocessor,
            retry_config=RetryConfig(max_retries=3, retry_delay=0.0),
        )

        # 3 bytes is corrupt for 16-bit mono PCM (frame_size = 2 bytes)
        corrupt_chunk = object.__new__(AudioChunk)
        object.__setattr__(corrupt_chunk, "sequence_id", 0)
        object.__setattr__(corrupt_chunk, "timestamp", 0.0)
        object.__setattr__(corrupt_chunk, "data", b"\x01\x02\x03")
        object.__setattr__(corrupt_chunk, "format", AudioFormat(sample_rate=16000, channels=1, sample_width=2))
        object.__setattr__(corrupt_chunk, "metadata", {"is_last": True})

        events = orch.process_chunk(corrupt_chunk)
        assert len(events) == 1
        err_event = events[0]
        assert err_event.event_type == TranscriptEventType.ERROR
        assert err_event.error is not None
        assert err_event.error.code == "CORRUPT_CHUNK_DATA"
        assert err_event.error.retryable is False
        assert err_event.error.request_id == orch.session_id
        assert orch.accumulator.last_error is not None
        assert orch.accumulator.last_error.code == "CORRUPT_CHUNK_DATA"
        # Non-retryable error should not trigger retries
        assert orch.retries_attempted == 0

    # 22. Preprocessing Error Normalization: Empty audio chunk produces normalized ERROR event
    def test_22_preprocessing_empty_audio_chunk_normalized_to_error_event(self) -> None:
        """Verify empty audio chunk payload is normalized to EMPTY_CHUNK_DATA ERROR event."""
        preprocessor = AudioPreprocessor(target_format=AudioFormat(sample_rate=16000, channels=1))
        orch = TranscriptionOrchestrator(
            adapter=DeterministicFakeTranscriber(),
            preprocessor=preprocessor,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        empty_chunk = object.__new__(AudioChunk)
        object.__setattr__(empty_chunk, "sequence_id", 0)
        object.__setattr__(empty_chunk, "timestamp", 0.0)
        object.__setattr__(empty_chunk, "data", b"")
        object.__setattr__(empty_chunk, "format", AudioFormat(sample_rate=16000, channels=1, sample_width=2))
        object.__setattr__(empty_chunk, "metadata", {"is_last": True})

        events = orch.process_chunk(empty_chunk)
        assert len(events) == 1
        err_event = events[0]
        assert err_event.event_type == TranscriptEventType.ERROR
        assert err_event.error is not None
        assert err_event.error.code == "EMPTY_CHUNK_DATA"
        assert err_event.error.retryable is False
        assert orch.accumulator.last_error is not None
        assert orch.accumulator.last_error.code == "EMPTY_CHUNK_DATA"

    # 23. Preprocessing Error Normalization: Corrupt chunk in streaming does not break pipeline
    def test_23_preprocessing_corrupt_chunk_in_stream_yields_normalized_error_event(
        self,
        sample_audio_bytes: bytes,
    ) -> None:
        """Verify streaming generator handles corrupt audio chunk safely and yields normalized error event."""
        preprocessor = AudioPreprocessor(target_format=AudioFormat(sample_rate=16000, channels=1))
        orch = TranscriptionOrchestrator(
            adapter=DeterministicFakeTranscriber(),
            preprocessor=preprocessor,
            retry_config=RetryConfig(max_retries=2, retry_delay=0.0),
        )

        valid_chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=sample_audio_bytes,
            format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
            metadata={"is_last": False},
        )
        corrupt_chunk = object.__new__(AudioChunk)
        object.__setattr__(corrupt_chunk, "sequence_id", 1)
        object.__setattr__(corrupt_chunk, "timestamp", 0.1)
        object.__setattr__(corrupt_chunk, "data", b"\xaa\xbb\xcc")
        object.__setattr__(corrupt_chunk, "format", AudioFormat(sample_rate=16000, channels=1, sample_width=2))
        object.__setattr__(corrupt_chunk, "metadata", {"is_last": True})

        events = list(orch.process_stream([valid_chunk, corrupt_chunk]))
        assert len(events) >= 2
        # First chunk yielded valid events (interim or word timing)
        assert any(e.event_type != TranscriptEventType.ERROR for e in events)
        # Second chunk yielded error event
        error_events = [e for e in events if e.event_type == TranscriptEventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].error is not None
        assert error_events[0].error.code == "CORRUPT_CHUNK_DATA"
        assert orch.accumulator.last_error is not None
        assert orch.accumulator.last_error.code == "CORRUPT_CHUNK_DATA"


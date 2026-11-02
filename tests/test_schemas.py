"""Unit tests for STT schemas, constraints, and validation error handling."""

import pytest
from pydantic import ValidationError

from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestWordTimingSchema:
    """Tests for WordTiming schema validation and constraints."""

    def test_valid_word_timing(self) -> None:
        wt = WordTiming(word="hello", start_time=0.5, end_time=0.8, confidence=0.95)
        assert wt.word == "hello"
        assert wt.start_time == 0.5
        assert wt.end_time == 0.8
        assert wt.confidence == 0.95

    def test_zero_duration_word_boundary_allowed(self) -> None:
        wt = WordTiming(word="instant", start_time=1.0, end_time=1.0, confidence=0.8)
        assert wt.start_time == wt.end_time

    def test_reject_inverted_word_timestamps(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            WordTiming(word="inverted", start_time=1.5, end_time=1.0, confidence=0.9)
        assert "cannot be earlier than start_time" in str(exc_info.value)

    def test_reject_negative_word_timestamp(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)):
            WordTiming(word="negative", start_time=-0.1, end_time=0.5, confidence=0.9)

    def test_reject_out_of_range_confidence(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)):
            WordTiming(word="high", start_time=0.0, end_time=0.2, confidence=1.05)

        with pytest.raises((ValidationError, STTValidationError)):
            WordTiming(word="low", start_time=0.0, end_time=0.2, confidence=-0.01)

    def test_reject_empty_word(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)):
            WordTiming(word="", start_time=0.0, end_time=0.2, confidence=0.5)


class TestTranscriptSegmentSchema:
    """Tests for TranscriptSegment schema validation and constraints."""

    def test_valid_segment_creation(self, valid_final_segment: TranscriptSegment) -> None:
        assert valid_final_segment.segment_id == "seg-final-001"
        assert valid_final_segment.is_final is True
        assert len(valid_final_segment.words) == 7
        assert valid_final_segment.language == "en"

    def test_reject_inverted_segment_timestamps(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptSegment(
                text="Inverted timing test",
                start_time=5.0,
                end_time=3.0,
                confidence=0.9,
                is_final=True,
            )
        assert "cannot be earlier than start_time" in str(exc_info.value)

    def test_reject_negative_segment_start_time(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(
                text="Negative start",
                start_time=-1.0,
                end_time=2.0,
                confidence=0.9,
            )

    def test_reject_confidence_exceeding_unity(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)):
            TranscriptSegment(
                text="Overconfident",
                start_time=0.0,
                end_time=1.0,
                confidence=1.1,
            )

    def test_reject_invalid_language_tag(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptSegment(
                text="Bad language",
                start_time=0.0,
                end_time=1.0,
                confidence=0.9,
                language="invalid_language_code!!!",
            )
        assert "Invalid language format" in str(exc_info.value)

    def test_reject_empty_language_tag(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptSegment(
                text="Empty language",
                start_time=0.0,
                end_time=1.0,
                confidence=0.9,
                language="   ",
            )
        assert "Language code cannot be empty" in str(exc_info.value)

    def test_reject_word_timing_exceeding_segment_boundary(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptSegment(
                text="Boundary overflow",
                start_time=1.0,
                end_time=2.0,
                confidence=0.9,
                words=[
                    WordTiming(word="out-of-bounds", start_time=2.5, end_time=3.0, confidence=0.9)
                ],
            )
        assert "exceeds segment boundary" in str(exc_info.value)

    def test_reject_extra_unexpected_field(self) -> None:
        with pytest.raises(ValidationError):
            TranscriptSegment.model_validate({
                "text": "Payload with forbidden key",
                "start_time": 0.0,
                "end_time": 1.0,
                "confidence": 0.9,
                "forbidden_key": "not_allowed",
            })

    def test_json_roundtrip_serialization(self, valid_final_segment: TranscriptSegment) -> None:
        json_data = valid_final_segment.model_dump_json()
        restored = TranscriptSegment.model_validate_json(json_data)
        assert restored.segment_id == valid_final_segment.segment_id
        assert restored.text == valid_final_segment.text
        assert restored.start_time == valid_final_segment.start_time
        assert restored.end_time == valid_final_segment.end_time
        assert restored.confidence == valid_final_segment.confidence
        assert restored.is_final == valid_final_segment.is_final

    def test_transcript_segment_immutability(self, valid_final_segment: TranscriptSegment) -> None:
        """TranscriptSegment is frozen and rejects attribute reassignment after creation."""
        with pytest.raises(ValidationError):
            valid_final_segment.text = "Attempted text mutation"  # type: ignore[misc]


class TestTranscriptEventSchema:
    """Tests for TranscriptEvent streaming contract and lifecycle validation."""

    def test_valid_interim_event(self, valid_interim_segment: TranscriptSegment) -> None:
        event = TranscriptEvent(
            event_id="evt-001",
            event_type=TranscriptEventType.INTERIM,
            sequence_number=1,
            timestamp=0.8,
            segment=valid_interim_segment,
        )
        assert event.event_type == TranscriptEventType.INTERIM
        assert event.segment is not None
        assert event.segment.is_final is False

    def test_valid_final_event(self, valid_final_segment: TranscriptSegment) -> None:
        event = TranscriptEvent(
            event_id="evt-002",
            event_type=TranscriptEventType.FINAL,
            sequence_number=2,
            timestamp=1.5,
            segment=valid_final_segment,
        )
        assert event.event_type == TranscriptEventType.FINAL
        assert event.segment is not None
        assert event.segment.is_final is True

    def test_reject_interim_event_without_segment(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptEvent(
                event_type=TranscriptEventType.INTERIM,
                sequence_number=1,
                segment=None,
            )
        assert "require a non-null 'segment' payload" in str(exc_info.value)

    def test_reject_final_event_without_segment(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                sequence_number=2,
                segment=None,
            )
        assert "require a non-null 'segment' payload" in str(exc_info.value)

    def test_reject_mismatched_interim_event_with_final_segment(
        self, valid_final_segment: TranscriptSegment
    ) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptEvent(
                event_type=TranscriptEventType.INTERIM,
                sequence_number=1,
                segment=valid_final_segment,  # is_final is True!
            )
        assert "TranscriptEvent is marked 'interim' but its segment.is_final is True" in str(exc_info.value)

    def test_reject_mismatched_final_event_with_interim_segment(
        self, valid_interim_segment: TranscriptSegment
    ) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                sequence_number=2,
                segment=valid_interim_segment,  # is_final is False!
            )
        assert "TranscriptEvent is marked 'final' but its segment.is_final is False" in str(exc_info.value)

    def test_valid_error_event(self, sample_error_event: TranscriptEvent) -> None:
        assert sample_error_event.event_type == TranscriptEventType.ERROR
        assert sample_error_event.error is not None
        assert sample_error_event.error.code == "MICROPHONE_DROPOUT"
        assert sample_error_event.error.retryable is True

    def test_reject_error_event_without_error_detail(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            TranscriptEvent(
                event_type=TranscriptEventType.ERROR,
                sequence_number=5,
                error=None,
            )
        assert "require a non-null 'error' payload" in str(exc_info.value)


class TestSTTErrorDetailSchema:
    """Tests for STTErrorDetail conforming to API Specifications & Interface Contracts (doc 04), Section 5."""

    def test_error_detail_without_request_id(self) -> None:
        err = STTErrorDetail(code="AUDIO_DECODE_FAILED", message="Unable to parse WAV header.")
        assert err.code == "AUDIO_DECODE_FAILED"
        assert err.message == "Unable to parse WAV header."
        assert err.request_id is None
        assert err.retryable is False
        assert err.details == {}

    def test_error_detail_with_request_id(self) -> None:
        err = STTErrorDetail(
            code="INVALID_PAYLOAD",
            message="Payload missing required fields.",
            request_id="req-voice-001",
            retryable=True,
            details={"chunk_id": "chk-99"},
        )
        assert err.request_id == "req-voice-001"
        assert err.retryable is True
        assert err.details == {"chunk_id": "chk-99"}

    def test_to_api_error_shape(self) -> None:
        err = STTErrorDetail(
            code="INVALID_REQUEST",
            message="The request is invalid.",
            request_id="req-001",
            retryable=False,
            details={"field": "timestamp"},
        )
        api_dict = err.to_api_error()
        assert "error" in api_dict
        inner = api_dict["error"]
        assert inner["code"] == "INVALID_REQUEST"
        assert inner["message"] == "The request is invalid."
        assert inner["request_id"] == "req-001"
        assert inner["retryable"] is False
        assert inner["details"] == {"field": "timestamp"}

    def test_to_api_error_without_request_id_keeps_key(self) -> None:
        err = STTErrorDetail(code="RATE_LIMIT", message="Too many requests.")
        api_dict = err.to_api_error()
        assert "error" in api_dict
        assert api_dict["error"]["code"] == "RATE_LIMIT"
        assert api_dict["error"]["message"] == "Too many requests."
        assert api_dict["error"]["request_id"] is None

    def test_reject_secrets_in_error_message(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            STTErrorDetail(
                code="AUTH_FAILURE",
                message="Authentication failed for key sk-abcdef123456789012345678",
            )
        assert "sensitive credential data" in str(exc_info.value)

        with pytest.raises((ValidationError, STTValidationError)):
            STTErrorDetail(
                code="AUTH_FAILURE",
                message="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            )

        with pytest.raises((ValidationError, STTValidationError)):
            STTErrorDetail(
                code="AUTH_FAILURE",
                message="Invalid password: secretpassword123",
            )


class TestAudioChunkSchema:
    """Tests for AudioChunk binary payload contract."""

    def test_valid_audio_chunk(self, sample_audio_bytes: bytes) -> None:
        chunk = AudioChunk(
            data=sample_audio_bytes,
            sequence_number=0,
            timestamp=0.0,
            duration_ms=100.0,
            sample_rate=16000,
        )
        assert len(chunk.data) == len(sample_audio_bytes)
        assert chunk.sample_rate == 16000
        assert chunk.sequence_number == 0

    def test_reject_non_bytes_audio_data(self) -> None:
        with pytest.raises((ValidationError, STTValidationError)) as exc_info:
            AudioChunk(
                data="not-bytes-string",  # type: ignore[arg-type]
                sequence_number=0,
            )
        assert "must be bytes or bytearray" in str(exc_info.value)

    def test_reject_negative_sequence_number(self, sample_audio_bytes: bytes) -> None:
        with pytest.raises(ValidationError):
            AudioChunk(
                data=sample_audio_bytes,
                sequence_number=-1,
            )

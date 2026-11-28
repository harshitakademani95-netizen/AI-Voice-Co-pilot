"""AI Voice Co-Pilot - Speech-To-Text Pipeline Foundation (Workstream W2).

This package provides:
- Core transcript schemas (TranscriptSegment, TranscriptEvent, STTErrorDetail)
- Provider-neutral STT adapter interface (BaseSTTAdapter)
- Deterministic fake transcriber for offline/mock development (DeterministicFakeTranscriber)
- Canonical named demonstration and diagnostic fixtures (STTFixture, get_fixture, get_all_fixtures)
- Ordered segment accumulator for real-time speech streaming (OrderedSegmentAccumulator)
"""

try:
    from .schemas import (
        AudioChunk,
        STTErrorDetail,
        TranscriptEvent,
        TranscriptEventType,
        TranscriptSegment,
        WordTiming,
        STTValidationError,
    )
    from .adapter import (
        BaseSTTAdapter,
        STTAdapterConfig,
        STTAdapterStatus,
        STTAdapterState,
    )
    from .fixtures import (
        STTFixture,
        get_fixture,
        get_all_fixtures,
    )
    from .fake_transcriber import DeterministicFakeTranscriber
    from .accumulator import OrderedSegmentAccumulator
except ImportError as err:
    try:
        from voice_stt.schemas import (
            AudioChunk,
            STTErrorDetail,
            TranscriptEvent,
            TranscriptEventType,
            TranscriptSegment,
            WordTiming,
            STTValidationError,
        )
        from voice_stt.adapter import (
            BaseSTTAdapter,
            STTAdapterConfig,
            STTAdapterStatus,
            STTAdapterState,
        )
        from voice_stt.fixtures import (
            STTFixture,
            get_fixture,
            get_all_fixtures,
        )
        from voice_stt.fake_transcriber import DeterministicFakeTranscriber
        from voice_stt.accumulator import OrderedSegmentAccumulator
    except ImportError:
        raise ImportError(f"Failed to import voice_stt package: {err}") from err

__all__ = [
    "AudioChunk",
    "STTErrorDetail",
    "TranscriptEvent",
    "TranscriptEventType",
    "TranscriptSegment",
    "WordTiming",
    "STTValidationError",
    "BaseSTTAdapter",
    "STTAdapterConfig",
    "STTAdapterStatus",
    "STTAdapterState",
    "STTFixture",
    "get_fixture",
    "get_all_fixtures",
    "DeterministicFakeTranscriber",
    "OrderedSegmentAccumulator",
]

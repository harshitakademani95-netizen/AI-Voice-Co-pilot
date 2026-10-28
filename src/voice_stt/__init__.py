"""AI Voice Co-Pilot - Speech-To-Text Pipeline Foundation (Workstream W2).

This package provides:
- Core transcript schemas (TranscriptSegment, TranscriptEvent, STTErrorDetail)
- Provider-neutral STT adapter interface (BaseSTTAdapter)
- Deterministic fake transcriber for offline/mock development (DeterministicFakeTranscriber)
- Ordered segment accumulator for real-time speech streaming (OrderedSegmentAccumulator)
"""

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
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.accumulator import OrderedSegmentAccumulator

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
    "DeterministicFakeTranscriber",
    "OrderedSegmentAccumulator",
]

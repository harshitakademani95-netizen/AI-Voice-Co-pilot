"""
Audio Schemas Package.

Exports the canonical audio contracts:
- AudioChunk
- AudioFormat
- AudioError
- AudioEvent
- AudioEventType
"""

from src.schemas.audio import (
    SUPPORTED_CHANNELS,
    SUPPORTED_SAMPLE_RATES,
    SUPPORTED_SAMPLE_WIDTHS,
    AudioChunk,
    AudioError,
    AudioEvent,
    AudioEventType,
    AudioFormat,
)

__all__ = [
    "AudioChunk",
    "AudioFormat",
    "AudioError",
    "AudioEvent",
    "AudioEventType",
    "SUPPORTED_SAMPLE_RATES",
    "SUPPORTED_CHANNELS",
    "SUPPORTED_SAMPLE_WIDTHS",
]

"""
Audio Schemas Package.

Exports the canonical audio contracts:
- AudioChunk
- AudioFormat
- AudioError
"""

from src.schemas.audio import (
    SUPPORTED_CHANNELS,
    SUPPORTED_SAMPLE_RATES,
    SUPPORTED_SAMPLE_WIDTHS,
    AudioChunk,
    AudioError,
    AudioFormat,
)

__all__ = [
    "AudioChunk",
    "AudioFormat",
    "AudioError",
    "SUPPORTED_SAMPLE_RATES",
    "SUPPORTED_CHANNELS",
    "SUPPORTED_SAMPLE_WIDTHS",
]

"""
Audio Pipeline Components for AI Voice Copilot.

Exports:
- AudioChunker: Deterministic chunking utility.
- MockMicrophone: Simulated microphone audio source.
- AudioPreprocessor: Format standardization, resampling, downmixing, and normalization.
- convert_stereo_to_mono_pcm16: Interleaved stereo to mono converter.
- resample_pcm16: Linear interpolation sample rate converter.
- normalize_pcm16: Safe peak amplitude normalizer.
"""

from src.audio.chunker import AudioChunker
from src.audio.mock_source import MockMicrophone
from src.audio.preprocessing import (
    AudioPreprocessor,
    convert_stereo_to_mono_pcm16,
    normalize_pcm16,
    resample_pcm16,
)

__all__ = [
    "AudioChunker",
    "MockMicrophone",
    "AudioPreprocessor",
    "convert_stereo_to_mono_pcm16",
    "resample_pcm16",
    "normalize_pcm16",
]

"""Audio Preprocessing Module for AI Voice Copilot (W2 - STT, Day 13).

This module provides a provider-neutral, modular, and dependency-free audio
preprocessing layer designed to normalize, resample, downmix channels, and validate
raw PCM audio streams before they enter the Speech-to-Text (STT) pipeline.

Key Capabilities:
1. Audio Format Validation: Strict schema verification, empty/corrupt chunk detection.
2. Stereo-to-Mono Downmixing: Average multi-channel audio without overflow or clipping.
3. Resampling (Linear Interpolation): Convert arbitrary sample rates (e.g. 44.1kHz, 48kHz,
   8kHz) to standard STT rates (16kHz) preserving duration within ±1%.
4. Safe Amplitude Normalization: Scale low-amplitude signals to target peak while safely
   handling silence and clamping to prevent clipping.
5. End-to-End Pipeline Compatibility: Emits validated AudioChunk instances compatible
   with BaseSTTAdapter and TranscriptionOrchestrator.
"""

from __future__ import annotations

import math
import struct
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from src.schemas.audio import (
    AudioChunk,
    AudioError,
    AudioFormat,
    SUPPORTED_SAMPLE_RATES,
)


def convert_stereo_to_mono_pcm16(data: bytes, sample_width: int = 2) -> bytes:
    """Downmix 16-bit interleaved stereo PCM audio to single-channel mono.

    Averages left and right channel samples: (left + right) // 2.
    Clamps values to signed 16-bit range [-32768, 32767] to eliminate any potential overflow.

    Args:
        data: Interleaved 16-bit stereo PCM byte sequence.
        sample_width: Byte width per sample (must be 2 for 16-bit PCM).

    Returns:
        Mono 16-bit PCM byte sequence (half the input byte length).

    Raises:
        AudioError: If data length is unaligned with stereo frame size (4 bytes).
    """
    if sample_width != 2:
        raise AudioError(
            message=f"convert_stereo_to_mono_pcm16 only supports 16-bit audio (got sample_width={sample_width}).",
            code="UNSUPPORTED_SAMPLE_WIDTH",
            details={"sample_width": sample_width},
        )

    frame_size = 2 * sample_width  # 4 bytes per stereo frame
    if len(data) % frame_size != 0:
        raise AudioError(
            message=(
                f"Stereo data length ({len(data)} bytes) is not aligned to frame size ({frame_size} bytes)."
            ),
            code="CORRUPT_CHUNK_DATA",
            details={"data_length": len(data), "frame_size": frame_size},
        )

    num_frames = len(data) // frame_size
    if num_frames == 0:
        return b""

    # Unpack pairs of 16-bit signed integers: left and right
    unpack_format = f"<{num_frames * 2}h"
    samples = struct.unpack(unpack_format, data)

    # Average left and right channel for each frame
    mono_samples = [
        max(-32768, min(32767, (samples[2 * i] + samples[2 * i + 1]) // 2))
        for i in range(num_frames)
    ]

    return struct.pack(f"<{num_frames}h", *mono_samples)


def resample_pcm16(
    data: bytes,
    in_rate: int,
    out_rate: int,
    channels: int = 1,
) -> bytes:
    """Resample 16-bit linear PCM audio using pure-Python linear interpolation.

    Converts sample rate from in_rate to out_rate while preserving signal duration.
    Operates without third-party dependencies (no scipy/numpy required).

    Args:
        data: Raw 16-bit PCM bytes.
        in_rate: Source sample rate in Hz.
        out_rate: Target sample rate in Hz.
        channels: Channel count (1 for mono, 2 for stereo).

    Returns:
        Resampled 16-bit PCM bytes.

    Raises:
        AudioError: If data is unaligned, sample rates are non-positive, or rates unsupported.
    """
    if in_rate <= 0 or out_rate <= 0:
        raise AudioError(
            message=f"Sample rates must be strictly positive (in_rate={in_rate}, out_rate={out_rate}).",
            code="INVALID_SAMPLE_RATE",
            details={"in_rate": in_rate, "out_rate": out_rate},
        )

    if in_rate == out_rate:
        # Fast-path passthrough
        return data

    frame_size = channels * 2  # 2 bytes per sample for PCM16
    if len(data) % frame_size != 0:
        raise AudioError(
            message=(
                f"Data length ({len(data)} bytes) is not aligned to frame size ({frame_size} bytes)."
            ),
            code="CORRUPT_CHUNK_DATA",
            details={"data_length": len(data), "frame_size": frame_size},
        )

    num_in_frames = len(data) // frame_size
    if num_in_frames == 0:
        return b""

    # Calculate target output frame count to preserve duration
    # Duration = num_in_frames / in_rate = num_out_frames / out_rate
    num_out_frames = int(round(num_in_frames * (out_rate / in_rate)))
    if num_out_frames <= 0:
        num_out_frames = 1

    total_in_samples = num_in_frames * channels
    unpack_fmt = f"<{total_in_samples}h"
    in_samples = struct.unpack(unpack_fmt, data)

    out_samples: List[int] = []
    ratio = in_rate / out_rate

    for i in range(num_out_frames):
        # Precise continuous position in input frames
        pos = i * ratio
        idx0 = int(pos)
        frac = pos - idx0

        if idx0 >= num_in_frames - 1:
            idx0 = num_in_frames - 1
            idx1 = num_in_frames - 1
            frac = 0.0
        else:
            idx1 = idx0 + 1

        for ch in range(channels):
            s0 = in_samples[idx0 * channels + ch]
            s1 = in_samples[idx1 * channels + ch]
            interp = s0 + (s1 - s0) * frac
            clamped = max(-32768, min(32767, int(round(interp))))
            out_samples.append(clamped)

    return struct.pack(f"<{len(out_samples)}h", *out_samples)


def normalize_pcm16(
    data: bytes,
    target_peak: float = 0.95,
    sample_width: int = 2,
) -> bytes:
    """Safely normalize amplitude of 16-bit PCM audio to a specified target peak.

    Prevents clipping by strictly clamping all scaled samples to [-32768, 32767].
    Safely leaves silent or zero-energy audio unmodified to avoid division-by-zero.

    Args:
        data: 16-bit PCM bytes.
        target_peak: Desired peak amplitude as a ratio of full scale [0.0, 1.0]. Defaults to 0.95.
        sample_width: Must be 2 for 16-bit PCM.

    Returns:
        Normalized 16-bit PCM bytes.

    Raises:
        AudioError: If data length is not aligned to sample_width or target_peak is invalid.
    """
    if not (0.0 < target_peak <= 1.0):
        raise AudioError(
            message=f"target_peak must be in range (0.0, 1.0], got {target_peak}.",
            code="INVALID_TARGET_PEAK",
            details={"target_peak": target_peak},
        )

    if len(data) % sample_width != 0:
        raise AudioError(
            message=f"Data length ({len(data)} bytes) is not aligned to sample width ({sample_width} bytes).",
            code="CORRUPT_CHUNK_DATA",
            details={"data_length": len(data), "sample_width": sample_width},
        )

    num_samples = len(data) // sample_width
    if num_samples == 0:
        return b""

    samples = struct.unpack(f"<{num_samples}h", data)
    current_peak = max(abs(s) for s in samples)

    # If completely silent or zero amplitude, return unmodified
    if current_peak == 0:
        return data

    target_int = target_peak * 32767.0
    scale = target_int / float(current_peak)

    # If already at or very close to target (within 1%), return unmodified
    if abs(scale - 1.0) < 0.01:
        return data

    normalized_samples = [
        max(-32768, min(32767, int(round(s * scale))))
        for s in samples
    ]

    return struct.pack(f"<{num_samples}h", *normalized_samples)


class AudioPreprocessor:
    """Configurable, provider-neutral audio preprocessor for Speech-to-Text pipelines.

    Standardizes incoming audio streams into the exact format required by STT engines
    (default: 16kHz, 1-channel mono, 16-bit PCM, normalized amplitude).

    Attributes:
        target_format (AudioFormat): Target standardized audio format contract.
        normalize (bool): Whether to perform peak amplitude normalization.
        target_peak (float): Target peak ratio for normalization in (0.0, 1.0].
    """

    def __init__(
        self,
        target_format: Optional[AudioFormat] = None,
        normalize: bool = True,
        target_peak: float = 0.95,
    ) -> None:
        """Initialize the AudioPreprocessor.

        Args:
            target_format: Desired target AudioFormat. Defaults to 16kHz mono PCM16.
            normalize: Whether amplitude normalization should be enabled. Defaults to True.
            target_peak: Desired target peak ratio. Defaults to 0.95.

        Raises:
            AudioError: If target_format is invalid or target_peak is out of bounds.
        """
        self.target_format: AudioFormat = (
            target_format if target_format is not None else AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        )
        if not (0.0 < target_peak <= 1.0):
            raise AudioError(
                message=f"target_peak must be in range (0.0, 1.0], got {target_peak}.",
                code="INVALID_TARGET_PEAK",
                details={"target_peak": target_peak},
            )
        self.normalize: bool = bool(normalize)
        self.target_peak: float = float(target_peak)

    def validate_chunk(self, chunk: Any) -> AudioChunk:
        """Verify that chunk is a valid, non-empty, byte-aligned AudioChunk instance.

        Args:
            chunk: Candidate object to validate.

        Returns:
            The validated AudioChunk.

        Raises:
            AudioError: If chunk is invalid, empty, or corrupt.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioError(
                message=f"Expected AudioChunk instance, received: {type(chunk).__name__}.",
                code="INVALID_CHUNK_DATA",
                details={"received_type": type(chunk).__name__},
            )

        if len(chunk.data) == 0:
            raise AudioError(
                message="Audio chunk data cannot be empty (0 bytes received).",
                code="EMPTY_CHUNK_DATA",
                details={"sequence_id": chunk.sequence_id},
            )

        frame_size = chunk.format.frame_size
        if len(chunk.data) % frame_size != 0:
            raise AudioError(
                message=(
                    f"Corrupt audio chunk: payload length ({len(chunk.data)} bytes) is not a multiple "
                    f"of frame size ({frame_size} bytes)."
                ),
                code="CORRUPT_CHUNK_DATA",
                details={"data_length": len(chunk.data), "frame_size": frame_size},
            )

        return chunk

    def process_bytes(
        self,
        raw_data: bytes,
        in_format: AudioFormat,
    ) -> Tuple[bytes, AudioFormat]:
        """Preprocess raw PCM audio bytes to match target_format.

        Performs:
        1. Stereo-to-mono downmixing if input is 2-channel and target is 1-channel.
        2. Sample rate conversion via linear interpolation if in_rate != target_rate.
        3. Peak amplitude normalization if enabled.

        Args:
            raw_data: Input PCM bytes.
            in_format: Source AudioFormat metadata.

        Returns:
            Tuple of (processed_bytes, output_format).
        """
        if not isinstance(raw_data, (bytes, bytearray)):
            raise AudioError(
                message=f"Expected bytes or bytearray, got {type(raw_data).__name__}.",
                code="INVALID_CHUNK_DATA",
            )
        data = bytes(raw_data)
        if len(data) == 0:
            raise AudioError(
                message="Audio data cannot be empty.",
                code="EMPTY_CHUNK_DATA",
            )

        current_channels = in_format.channels
        current_rate = in_format.sample_rate

        # 1. Downmix stereo to mono if needed
        if current_channels == 2 and self.target_format.channels == 1:
            data = convert_stereo_to_mono_pcm16(data, sample_width=in_format.sample_width)
            current_channels = 1

        # 2. Resample if sample rate differs
        if current_rate != self.target_format.sample_rate:
            data = resample_pcm16(
                data=data,
                in_rate=current_rate,
                out_rate=self.target_format.sample_rate,
                channels=current_channels,
            )
            current_rate = self.target_format.sample_rate

        # 3. Normalize amplitude if enabled
        if self.normalize:
            data = normalize_pcm16(
                data=data,
                target_peak=self.target_peak,
                sample_width=self.target_format.sample_width,
            )

        output_format = AudioFormat(
            sample_rate=self.target_format.sample_rate,
            channels=current_channels,
            sample_width=self.target_format.sample_width,
            encoding=self.target_format.encoding,
        )

        return data, output_format

    def process_chunk(self, chunk: AudioChunk) -> AudioChunk:
        """Validate and preprocess an incoming AudioChunk instance.

        Transforms the audio data to standard target specifications while preserving
        original sequence IDs, timestamps, and attaching preprocessing metadata.

        Args:
            chunk: Input AudioChunk to preprocess.

        Returns:
            Preprocessed AudioChunk adhering to target_format.
        """
        self.validate_chunk(chunk)

        # Fast path: already matching format and normalization disabled
        if (
            chunk.format.sample_rate == self.target_format.sample_rate
            and chunk.format.channels == self.target_format.channels
            and chunk.format.sample_width == self.target_format.sample_width
            and not self.normalize
        ):
            return chunk

        processed_bytes, out_format = self.process_bytes(chunk.data, chunk.format)

        updated_metadata = dict(chunk.metadata)
        updated_metadata.update({
            "preprocessed": True,
            "original_format": chunk.format.to_dict(),
            "original_byte_length": len(chunk.data),
        })

        return AudioChunk(
            sequence_id=chunk.sequence_id,
            timestamp=chunk.timestamp,
            data=processed_bytes,
            format=out_format,
            metadata=updated_metadata,
        )

    def process_stream(self, chunks: Iterable[AudioChunk]) -> Iterator[AudioChunk]:
        """Preprocess an iterable stream of AudioChunk instances lazily.

        Args:
            chunks: Iterable producing input AudioChunks.

        Yields:
            Preprocessed AudioChunk instances.
        """
        for chunk in chunks:
            yield self.process_chunk(chunk)


"""
Deterministic mock microphone audio source for AI Voice Copilot.

This module provides a fake microphone source that emits validated AudioChunks.
It is deterministic: given the same configuration parameters, multiple runs or instances
will produce byte-for-byte identical audio chunks, sequence IDs, and timestamps.
"""

from __future__ import annotations

import math
import struct
import time
from typing import Iterator, Optional

from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class MockMicrophone:
    """
    Simulated mock microphone input source emitting continuous AudioChunk streams.

    Note:
        This is a purely synthetic audio source designed for pipeline development,
        testing, and simulation. It does NOT record from a physical microphone device.

    Features:
        - Purely deterministic audio generation (sine wave synthesis or custom pattern).
        - Monotonically increasing sequence IDs (0, 1, 2, ...) and strictly advancing timestamps.
        - Configurable sample rate, channels, chunk duration, and waveform frequency.
        - Supports both offline instant generation (fast unit testing) and real-time pacing
          (interactive CLI demo).
    """

    def __init__(
        self,
        audio_format: Optional[AudioFormat] = None,
        chunk_duration_ms: float = 20.0,
        frequency_hz: float = 440.0,
        amplitude: float = 0.5,
        total_duration_sec: Optional[float] = 1.0,
    ) -> None:
        """
        Initialize the MockMicrophone source.

        Args:
            audio_format (Optional[AudioFormat]): Format contract. Default: 16kHz mono PCM16.
            chunk_duration_ms (float): Duration per emitted chunk in milliseconds. Default: 20.0 ms.
            frequency_hz (float): Synthetic tone frequency in Hz (e.g. 440.0 for musical pitch A4).
            amplitude (float): Signal amplitude between 0.0 (silence) and 1.0 (full scale). Default: 0.5.
            total_duration_sec (Optional[float]): Finite stream duration limit in seconds.
                Defaults to 1.0 s for safe, bounded execution in tests and scripts.
                Explicitly pass total_duration_sec=None to allow continuous / unbounded streaming.

        Raises:
            AudioError: If parameters are invalid or out of allowable ranges.
        """
        self.format: AudioFormat = audio_format if audio_format is not None else AudioFormat()

        if not isinstance(chunk_duration_ms, (int, float)) or isinstance(chunk_duration_ms, bool) or not math.isfinite(chunk_duration_ms) or chunk_duration_ms <= 0:
            raise AudioError(
                message=f"chunk_duration_ms must be positive (received: {chunk_duration_ms}).",
                code="INVALID_CHUNK_DURATION",
                details={"chunk_duration_ms": chunk_duration_ms},
            )
        self.chunk_duration_ms: float = float(chunk_duration_ms)

        if not isinstance(frequency_hz, (int, float)) or isinstance(frequency_hz, bool) or not math.isfinite(frequency_hz) or frequency_hz <= 0:
            raise AudioError(
                message=f"frequency_hz must be positive (received: {frequency_hz}).",
                code="INVALID_PARAMETER",
                details={"frequency_hz": frequency_hz},
            )
        self.frequency_hz: float = float(frequency_hz)

        if not isinstance(amplitude, (int, float)) or isinstance(amplitude, bool) or not math.isfinite(amplitude) or not (0.0 <= amplitude <= 1.0):
            raise AudioError(
                message=f"amplitude must be between 0.0 and 1.0 (received: {amplitude}).",
                code="INVALID_PARAMETER",
                details={"amplitude": amplitude},
            )
        self.amplitude: float = float(amplitude)

        if total_duration_sec is not None:
            if not isinstance(total_duration_sec, (int, float)) or isinstance(total_duration_sec, bool) or not math.isfinite(total_duration_sec) or total_duration_sec <= 0:
                raise AudioError(
                    message=f"total_duration_sec must be positive (received: {total_duration_sec}).",
                    code="INVALID_PARAMETER",
                    details={"total_duration_sec": total_duration_sec},
                )
            self.total_duration_sec: Optional[float] = float(total_duration_sec)
        else:
            self.total_duration_sec = None

        # Sample calculations
        self.samples_per_chunk: int = int(round(self.format.sample_rate * (self.chunk_duration_ms / 1000.0)))
        if self.samples_per_chunk <= 0:
            raise AudioError(
                message=f"Chunk duration {chunk_duration_ms} ms produces 0 samples.",
                code="INVALID_CHUNK_DURATION",
                details={"chunk_duration_ms": chunk_duration_ms},
            )

        self.bytes_per_chunk: int = self.samples_per_chunk * self.format.frame_size

        # Stream state
        self._current_sequence_id: int = 0
        self._current_timestamp: float = 0.0
        self._sample_index: int = 0
        self._is_active: bool = True

    @property
    def is_active(self) -> bool:
        """True if the mock microphone stream is active and ready to emit chunks."""
        return self._is_active

    @property
    def current_sequence_id(self) -> int:
        """Current sequence ID of the next chunk to be emitted."""
        return self._current_sequence_id

    @property
    def current_timestamp(self) -> float:
        """Current timestamp in seconds of the stream position."""
        return self._current_timestamp

    def reset(self) -> None:
        """
        Reset the mock microphone back to its initial state.
        Resets sequence ID to 0, timestamp to 0.0, and waveform synthesis phase.
        Enables 100% reproducible stream replay.
        """
        self._current_sequence_id = 0
        self._current_timestamp = 0.0
        self._sample_index = 0
        self._is_active = True

    def close(self) -> None:
        """Close/deactivate the microphone source."""
        self._is_active = False

    def _synthesize_chunk(self, num_samples: int) -> bytes:
        """
        Synthesize deterministic linear PCM audio chunk data based on format sample_width.
        Generates a clean sine wave with continuous phase across chunk boundaries.
        Supports 1-byte (8-bit), 2-byte (16-bit), and 4-byte (32-bit int or float) sample widths.
        Supports mono (1 channel) and stereo (2 channels).
        """
        sample_rate = self.format.sample_rate
        two_pi_f = 2.0 * math.pi * self.frequency_hz
        channels = self.format.channels
        sample_width = self.format.sample_width
        encoding = self.format.encoding

        pcm_data = bytearray()

        for i in range(num_samples):
            global_sample = self._sample_index + i
            t = global_sample / sample_rate
            sin_val = math.sin(two_pi_f * t)

            if sample_width == 1:
                # 8-bit unsigned PCM [0, 255] centered at 128
                scaled = int(round(128.0 + 127.0 * self.amplitude * sin_val))
                clamped = max(0, min(255, scaled))
                sample_bytes = struct.pack("B", clamped)
            elif sample_width == 2:
                # 16-bit signed PCM [-32768, 32767]
                scaled = int(round(32767.0 * self.amplitude * sin_val))
                clamped = max(-32768, min(32767, scaled))
                fmt_str = ">h" if encoding == "pcm_s16be" else "<h"
                sample_bytes = struct.pack(fmt_str, clamped)
            elif sample_width == 4:
                if encoding in ("pcm_f32le", "pcm_f32be"):
                    # 32-bit IEEE float [-1.0, 1.0]
                    f_val = float(self.amplitude * sin_val)
                    clamped_f = max(-1.0, min(1.0, f_val))
                    fmt_str = ">f" if encoding == "pcm_f32be" else "<f"
                    sample_bytes = struct.pack(fmt_str, clamped_f)
                else:
                    # 32-bit signed int [-2147483648, 2147483647]
                    scaled = int(round(2147483647.0 * self.amplitude * sin_val))
                    clamped = max(-2147483648, min(2147483647, scaled))
                    fmt_str = ">i" if encoding == "pcm_s32be" else "<i"
                    sample_bytes = struct.pack(fmt_str, clamped)
            else:
                raise AudioError(
                    message=f"Unsupported sample width for mock mic synthesis: {sample_width}.",
                    code="INVALID_SAMPLE_WIDTH",
                    details={"sample_width": sample_width},
                )

            # Replicate sample for all channels (mono or stereo)
            for _ in range(channels):
                pcm_data.extend(sample_bytes)

        self._sample_index += num_samples
        return bytes(pcm_data)

    def _synthesize_chunk_pcm16(self, num_samples: int) -> bytes:
        """Backwards compatibility alias for _synthesize_chunk."""
        return self._synthesize_chunk(num_samples)

    def read_chunk(self) -> Optional[AudioChunk]:
        """
        Read the next discrete AudioChunk from the mock microphone stream.

        Returns:
            Optional[AudioChunk]: The next audio chunk, or None if stream duration reached or closed.
        """
        if not self._is_active:
            return None

        # Check if total duration limit reached.
        # Protect against rounding overshoot (e.g. at 22050 Hz with 10 ms chunks,
        # 220.5 rounds to 220, so 100 chunks = 0.9977 s; emitting a 101st chunk would overshoot to 1.0077 s).
        if self.total_duration_sec is not None:
            nominal_chunk_sec = self.chunk_duration_ms / 1000.0
            if self._current_sequence_id > 0 and (self._current_timestamp + nominal_chunk_sec / 2.0) >= self.total_duration_sec:
                self._is_active = False
                return None

        # Generate deterministic audio bytes
        chunk_data = self._synthesize_chunk(self.samples_per_chunk)

        chunk = AudioChunk(
            sequence_id=self._current_sequence_id,
            timestamp=round(self._current_timestamp, 6),
            data=chunk_data,
            format=self.format,
            metadata={"source": "MockMicrophone", "frequency_hz": self.frequency_hz},
        )

        # Increment sequence ID and advance timestamp
        self._current_sequence_id += 1
        self._current_timestamp = round(self._current_timestamp + chunk.duration_seconds, 6)

        return chunk

    def stream(
        self,
        simulate_realtime: bool = False,
        max_chunks: Optional[int] = None,
    ) -> Iterator[AudioChunk]:
        """
        Yield AudioChunks continuously until stream limit or max_chunks is reached.

        Args:
            simulate_realtime (bool): If True, sleeps for chunk_duration to simulate live mic capture.
            max_chunks (Optional[int]): Optional cap on number of chunks to yield.

        Yields:
            AudioChunk: Sequentially produced audio chunks.
        """
        chunks_emitted = 0
        chunk_interval_sec = self.samples_per_chunk / float(self.format.sample_rate)

        while self._is_active:
            if max_chunks is not None and chunks_emitted >= max_chunks:
                break

            start_t = time.perf_counter() if simulate_realtime else 0.0

            chunk = self.read_chunk()
            if chunk is None:
                break

            yield chunk
            chunks_emitted += 1

            if simulate_realtime:
                elapsed = time.perf_counter() - start_t
                sleep_duration = chunk_interval_sec - elapsed
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

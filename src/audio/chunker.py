"""
Deterministic audio chunker module for AI Voice Copilot.

This module provides the AudioChunker component responsible for splitting continuous
raw audio byte streams into fixed-duration AudioChunk instances with monotonically
increasing sequence IDs and exact timestamps.

Guarantee:
Same input bytes + format + chunk settings -> 100% identical AudioChunks every run.
"""

from __future__ import annotations

import math
from typing import Generator, Iterator, List, Optional

from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class AudioChunker:
    """
    Splits raw PCM audio streams into deterministic, validated AudioChunk instances.

    Attributes:
        format (AudioFormat): Audio format contract (sample rate, channels, bit depth).
        chunk_duration_ms (float): Target duration for each chunk in milliseconds (e.g. 20ms).
        bytes_per_chunk (int): Number of bytes in each chunk, aligned to frame_size.
    """

    def __init__(
        self,
        audio_format: Optional[AudioFormat] = None,
        chunk_duration_ms: float = 20.0,
    ) -> None:
        """
        Initialize AudioChunker.

        Args:
            audio_format (Optional[AudioFormat]): Format of the audio stream. Defaults to 16kHz mono PCM16.
            chunk_duration_ms (float): Chunk duration in ms. Must be positive (typically 10-100ms).

        Raises:
            AudioError: If chunk_duration_ms <= 0 or results in 0 samples per chunk.
        """
        self.format: AudioFormat = audio_format if audio_format is not None else AudioFormat()

        if not isinstance(chunk_duration_ms, (int, float)) or isinstance(chunk_duration_ms, bool) or not math.isfinite(chunk_duration_ms) or chunk_duration_ms <= 0:
            raise AudioError(
                message=f"Chunk duration must be a positive number in milliseconds (received: {chunk_duration_ms}).",
                code="INVALID_CHUNK_DURATION",
                details={"chunk_duration_ms": chunk_duration_ms},
            )

        self.chunk_duration_ms: float = float(chunk_duration_ms)

        # Calculate exact number of sample frames per chunk
        # Example: 16000 Hz * 0.020 s = 320 frames
        self.samples_per_chunk: int = int(round(self.format.sample_rate * (self.chunk_duration_ms / 1000.0)))
        if self.samples_per_chunk <= 0:
            raise AudioError(
                message=(
                    f"Chunk duration {chunk_duration_ms} ms results in 0 samples at "
                    f"sample rate {self.format.sample_rate} Hz."
                ),
                code="INVALID_CHUNK_DURATION",
                details={
                    "chunk_duration_ms": chunk_duration_ms,
                    "sample_rate": self.format.sample_rate,
                },
            )

        # Number of bytes per chunk = samples * frame_size (channels * sample_width)
        # Example: 320 frames * 2 bytes = 640 bytes
        self.bytes_per_chunk: int = self.samples_per_chunk * self.format.frame_size

    def chunk_stream(
        self,
        raw_audio: bytes,
        start_sequence_id: int = 0,
        start_timestamp: float = 0.0,
        drop_incomplete_tail: bool = False,
    ) -> Iterator[AudioChunk]:
        """
        Lazily chunk a raw audio byte buffer into deterministic AudioChunk instances.

        Args:
            raw_audio (bytes): Continuous raw PCM audio bytes to chunk.
            start_sequence_id (int): Initial sequence ID (must be >= 0). Default: 0.
            start_timestamp (float): Initial timestamp in seconds (must be >= 0.0). Default: 0.0.
            drop_incomplete_tail (bool): If True, drops an incomplete trailing chunk;
                                        if False, emits any remaining aligned frame bytes.

        Yields:
            AudioChunk: Validated audio chunks with monotonically increasing sequence IDs
                        and consistent timestamps.

        Raises:
            AudioError: If raw_audio is invalid, empty, or has corrupt frame alignment.
        """
        if not isinstance(raw_audio, (bytes, bytearray)):
            raise AudioError(
                message=f"raw_audio must be bytes or bytearray (received: {type(raw_audio).__name__}).",
                code="INVALID_CHUNK_DATA",
                details={"type": type(raw_audio).__name__},
            )

        if len(raw_audio) == 0:
            raise AudioError(
                message="Cannot chunk empty audio buffer (0 bytes received).",
                code="EMPTY_CHUNK_DATA",
                details={"buffer_size": 0},
            )

        # Check frame alignment across total buffer
        frame_size = self.format.frame_size
        if len(raw_audio) % frame_size != 0:
            raise AudioError(
                message=(
                    f"Corrupt input stream: audio length {len(raw_audio)} bytes is not aligned "
                    f"to frame size {frame_size} bytes."
                ),
                code="CORRUPT_CHUNK_DATA",
                details={
                    "buffer_size": len(raw_audio),
                    "frame_size": frame_size,
                    "remainder": len(raw_audio) % frame_size,
                },
            )

        if not isinstance(start_sequence_id, int) or isinstance(start_sequence_id, bool) or start_sequence_id < 0:
            raise AudioError(
                message=f"start_sequence_id must be a non-negative integer (received: {start_sequence_id}).",
                code="INVALID_SEQUENCE_ID",
                details={"start_sequence_id": start_sequence_id},
            )

        if not isinstance(start_timestamp, (int, float)) or isinstance(start_timestamp, bool) or not math.isfinite(start_timestamp) or start_timestamp < 0:
            raise AudioError(
                message=f"start_timestamp must be a non-negative, finite number (received: {start_timestamp}).",
                code="INVALID_TIMESTAMP",
                details={"start_timestamp": start_timestamp},
            )

        current_seq_id = start_sequence_id
        current_time = float(start_timestamp)
        chunk_step_sec = self.samples_per_chunk / float(self.format.sample_rate)

        total_bytes = len(raw_audio)
        offset = 0

        while offset < total_bytes:
            end_offset = offset + self.bytes_per_chunk
            chunk_bytes = bytes(raw_audio[offset:end_offset])

            # If this is a trailing partial chunk
            if len(chunk_bytes) < self.bytes_per_chunk:
                if drop_incomplete_tail:
                    break
                # Partial chunk must still be aligned with frame_size
                if len(chunk_bytes) % frame_size != 0:
                    raise AudioError(
                        message="Trailing partial chunk is unaligned with audio frame size.",
                        code="CORRUPT_CHUNK_DATA",
                        details={"tail_length": len(chunk_bytes), "frame_size": frame_size},
                    )

            chunk = AudioChunk(
                sequence_id=current_seq_id,
                timestamp=round(current_time, 6),
                data=chunk_bytes,
                format=self.format,
            )
            yield chunk

            # Monotonically advance sequence ID and timestamp
            current_seq_id += 1
            current_time += chunk.duration_seconds
            offset = end_offset

    def chunk_all(
        self,
        raw_audio: bytes,
        start_sequence_id: int = 0,
        start_timestamp: float = 0.0,
        drop_incomplete_tail: bool = False,
    ) -> List[AudioChunk]:
        """
        Eagerly chunk all raw audio into a list of AudioChunk instances.

        Returns:
            List[AudioChunk]: Deterministic list of audio chunks.
        """
        return list(
            self.chunk_stream(
                raw_audio=raw_audio,
                start_sequence_id=start_sequence_id,
                start_timestamp=start_timestamp,
                drop_incomplete_tail=drop_incomplete_tail,
            )
        )

    @staticmethod
    def validate_sequence(chunks: Any) -> List[AudioChunk]:
        """
        Validate that an iterable or sequence of AudioChunks forms a strictly ordered stream.

        Verifies:
            1. Every element is an AudioChunk instance.
            2. sequence_ids are strictly monotonically increasing (chunk[i].sequence_id > chunk[i-1].sequence_id).
            3. timestamps are strictly advancing (chunk[i].timestamp > chunk[i-1].timestamp).

        Returns:
            List[AudioChunk]: The validated list of audio chunks.

        Raises:
            AudioError: With code 'INVALID_PAYLOAD' if chunks input is not an iterable.
            AudioError: With code 'EMPTY_CHUNK_DATA' if chunk list is empty.
            AudioError: With code 'INVALID_CHUNK_DATA' if an item is not an AudioChunk.
            AudioError: With code 'INVALID_SEQUENCE_ORDER' if sequence IDs decrease or repeat.
            AudioError: With code 'INVALID_TIMESTAMP_ORDER' if timestamps decrease or repeat.
        """
        if not hasattr(chunks, "__iter__"):
            raise AudioError(
                message=f"Expected iterable of AudioChunk instances (received: {type(chunks).__name__}).",
                code="INVALID_PAYLOAD",
                details={"type": type(chunks).__name__},
            )

        chunk_list = list(chunks)
        if not chunk_list:
            raise AudioError(
                message="Cannot validate empty chunk sequence (0 chunks received).",
                code="EMPTY_CHUNK_DATA",
                details={"count": 0},
            )

        prev_chunk: Optional[AudioChunk] = None
        for idx, chunk in enumerate(chunk_list):
            if not isinstance(chunk, AudioChunk):
                raise AudioError(
                    message=f"Item at index {idx} is not an AudioChunk (got {type(chunk).__name__}).",
                    code="INVALID_CHUNK_DATA",
                    details={"index": idx, "type": type(chunk).__name__},
                )

            if prev_chunk is not None:
                if chunk.sequence_id <= prev_chunk.sequence_id:
                    raise AudioError(
                        message=(
                            f"Non-increasing sequence ID at index {idx}: current {chunk.sequence_id} "
                            f"<= previous {prev_chunk.sequence_id}."
                        ),
                        code="INVALID_SEQUENCE_ORDER",
                        details={
                            "index": idx,
                            "current_sequence_id": chunk.sequence_id,
                            "previous_sequence_id": prev_chunk.sequence_id,
                        },
                    )

                if chunk.timestamp <= prev_chunk.timestamp:
                    raise AudioError(
                        message=(
                            f"Non-advancing timestamp at index {idx}: current {chunk.timestamp} "
                            f"<= previous {prev_chunk.timestamp}."
                        ),
                        code="INVALID_TIMESTAMP_ORDER",
                        details={
                            "index": idx,
                            "current_timestamp": chunk.timestamp,
                            "previous_timestamp": prev_chunk.timestamp,
                        },
                    )

            prev_chunk = chunk

        return chunk_list

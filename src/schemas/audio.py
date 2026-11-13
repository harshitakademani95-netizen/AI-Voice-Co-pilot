"""
Audio schema definitions for AI Voice Copilot.

This module defines the foundational audio data contracts:
- AudioError: Custom exception for all audio validation and processing errors.
- AudioFormat: Audio format metadata specifying rate, channels, bit-depth, and encoding.
- AudioChunk: A single discrete segment of raw PCM audio data with timing and sequence info.

These schemas are defined once in this module to serve as the single source of truth
for all audio streaming, voice activity detection (VAD), speech-to-text (STT),
and downstream pipelines.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import math
from typing import Any, Dict, FrozenSet, Optional


# Standard audio sample rates supported across voice and speech processing pipelines
SUPPORTED_SAMPLE_RATES: FrozenSet[int] = frozenset({
    8000,   # Telephony standard (narrowband)
    11025,  # Quarter CD rate
    12000,  # Intermediate sampling rate
    16000,  # Standard voice recognition / Whisper / VAD default (wideband)
    22050,  # Half CD rate
    24000,  # Opus voice standard
    32000,  # Broadcast / modern telephony
    44100,  # CD standard audio
    48000,  # Professional digital audio / WebRTC default
    96000,  # High-definition audio
})

# Supported channel counts: 1 (mono) or 2 (stereo)
SUPPORTED_CHANNELS: FrozenSet[int] = frozenset({1, 2})

# Supported sample widths in bytes: 1 (8-bit), 2 (16-bit PCM), 4 (32-bit float/int)
SUPPORTED_SAMPLE_WIDTHS: FrozenSet[int] = frozenset({1, 2, 4})

# Supported audio encodings mapped by sample width in bytes
SUPPORTED_ENCODINGS_BY_WIDTH: Dict[int, FrozenSet[str]] = {
    1: frozenset({"pcm_u8", "pcm_s8"}),
    2: frozenset({"pcm_s16le", "pcm_s16be"}),
    4: frozenset({"pcm_s32le", "pcm_s32be", "pcm_f32le", "pcm_f32be"}),
}
ALL_SUPPORTED_ENCODINGS: FrozenSet[str] = frozenset().union(*SUPPORTED_ENCODINGS_BY_WIDTH.values())

DEFAULT_ENCODING_BY_WIDTH: Dict[int, str] = {
    1: "pcm_u8",
    2: "pcm_s16le",
    4: "pcm_s32le",
}


class AudioError(Exception):
    """
    Standard exception raised for any audio validation, schema, or processing failure.

    Conforms to the system design error specification (Doc 04, section 5):
    {
        "error": {
            "code": "<ERROR_CODE>",
            "message": "<Human-readable explanation>",
            "request_id": "<Optional tracking UUID>",
            "details": {...}
        }
    }

    Attributes:
        message (str): Human-readable error description explaining the cause of failure.
        code (str): Machine-readable error code (e.g., 'INVALID_SAMPLE_RATE', 'CORRUPT_CHUNK_DATA').
        details (Optional[Dict[str, Any]]): Contextual key-value pairs providing debug info.
        request_id (Optional[str]): Optional client/server request correlation ID.
    """

    def __init__(
        self,
        message: str,
        code: str = "AUDIO_ERROR",
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.code: str = code
        self.details: Dict[str, Any] = details or {}
        self.request_id: Optional[str] = request_id

    def to_dict(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Serialize exception to standard API error dictionary format.
        Includes request_id (optional), code, message, and details per Doc 04, section 5.
        """
        effective_req_id = request_id if request_id is not None else self.request_id
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": effective_req_id,
                "details": self.details,
            }
        }

    def __str__(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        if self.request_id:
            parts.append(f"request_id: {self.request_id}")
        if self.details:
            parts.append(f"details: {self.details}")
        if len(parts) > 1:
            return f"{parts[0]} ({', '.join(parts[1:])})"
        return parts[0]

    def __repr__(self) -> str:
        return (
            f"AudioError(code={self.code!r}, message={self.message!r}, "
            f"details={self.details!r}, request_id={self.request_id!r})"
        )


@dataclass(frozen=True)
class AudioFormat:
    """
    Audio format specification contract.

    Defines the sample rate, channel count, sample bit-depth, and encoding format
    for raw PCM audio streams.

    Fields & Constraints:
        sample_rate:
            - Type: int
            - Units: Hertz (Hz, samples per second)
            - Constraints: Must be positive and in SUPPORTED_SAMPLE_RATES
                           (e.g., 8000, 16000, 22050, 24000, 32000, 44100, 48000, 96000).
                           Common voice default: 16000 Hz.
        channels:
            - Type: int
            - Units: Count (1 = mono, 2 = stereo)
            - Constraints: Must be in {1, 2}. Standard voice default: 1 (mono).
        sample_width:
            - Type: int
            - Units: Bytes per individual sample
            - Constraints: Must be in {1, 2, 4}. Default: 2 (16-bit linear PCM).
        encoding:
            - Type: str
            - Units: Identifier string
            - Constraints: Only supported PCM encoding identifiers matching sample_width
                           are accepted:
                           - 1 byte (8-bit): 'pcm_u8', 'pcm_s8'
                           - 2 bytes (16-bit): 'pcm_s16le', 'pcm_s16be'
                           - 4 bytes (32-bit): 'pcm_s32le', 'pcm_s32be', 'pcm_f32le', 'pcm_f32be'
                           Default: 'pcm_s16le' (width 2), 'pcm_u8' (width 1), 'pcm_s32le' (width 4).
                           Unsupported codec names (e.g. 'banana') or encodings incompatible with
                           sample_width will raise AudioError with code 'INVALID_ENCODING'.
    """

    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    encoding: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate sample-rate, channels, and sample-width constraints upon instantiation."""
        # 0. Default encoding based on sample width if not explicitly provided
        if self.encoding is None:
            object.__setattr__(
                self,
                "encoding",
                DEFAULT_ENCODING_BY_WIDTH.get(self.sample_width, "pcm_s16le"),
            )

        # 1. Validate sample_rate
        if not isinstance(self.sample_rate, int) or isinstance(self.sample_rate, bool):
            raise AudioError(
                message=f"Sample rate must be an integer (received: {type(self.sample_rate).__name__}).",
                code="INVALID_SAMPLE_RATE",
                details={"sample_rate": self.sample_rate},
            )
        if self.sample_rate <= 0:
            raise AudioError(
                message=f"Sample rate must be strictly positive (received: {self.sample_rate} Hz).",
                code="INVALID_SAMPLE_RATE",
                details={"sample_rate": self.sample_rate},
            )
        if self.sample_rate not in SUPPORTED_SAMPLE_RATES:
            rates_list = sorted(list(SUPPORTED_SAMPLE_RATES))
            raise AudioError(
                message=(
                    f"Unsupported sample rate: {self.sample_rate} Hz. "
                    f"Must be one of: {rates_list}."
                ),
                code="INVALID_SAMPLE_RATE",
                details={"sample_rate": self.sample_rate, "supported": rates_list},
            )

        # 2. Validate channels
        if not isinstance(self.channels, int) or isinstance(self.channels, bool):
            raise AudioError(
                message=f"Channels must be an integer (received: {type(self.channels).__name__}).",
                code="INVALID_CHANNELS",
                details={"channels": self.channels},
            )
        if self.channels not in SUPPORTED_CHANNELS:
            raise AudioError(
                message=(
                    f"Invalid channel count: {self.channels}. "
                    f"Voice pipeline requires mono (1) or stereo (2)."
                ),
                code="INVALID_CHANNELS",
                details={"channels": self.channels, "supported": list(SUPPORTED_CHANNELS)},
            )

        # 3. Validate sample_width
        if not isinstance(self.sample_width, int) or isinstance(self.sample_width, bool):
            raise AudioError(
                message=f"Sample width must be an integer (received: {type(self.sample_width).__name__}).",
                code="INVALID_SAMPLE_WIDTH",
                details={"sample_width": self.sample_width},
            )
        if self.sample_width not in SUPPORTED_SAMPLE_WIDTHS:
            raise AudioError(
                message=(
                    f"Invalid sample width: {self.sample_width} bytes. "
                    f"Supported sample widths are {sorted(list(SUPPORTED_SAMPLE_WIDTHS))} bytes."
                ),
                code="INVALID_SAMPLE_WIDTH",
                details={"sample_width": self.sample_width, "supported": list(SUPPORTED_SAMPLE_WIDTHS)},
            )

        # 4. Validate encoding and match against sample_width
        if not isinstance(self.encoding, str) or not self.encoding.strip():
            raise AudioError(
                message="Encoding must be a non-empty string identifier.",
                code="INVALID_ENCODING",
                details={"encoding": self.encoding},
            )
        if self.encoding not in ALL_SUPPORTED_ENCODINGS:
            raise AudioError(
                message=(
                    f"Unsupported audio encoding: {self.encoding!r}. "
                    f"Supported encodings are: {sorted(list(ALL_SUPPORTED_ENCODINGS))}."
                ),
                code="INVALID_ENCODING",
                details={"encoding": self.encoding, "supported": sorted(list(ALL_SUPPORTED_ENCODINGS))},
            )
        valid_for_width = SUPPORTED_ENCODINGS_BY_WIDTH.get(self.sample_width, frozenset())
        if self.encoding not in valid_for_width:
            raise AudioError(
                message=(
                    f"Encoding {self.encoding!r} is incompatible with sample_width={self.sample_width} byte(s). "
                    f"Supported encodings for width {self.sample_width} are: {sorted(list(valid_for_width))}."
                ),
                code="INVALID_ENCODING",
                details={
                    "encoding": self.encoding,
                    "sample_width": self.sample_width,
                    "supported_for_width": sorted(list(valid_for_width)),
                },
            )

    @property
    def frame_size(self) -> int:
        """
        Number of bytes in a single multi-channel frame.
        Calculated as: channels * sample_width (e.g., 1 ch * 2 bytes = 2 bytes/frame).
        """
        return self.channels * self.sample_width

    @property
    def bytes_per_second(self) -> int:
        """
        Data throughput rate in bytes per second.
        Calculated as: sample_rate * channels * sample_width (e.g., 16000 * 1 * 2 = 32000 B/s).
        """
        return self.sample_rate * self.frame_size

    def to_dict(self) -> Dict[str, Any]:
        """Serialize AudioFormat to standard dictionary format."""
        return {
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width": self.sample_width,
            "encoding": self.encoding,
            "frame_size": self.frame_size,
            "bytes_per_second": self.bytes_per_second,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AudioFormat:
        """
        Construct an AudioFormat instance from a dictionary.

        Required fields:
            - 'sample_rate': Must be an integer matching one of SUPPORTED_SAMPLE_RATES.
            - 'channels': Must be an integer matching one of SUPPORTED_CHANNELS (1 or 2).

        Optional fields:
            - 'sample_width': Sample bit depth in bytes (1, 2, or 4). Defaults to 2 if omitted.
            - 'encoding': Codec identifier string. Defaults based on sample_width if omitted.

        Raises:
            AudioError: If data is not a dict (INVALID_PAYLOAD), if required fields
                        are missing (INVALID_PAYLOAD), or if values fail schema validation.
        """
        if not isinstance(data, dict):
            raise AudioError(
                message=f"Format payload must be a dictionary (received: {type(data).__name__}).",
                code="INVALID_PAYLOAD",
                details={"data_type": type(data).__name__},
            )

        if "sample_rate" not in data:
            raise AudioError(
                message="Missing required field 'sample_rate' in format dictionary payload.",
                code="INVALID_PAYLOAD",
                details={"missing_key": "sample_rate", "keys_provided": list(data.keys())},
            )

        if "channels" not in data:
            raise AudioError(
                message="Missing required field 'channels' in format dictionary payload.",
                code="INVALID_PAYLOAD",
                details={"missing_key": "channels", "keys_provided": list(data.keys())},
            )

        return cls(
            sample_rate=data["sample_rate"],
            channels=data["channels"],
            sample_width=data.get("sample_width", 2),
            encoding=data.get("encoding"),
        )


@dataclass(frozen=True)
class AudioChunk:
    """
    Audio chunk contract representing a slice of audio data in the pipeline.

    Fields & Constraints:
        sequence_id:
            - Type: int
            - Units: Monotonically increasing counter (0, 1, 2, ...)
            - Constraints: Must be non-negative integer (>= 0).
        timestamp:
            - Type: float
            - Units: Seconds (relative offset from stream start or POSIX timestamp)
            - Constraints: Must be non-negative, finite float or int (>= 0.0).
        data:
            - Type: bytes
            - Units: Raw binary PCM bytes
            - Constraints: Must be non-empty bytes. Length must be an exact integer
                           multiple of format.frame_size (channels * sample_width).
                           Mutable bytearray inputs are copied to immutable bytes upon init.
        format:
            - Type: AudioFormat
            - Constraints: Must be a valid AudioFormat instance.
        metadata:
            - Type: Dict[str, Any]
            - Units: Optional arbitrary annotations (e.g. source_id, snr, vad_flag)
            - Constraints: Dictionary, defaults to empty dict.
    """

    sequence_id: int
    timestamp: float
    data: bytes
    format: AudioFormat = field(default_factory=AudioFormat)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate sequence ID, timestamp, and byte payload integrity."""
        # 0. Defensive copies: convert mutable bytearray to immutable bytes and shallow copy metadata
        if isinstance(self.data, (bytes, bytearray)):
            object.__setattr__(self, "data", bytes(self.data))
        if isinstance(self.metadata, dict):
            object.__setattr__(self, "metadata", dict(self.metadata))

        # 1. Validate format
        if not isinstance(self.format, AudioFormat):
            raise AudioError(
                message=f"Expected format to be an AudioFormat instance, got {type(self.format).__name__}.",
                code="INVALID_FORMAT",
                details={"format": type(self.format).__name__},
            )

        # 2. Validate sequence_id
        if not isinstance(self.sequence_id, int) or isinstance(self.sequence_id, bool):
            raise AudioError(
                message=f"Sequence ID must be an integer (received: {type(self.sequence_id).__name__}).",
                code="INVALID_SEQUENCE_ID",
                details={"sequence_id": self.sequence_id},
            )
        if self.sequence_id < 0:
            raise AudioError(
                message=f"Sequence ID must be non-negative (received: {self.sequence_id}).",
                code="INVALID_SEQUENCE_ID",
                details={"sequence_id": self.sequence_id},
            )

        # 3. Validate timestamp (must be numeric, finite, non-negative)
        if not isinstance(self.timestamp, (int, float)) or isinstance(self.timestamp, bool):
            raise AudioError(
                message=f"Timestamp must be a float or integer (received: {type(self.timestamp).__name__}).",
                code="INVALID_TIMESTAMP",
                details={"timestamp": self.timestamp},
            )
        if not math.isfinite(self.timestamp):
            raise AudioError(
                message=f"Timestamp must be a finite number (received: {self.timestamp}).",
                code="INVALID_TIMESTAMP",
                details={"timestamp": self.timestamp},
            )
        if self.timestamp < 0:
            raise AudioError(
                message=f"Timestamp must be non-negative (received: {self.timestamp} s).",
                code="INVALID_TIMESTAMP",
                details={"timestamp": self.timestamp},
            )

        # 4. Validate data type
        if not isinstance(self.data, bytes):
            raise AudioError(
                message=f"Chunk data must be bytes or bytearray (received: {type(self.data).__name__}).",
                code="INVALID_CHUNK_DATA",
                details={"data_type": type(self.data).__name__},
            )

        # 5. Validate empty data
        if len(self.data) == 0:
            raise AudioError(
                message="Audio chunk data cannot be empty (0 bytes received).",
                code="EMPTY_CHUNK_DATA",
                details={"size_bytes": 0, "sequence_id": self.sequence_id},
            )

        # 6. Validate corrupt/unaligned data (must align with frame_size = channels * sample_width)
        frame_size = self.format.frame_size
        remainder = len(self.data) % frame_size
        if remainder != 0:
            raise AudioError(
                message=(
                    f"Corrupt audio chunk: byte length {len(self.data)} is not aligned with "
                    f"frame size {frame_size} bytes ({self.format.channels} channels * "
                    f"{self.format.sample_width} bytes/sample). Remainder: {remainder} bytes."
                ),
                code="CORRUPT_CHUNK_DATA",
                details={
                    "data_length": len(self.data),
                    "frame_size": frame_size,
                    "remainder": remainder,
                    "sequence_id": self.sequence_id,
                },
            )

    @property
    def size_bytes(self) -> int:
        """Size of the chunk data in bytes."""
        return len(self.data)

    @property
    def num_samples(self) -> int:
        """Total number of audio sample frames contained in this chunk."""
        return len(self.data) // self.format.frame_size

    @property
    def duration_seconds(self) -> float:
        """Audio duration represented by this chunk in seconds."""
        return self.num_samples / float(self.format.sample_rate)

    @property
    def duration_ms(self) -> float:
        """Audio duration represented by this chunk in milliseconds."""
        return self.duration_seconds * 1000.0

    def to_dict(self, include_base64_data: bool = True) -> Dict[str, Any]:
        """
        Serialize AudioChunk to dictionary format suitable for JSON / REST / WebSocket payloads.
        Data is base64-encoded to preserve exact byte fidelity.
        """
        res: Dict[str, Any] = {
            "sequence_id": self.sequence_id,
            "timestamp": round(float(self.timestamp), 6),
            "duration_ms": round(self.duration_ms, 2),
            "size_bytes": self.size_bytes,
            "num_samples": self.num_samples,
            "format": self.format.to_dict(),
            "metadata": dict(self.metadata),
        }
        if include_base64_data:
            res["data_b64"] = base64.b64encode(self.data).decode("ascii")
        return res

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> AudioChunk:
        """
        Construct an AudioChunk instance from a serialized dictionary.
        Wraps missing keys, bad base64, and non-dict payloads into AudioError.
        """
        if not isinstance(payload, dict):
            raise AudioError(
                message=f"Chunk payload must be a dictionary (received: {type(payload).__name__}).",
                code="INVALID_PAYLOAD",
                details={"payload_type": type(payload).__name__},
            )

        if "sequence_id" not in payload:
            raise AudioError(
                message="Missing required field 'sequence_id' in chunk dictionary payload.",
                code="INVALID_PAYLOAD",
                details={"missing_key": "sequence_id"},
            )

        if "timestamp" not in payload:
            raise AudioError(
                message="Missing required field 'timestamp' in chunk dictionary payload.",
                code="INVALID_PAYLOAD",
                details={"missing_key": "timestamp"},
            )

        raw_format = payload.get("format")
        if raw_format is None:
            format_obj = AudioFormat()
        elif isinstance(raw_format, AudioFormat):
            format_obj = raw_format
        elif isinstance(raw_format, dict):
            format_obj = AudioFormat.from_dict(raw_format)
        else:
            raise AudioError(
                message=f"Invalid format specification in dictionary (received: {type(raw_format).__name__}).",
                code="INVALID_FORMAT",
                details={"format": type(raw_format).__name__},
            )

        data_b64 = payload.get("data_b64")
        if data_b64 is not None:
            if not isinstance(data_b64, (str, bytes)):
                raise AudioError(
                    message=f"Field 'data_b64' must be a string (received: {type(data_b64).__name__}).",
                    code="CORRUPT_CHUNK_DATA",
                    details={"data_b64_type": type(data_b64).__name__},
                )
            try:
                data_bytes = base64.b64decode(data_b64, validate=True)
            except (binascii.Error, ValueError) as b64_err:
                raise AudioError(
                    message=f"Corrupt audio chunk: invalid base64 data ({b64_err}).",
                    code="CORRUPT_CHUNK_DATA",
                    details={"data_b64": str(data_b64)[:50], "error": str(b64_err)},
                ) from b64_err
        elif "data" in payload:
            raw_data = payload["data"]
            if isinstance(raw_data, (bytes, bytearray)):
                data_bytes = bytes(raw_data)
            else:
                raise AudioError(
                    message=f"Field 'data' must be bytes or bytearray (received: {type(raw_data).__name__}).",
                    code="INVALID_CHUNK_DATA",
                    details={"data_type": type(raw_data).__name__},
                )
        else:
            raise AudioError(
                message="Missing audio data in dictionary payload: either 'data_b64' or 'data' required.",
                code="EMPTY_CHUNK_DATA",
                details={"keys": list(payload.keys())},
            )

        raw_meta = payload.get("metadata", {})
        if not isinstance(raw_meta, dict):
            raise AudioError(
                message=f"Metadata must be a dictionary (received: {type(raw_meta).__name__}).",
                code="INVALID_PAYLOAD",
                details={"metadata_type": type(raw_meta).__name__},
            )

        return cls(
            sequence_id=payload["sequence_id"],
            timestamp=payload["timestamp"],
            data=data_bytes,
            format=format_obj,
            metadata=raw_meta,
        )

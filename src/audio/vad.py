"""
Voice Activity Detection (VAD) Interface and MockVAD Module (Week 2, D10-D11).

Provides an extensible VAD interface and a deterministic MockVAD implementation.

Features:
- Configurable RMS energy and speech probability thresholds.
- Enforced minimum speech duration to eliminate transient noise bursts.
- Configurable silence hang-over debounce to prevent speech fluttering.
- Deterministic event generation (SPEECH_START, SPEECH_ONGOING, SPEECH_END, SILENCE).

Note:
    MockVAD is a deterministic rule-based acoustic signal processor. It does NOT
    employ deep neural networks or machine-learning models.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
import math
import struct
from typing import Any, Dict, Optional

from src.schemas.audio import AudioChunk, AudioError


class VADEventType(str, Enum):
    """Voice Activity Detection event classifications."""

    SPEECH_START = "SPEECH_START"
    SPEECH_ONGOING = "SPEECH_ONGOING"
    SPEECH_END = "SPEECH_END"
    SILENCE = "SILENCE"


@dataclass(frozen=True)
class VADConfig:
    """
    Configuration parameters for Voice Activity Detection.

    Attributes:
        energy_threshold (float): Baseline RMS energy (t) where computed speech probability begins
            rising above 0.0. The effective RMS energy required to qualify as candidate speech is:
            effective_energy = energy_threshold * (1 + 2 * speech_probability_threshold).
            With the default speech_probability_threshold of 0.5, effective_energy = 2.0 * energy_threshold.
            Must be > 0.0. Defaults to 0.02 (on a 0.0 to 1.0 normalized scale).
        speech_probability_threshold (float): Minimum confidence cutoff [0.0, 1.0] for speech.
            Defaults to 0.5.
        min_speech_duration_ms (float): Minimum duration of continuous speech energy required
            before confirming speech (rejects short clicks/bursts). Defaults to 60.0 ms.
        min_silence_duration_ms (float): Hang-over silence duration required before confirming
            speech end (prevents premature cutoffs between syllables). Defaults to 100.0 ms.
    """

    energy_threshold: float = 0.02
    speech_probability_threshold: float = 0.5
    min_speech_duration_ms: float = 60.0
    min_silence_duration_ms: float = 100.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.energy_threshold, (int, float))
            or isinstance(self.energy_threshold, bool)
            or not math.isfinite(self.energy_threshold)
            or self.energy_threshold <= 0.0
        ):
            raise AudioError(
                message=f"energy_threshold must be a positive finite float (received: {self.energy_threshold}).",
                code="INVALID_PARAMETER",
                details={"energy_threshold": self.energy_threshold},
            )

        if (
            not isinstance(self.speech_probability_threshold, (int, float))
            or isinstance(self.speech_probability_threshold, bool)
            or not math.isfinite(self.speech_probability_threshold)
            or not (0.0 <= self.speech_probability_threshold <= 1.0)
        ):
            raise AudioError(
                message=(
                    f"speech_probability_threshold must be between 0.0 and 1.0 "
                    f"(received: {self.speech_probability_threshold})."
                ),
                code="INVALID_PARAMETER",
                details={"speech_probability_threshold": self.speech_probability_threshold},
            )

        if (
            not isinstance(self.min_speech_duration_ms, (int, float))
            or isinstance(self.min_speech_duration_ms, bool)
            or not math.isfinite(self.min_speech_duration_ms)
            or self.min_speech_duration_ms < 0.0
        ):
            raise AudioError(
                message=f"min_speech_duration_ms must be non-negative (received: {self.min_speech_duration_ms}).",
                code="INVALID_PARAMETER",
                details={"min_speech_duration_ms": self.min_speech_duration_ms},
            )

        if (
            not isinstance(self.min_silence_duration_ms, (int, float))
            or isinstance(self.min_silence_duration_ms, bool)
            or not math.isfinite(self.min_silence_duration_ms)
            or self.min_silence_duration_ms < 0.0
        ):
            raise AudioError(
                message=f"min_silence_duration_ms must be non-negative (received: {self.min_silence_duration_ms}).",
                code="INVALID_PARAMETER",
                details={"min_silence_duration_ms": self.min_silence_duration_ms},
            )


@dataclass(frozen=True)
class VADEvent:
    """
    Structured outcome of processing an AudioChunk through VAD.

    Attributes:
        event_type (VADEventType): Event classification.
        timestamp (float): Event timestamp in seconds. For SPEECH_START, this is the true onset
            timestamp of the first qualifying frame in the qualification window.
        duration_ms (float): Chunk duration in milliseconds.
        energy (float): Computed RMS signal energy [0.0, 1.0].
        speech_probability (float): Computed speech probability [0.0, 1.0].
        is_speech (bool): True if speech is actively recognized.
        chunk_sequence_id (int): Source AudioChunk sequence ID of the confirming chunk.
        onset_sequence_id (Optional[int]): Sequence ID of the first qualifying frame for SPEECH_START / SPEECH_ONGOING.
    """

    event_type: VADEventType
    timestamp: float
    duration_ms: float
    energy: float
    speech_probability: float
    is_speech: bool
    chunk_sequence_id: int
    onset_sequence_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert VADEvent to dictionary representation."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "energy": round(self.energy, 4),
            "speech_probability": round(self.speech_probability, 4),
            "is_speech": self.is_speech,
            "chunk_sequence_id": self.chunk_sequence_id,
            "onset_sequence_id": self.onset_sequence_id,
        }


class VADInterface(abc.ABC):
    """Abstract interface for Voice Activity Detection."""

    @abc.abstractmethod
    def process_chunk(self, chunk: AudioChunk) -> VADEvent:
        """
        Analyze an AudioChunk and return the resulting VADEvent.

        Args:
            chunk (AudioChunk): Input audio frame slice.

        Returns:
            VADEvent: Detection classification and metrics.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def reset(self) -> None:
        """Reset internal filter states, debounce windows, and temporal accumulators."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def is_speech_active(self) -> bool:
        """True if the VAD is currently in an active speech state."""
        raise NotImplementedError


class MockVAD(VADInterface):
    """
    Deterministic rule-based Voice Activity Detector.

    Uses root-mean-square (RMS) signal energy calculation combined with temporal
    integration to accurately detect speech onset, sustained speech, and silence,
    while discarding transient noise bursts shorter than min_speech_duration_ms.
    """

    def __init__(self, config: Optional[VADConfig] = None) -> None:
        """
        Initialize MockVAD.

        Args:
            config: Optional VADConfig. Uses standard defaults if None.
        """
        self._config: VADConfig = config if config is not None else VADConfig()

        # State tracking
        self._in_speech: bool = False
        self._accumulated_speech_ms: float = 0.0
        self._accumulated_silence_ms: float = 0.0
        self._processed_chunks_count: int = 0
        self._candidate_onset_timestamp: Optional[float] = None
        self._candidate_onset_sequence_id: Optional[int] = None

    @property
    def config(self) -> VADConfig:
        """Active VAD configuration."""
        return self._config

    @property
    def is_speech_active(self) -> bool:
        """True if speech is confirmed and active."""
        return self._in_speech

    @property
    def processed_chunks_count(self) -> int:
        """Total chunks processed since initialization or reset."""
        return self._processed_chunks_count

    def reset(self) -> None:
        """Reset all temporal history and speech state."""
        self._in_speech = False
        self._accumulated_speech_ms = 0.0
        self._accumulated_silence_ms = 0.0
        self._processed_chunks_count = 0
        self._candidate_onset_timestamp = None
        self._candidate_onset_sequence_id = None

    @staticmethod
    def calculate_rms_energy(chunk: AudioChunk) -> float:
        """
        Calculate normalized RMS signal energy from raw PCM bytes.

        Returns:
            float: RMS value normalized to [0.0, 1.0].
        """
        raw_bytes = chunk.data
        sample_width = chunk.format.sample_width

        if not raw_bytes:
            return 0.0

        if sample_width == 2:
            # 16-bit signed PCM
            num_samples = len(raw_bytes) // 2
            if num_samples == 0:
                return 0.0
            fmt = "<" + ("h" * num_samples) if chunk.format.encoding != "pcm_s16be" else ">" + ("h" * num_samples)
            samples = struct.unpack(fmt, raw_bytes[: num_samples * 2])
            sum_sq = sum((s / 32768.0) ** 2 for s in samples)
            return math.sqrt(sum_sq / num_samples)

        if sample_width == 1:
            # 8-bit unsigned PCM [0, 255] centered at 128
            num_samples = len(raw_bytes)
            samples = struct.unpack(f"{num_samples}B", raw_bytes)
            sum_sq = sum(((s - 128) / 128.0) ** 2 for s in samples)
            return math.sqrt(sum_sq / num_samples)

        if sample_width == 4:
            num_samples = len(raw_bytes) // 4
            if num_samples == 0:
                return 0.0
            if chunk.format.encoding in ("pcm_f32le", "pcm_f32be"):
                fmt = "<" + ("f" * num_samples) if chunk.format.encoding == "pcm_f32le" else ">" + ("f" * num_samples)
                samples = struct.unpack(fmt, raw_bytes[: num_samples * 4])
                sum_sq = sum(s ** 2 for s in samples)
            else:
                fmt = "<" + ("i" * num_samples) if chunk.format.encoding != "pcm_s32be" else ">" + ("i" * num_samples)
                samples = struct.unpack(fmt, raw_bytes[: num_samples * 4])
                sum_sq = sum((s / 2147483648.0) ** 2 for s in samples)
            return math.sqrt(sum_sq / num_samples)

        return 0.0

    def process_chunk(self, chunk: AudioChunk) -> VADEvent:
        """
        Process an AudioChunk through deterministic energy and temporal window VAD.

        Rejects short noise spikes that do not meet min_speech_duration_ms.
        """
        if chunk is None or not isinstance(chunk, AudioChunk):
            raise AudioError(
                message="process_chunk requires a valid AudioChunk instance.",
                code="INVALID_PARAMETER",
            )

        self._processed_chunks_count += 1
        duration_ms = chunk.duration_ms
        energy = self.calculate_rms_energy(chunk)

        # Compute deterministic speech probability score
        # 1. Allow explicit probability override via chunk metadata (for synthetic/ML test fixtures)
        if "speech_probability" in chunk.metadata:
            prob = float(chunk.metadata["speech_probability"])
        elif energy <= self._config.energy_threshold:
            prob = 0.0
        else:
            # Scales linearly from 0.0 at energy_threshold to 1.0 at 3 * energy_threshold
            prob = min(1.0, (energy - self._config.energy_threshold) / (2.0 * self._config.energy_threshold))

        raw_speech_detected = (
            energy >= self._config.energy_threshold
            and prob >= self._config.speech_probability_threshold
        )

        event_type: VADEventType
        event_timestamp: float = chunk.timestamp
        onset_sequence_id: Optional[int] = None

        if raw_speech_detected:
            if self._candidate_onset_timestamp is None:
                self._candidate_onset_timestamp = chunk.timestamp
                self._candidate_onset_sequence_id = chunk.sequence_id
            self._accumulated_speech_ms += duration_ms
            self._accumulated_silence_ms = 0.0

            # Enforce minimum speech duration before confirming speech onset
            if self._accumulated_speech_ms >= self._config.min_speech_duration_ms:
                if not self._in_speech:
                    self._in_speech = True
                    event_type = VADEventType.SPEECH_START
                    # SPEECH_START carries the true onset timestamp of the first qualifying frame
                    event_timestamp = self._candidate_onset_timestamp
                    onset_sequence_id = self._candidate_onset_sequence_id
                else:
                    event_type = VADEventType.SPEECH_ONGOING
                    onset_sequence_id = self._candidate_onset_sequence_id
            else:
                # Frame has speech-level energy but is still in transient noise qualification window
                event_type = VADEventType.SILENCE
                onset_sequence_id = None

        else:
            # Silence or energy below threshold detected in this frame
            if self._in_speech:
                self._accumulated_silence_ms += duration_ms

                # Hang-over debounce: wait for min_silence_duration_ms before declaring SPEECH_END
                if self._accumulated_silence_ms >= self._config.min_silence_duration_ms:
                    self._in_speech = False
                    self._accumulated_speech_ms = 0.0
                    self._accumulated_silence_ms = 0.0
                    self._candidate_onset_timestamp = None
                    self._candidate_onset_sequence_id = None
                    event_type = VADEventType.SPEECH_END
                else:
                    # Still in hang-over: retain speech state to avoid syllabic flutter
                    event_type = VADEventType.SPEECH_ONGOING
                    onset_sequence_id = self._candidate_onset_sequence_id
            else:
                # Normal silence / noise below speech qualification
                self._accumulated_speech_ms = 0.0
                self._accumulated_silence_ms += duration_ms
                self._candidate_onset_timestamp = None
                self._candidate_onset_sequence_id = None
                event_type = VADEventType.SILENCE

        return VADEvent(
            event_type=event_type,
            timestamp=event_timestamp,
            duration_ms=duration_ms,
            energy=energy,
            speech_probability=prob,
            is_speech=self._in_speech,
            chunk_sequence_id=chunk.sequence_id,
            onset_sequence_id=onset_sequence_id,
        )


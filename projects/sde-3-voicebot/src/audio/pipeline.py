"""
End-to-End Audio Pipeline for AI Voice Bot (Week 2, D14).

Integrates:
- Device Adapter & Permissions (MockAudioDevice)
- Lifecycle Controller (AudioLifecycleController)
- Bounded Stream Buffer (BoundedAudioBuffer)
- Voice Activity Detection (MockVAD)

Provides:
- Synchronous process_step() for streaming chunk capture, enqueue, dequeue, and VAD processing
- Explicit state management (start, pause, resume, stop)
- Anomaly simulation (overflow, gaps, late chunks)
- Deterministic test fixtures for audio scenarios
- Comprehensive status and metrics aggregation
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from src.audio.buffer import BoundedAudioBuffer, BufferMetrics, BufferPushResult, BufferPushStatus
from src.audio.device import (
    AudioDeviceInfo,
    AudioDeviceInterface,
    AudioPermissionState,
    MockAudioDevice,
)
from src.audio.lifecycle import AudioLifecycleController, AudioLifecycleState
from src.audio.mock_source import MockMicrophone
from src.audio.vad import MockVAD, VADConfig, VADEvent, VADEventType, VADInterface
from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class AudioPipeline:
    """
    End-to-end integrated audio processing pipeline.
    
    Coordinates device capture, lifecycle governance, bounded queueing,
    and voice activity detection into a unified, deterministic interface.
    """

    def __init__(
        self,
        device: Optional[AudioDeviceInterface] = None,
        buffer_capacity: int = 20,
        vad_config: Optional[VADConfig] = None,
        format: Optional[AudioFormat] = None,
    ) -> None:
        self.format: AudioFormat = format or AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.device: AudioDeviceInterface = device or MockAudioDevice(
            audio_format=self.format,
            initial_permission=AudioPermissionState.GRANTED,
        )
        self.lifecycle: AudioLifecycleController = AudioLifecycleController(device=self.device)
        self.buffer: BoundedAudioBuffer = BoundedAudioBuffer(capacity=buffer_capacity)
        self.vad: VADInterface = MockVAD(config=vad_config or VADConfig())
        self._processed_events: List[Tuple[AudioChunk, VADEvent]] = []
        self.last_push_result: Optional[BufferPushResult] = None

    @property
    def state(self) -> AudioLifecycleState:
        """Current lifecycle state of the pipeline."""
        return self.lifecycle.state

    @property
    def buffer_metrics(self) -> BufferMetrics:
        """Current buffer performance counters."""
        return self.buffer.get_metrics()

    def select_device(self, device_id: str) -> AudioDeviceInfo:
        """Select audio input device."""
        return self.device.select_device(device_id)

    def request_permission(self) -> AudioPermissionState:
        """Request permission on the active device."""
        return self.device.request_permission()

    def start(self) -> None:
        """
        Start the pipeline:
        Verifies permission, initializes device, starts lifecycle, and resets VAD.
        
        Restart Policy:
        Restart is supported from STOPPED or ERROR states. Sequence IDs, timestamps,
        buffer tracking, buffer metrics, processed events history (total_processed_steps),
        and VAD state are completely reset so the new session starts clean.
        """
        if self.lifecycle.state in (AudioLifecycleState.STOPPED, AudioLifecycleState.ERROR):
            self.buffer.clear()
            self.buffer.reset_metrics()
            self._processed_events.clear()
            self.last_push_result = None
        self.lifecycle.start()
        self.vad.reset()

    def pause(self) -> None:
        """Temporarily suspend audio capture without losing pipeline context."""
        self.lifecycle.pause()

    def resume(self) -> None:
        """Resume audio capture from paused state."""
        self.lifecycle.resume()

    def stop(self) -> None:
        """
        Terminate audio capture, release device resources, and clear buffer.
        """
        self.lifecycle.stop()
        self.buffer.clear()

    def process_step(self) -> Optional[Tuple[AudioChunk, VADEvent]]:
        """
        Execute a single capture-enqueue-dequeue-VAD pipeline step:
        1. Validates RUNNING lifecycle state.
        2. Captures raw chunk from active device through lifecycle controller.
        3. Pushes chunk to bounded buffer (handling backpressure if full).
        4. Consumes oldest chunk from buffer in FIFO order (ensures buffer drains even during drops).
        5. Evaluates chunk with VAD to produce speech/silence event.
        6. Returns (AudioChunk, VADEvent) for the consumed chunk.
        """
        if self.lifecycle.state != AudioLifecycleState.RUNNING:
            return None

        # 1. Capture via lifecycle controller (governs state & sequence validation)
        chunk = self.lifecycle.read_chunk()
        if chunk is None:
            return None

        # 2. Push to bounded buffer (drops if capacity exceeded, records drop metrics)
        self.last_push_result = self.buffer.push(chunk)

        # 3. Dequeue oldest chunk from buffer (prevents starvation when buffer is full)
        dequeued = self.buffer.pop()
        if dequeued is None:
            return None

        # 4. Process through VAD
        event = self.vad.process_chunk(dequeued)
        pair = (dequeued, event)
        self._processed_events.append(pair)
        return pair

    def capture_burst(self, n: int) -> List[BufferPushResult]:
        """
        Read n real chunks from the device through the lifecycle controller
        and push them into the bounded buffer without consuming them.
        Enables testing overflow directly through the real device and lifecycle path.
        """
        if self.lifecycle.state != AudioLifecycleState.RUNNING:
            raise AudioError(
                message=f"Cannot capture burst: Pipeline is in {self.lifecycle.state.value} state (must be RUNNING).",
                code="INVALID_LIFECYCLE_STATE",
            )
        results: List[BufferPushResult] = []
        for _ in range(n):
            chunk = self.lifecycle.read_chunk()
            if chunk is None:
                break
            res = self.buffer.push(chunk)
            results.append(res)
        return results

    def simulate_overflow(self, burst_count: int = 25) -> List[BufferPushResult]:
        """
        Test helper: Directly inject simulated audio chunks to demonstrate backpressure.
        Starts at the buffer's expected sequence ID to avoid introducing artificial sequence gaps.
        """
        results: List[BufferPushResult] = []
        fmt = self.format
        zero_data = b"\x00" * 640  # 20ms @ 16kHz mono 16-bit
        base_seq = self.buffer._expected_sequence_id if self.buffer._expected_sequence_id is not None else 0
        base_timestamp = float(base_seq) * 0.02

        for i in range(burst_count):
            c = AudioChunk(
                sequence_id=base_seq + i,
                timestamp=base_timestamp + float(i) * 0.02,
                format=fmt,
                data=zero_data,
            )
            res = self.buffer.push(c)
            self.last_push_result = res
            results.append(res)

        return results

    def get_status(self) -> Dict[str, Any]:
        """Aggregate high-level pipeline status and metrics."""
        device_info = self.device.selected_device
        return {
            "lifecycle_state": self.lifecycle.state.value,
            "device": {
                "id": device_info.device_id if device_info else None,
                "name": device_info.name if device_info else None,
                "permission": self.device.get_permission_status().value,
                "is_open": self.device.is_open,
            },
            "buffer": self.buffer.get_metrics().to_dict(),
            "vad": {
                "is_speech_active": self.vad.is_speech_active,
                "energy_threshold": self.vad.config.energy_threshold,
                "speech_probability_threshold": self.vad.config.speech_probability_threshold,
            },
            "total_processed_steps": len(self._processed_events),
            "last_push_result": (
                {
                    "status": self.last_push_result.status.value,
                    "sequence_id": self.last_push_result.sequence_id,
                    "dropped_count": self.last_push_result.dropped_count,
                    "reason": self.last_push_result.reason,
                }
                if self.last_push_result
                else None
            ),
        }


# ==============================================================================
# Deterministic Test Fixtures (Week 2, D14)
# ==============================================================================

def create_deterministic_chunk(
    sequence_id: int,
    timestamp: float,
    amplitude: float = 0.0,
    frequency: float = 440.0,
    duration_ms: float = 20.0,
    sample_rate: int = 16000,
) -> AudioChunk:
    """
    Generate a deterministic synthetic PCM 16-bit mono AudioChunk.
    amplitude: 0.0 (silence) to 1.0 (full scale 32767).
    """
    fmt = AudioFormat(sample_rate=sample_rate, channels=1, sample_width=2)
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    raw_bytes = bytearray()

    for n in range(num_samples):
        if amplitude <= 0.0:
            val = 0
        else:
            t = float(n) / float(sample_rate)
            val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * frequency * t))
            val = max(-32768, min(32767, val))

        raw_bytes.extend(val.to_bytes(2, byteorder="little", signed=True))

    return AudioChunk(
        sequence_id=sequence_id,
        timestamp=timestamp,
        format=fmt,
        data=bytes(raw_bytes),
    )


def generate_speech_fixture(
    num_chunks: int = 10,
    amplitude: float = 0.5,
    sample_rate: int = 16000,
) -> List[AudioChunk]:
    """Fixture producing continuous speech-level audio chunks."""
    chunks: List[AudioChunk] = []
    for i in range(num_chunks):
        chunks.append(
            create_deterministic_chunk(
                sequence_id=i,
                timestamp=i * 0.02,
                amplitude=amplitude,
                duration_ms=20.0,
                sample_rate=sample_rate,
            )
        )
    return chunks


def generate_silence_fixture(
    num_chunks: int = 10,
    sample_rate: int = 16000,
) -> List[AudioChunk]:
    """Fixture producing pure zero-amplitude silence chunks."""
    chunks: List[AudioChunk] = []
    for i in range(num_chunks):
        chunks.append(
            create_deterministic_chunk(
                sequence_id=i,
                timestamp=i * 0.02,
                amplitude=0.0,
                duration_ms=20.0,
                sample_rate=sample_rate,
            )
        )
    return chunks


def generate_noise_burst_fixture(
    burst_chunks: int = 2,  # 40ms burst (below 60ms min speech threshold)
    total_chunks: int = 8,
    amplitude: float = 0.6,
    sample_rate: int = 16000,
) -> List[AudioChunk]:
    """
    Fixture producing silence with an isolated short noise burst.
    Used to test noise burst rejection in MockVAD.
    """
    chunks: List[AudioChunk] = []
    for i in range(total_chunks):
        amp = amplitude if i < burst_chunks else 0.0
        chunks.append(
            create_deterministic_chunk(
                sequence_id=i,
                timestamp=i * 0.02,
                amplitude=amp,
                duration_ms=20.0,
                sample_rate=sample_rate,
            )
        )
    return chunks

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

import logging
import math
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

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
from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat

logger = logging.getLogger(__name__)


class AudioPipeline:
    """
    End-to-end integrated audio processing pipeline.
    
    Coordinates device capture, lifecycle governance, bounded queueing,
    voice activity detection, and normalized audio event generation into a unified,
    deterministic interface.
    """

    def __init__(
        self,
        device: Optional[AudioDeviceInterface] = None,
        buffer_capacity: int = 20,
        vad_config: Optional[VADConfig] = None,
        format: Optional[AudioFormat] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        on_event_callback: Optional[Callable[[AudioEvent], None]] = None,
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

        # Normalized Audio Events & Session Context (Week 3, D15-D21)
        if session_id is not None:
            if not isinstance(session_id, str) or not session_id.strip() or isinstance(session_id, bool):
                raise AudioError("session_id must be a non-empty string.", code="INVALID_PARAMETER")
            self.session_id: str = session_id
        else:
            self.session_id = f"session-audio-{uuid.uuid4().hex[:8]}"

        if correlation_id is not None:
            if not isinstance(correlation_id, str) or not correlation_id.strip() or isinstance(correlation_id, bool):
                raise AudioError("correlation_id must be a non-empty string.", code="INVALID_PARAMETER")
            self.correlation_id: str = correlation_id
        else:
            self.correlation_id = f"corr-audio-{uuid.uuid4().hex[:8]}"

        self._on_event_callback: Optional[Callable[[AudioEvent], None]] = on_event_callback
        self._event_sequence: int = 0
        self._global_event_sequence: int = 0
        self._emitted_events: List[AudioEvent] = []
        self._historical_events: List[AudioEvent] = []
        self._unpolled_events: List[AudioEvent] = []
        self._last_step_events: List[AudioEvent] = []
        self._current_segment_id: Optional[str] = None
        self._segment_counter: int = 0
        self._segment_start_timestamp: Optional[float] = None
        self._segment_chunk_count: int = 0
        self._segment_speech_duration_ms: float = 0.0
        self._in_silence: bool = False
        self._is_cancelled: bool = False
        self._last_cancelled_event: Optional[AudioEvent] = None
        self._last_device_lost_event: Optional[AudioEvent] = None
        self.last_error: Optional[AudioError] = None
        self._transcription_bridge: Optional[Any] = None

    @property
    def state(self) -> AudioLifecycleState:
        """Current lifecycle state of the pipeline."""
        return self.lifecycle.state

    @property
    def buffer_metrics(self) -> BufferMetrics:
        """Current buffer performance counters."""
        return self.buffer.get_metrics()

    @property
    def latest_events(self) -> List[AudioEvent]:
        """Normalized audio events emitted during the most recent process_step or chunk evaluation."""
        return list(self._last_step_events)

    @property
    def active_segment_id(self) -> Optional[str]:
        """Current speech segment ID if currently in an active speech segment, otherwise None."""
        return self._current_segment_id

    def select_device(self, device_id: str) -> AudioDeviceInfo:
        """Select audio input device."""
        return self.device.select_device(device_id)

    def request_permission(self) -> AudioPermissionState:
        """Request permission on the active device."""
        return self.device.request_permission()

    @property
    def is_cancelled(self) -> bool:
        """True if the audio session has been cancelled."""
        return self._is_cancelled

    def set_session(self, session_id: str, correlation_id: Optional[str] = None) -> None:
        """
        Update active session tracking identifiers with strict validation (Week 3, D16).
        """
        if not isinstance(session_id, str) or not session_id.strip() or isinstance(session_id, bool):
            raise AudioError("session_id must be a non-empty string.", code="INVALID_PARAMETER")
        self.session_id = session_id
        if correlation_id is not None:
            if not isinstance(correlation_id, str) or not correlation_id.strip() or isinstance(correlation_id, bool):
                raise AudioError("correlation_id must be a non-empty string.", code="INVALID_PARAMETER")
            self.correlation_id = correlation_id

    def _emit_event(
        self,
        event_type: AudioEventType,
        timestamp: float,
        chunk: Optional[AudioChunk] = None,
        segment_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> AudioEvent:
        """Internal factory to construct, store, and dispatch a normalized AudioEvent."""
        seq = self._event_sequence
        self._event_sequence += 1
        self._global_event_sequence += 1
        effective_session_id = session_id or self.session_id
        effective_correlation_id = correlation_id or self.correlation_id
        prefix = {
            AudioEventType.SPEECH_START: "evt-start",
            AudioEventType.SPEECH_END: "evt-end",
            AudioEventType.AUDIO_CHUNK: "evt-chunk",
            AudioEventType.SILENCE: "evt-silence",
            AudioEventType.DEVICE_LOST: "evt-devloss",
            AudioEventType.DEVICE_RECONNECTED: "evt-devrecon",
            AudioEventType.CANCELLED: "evt-cancel",
        }.get(event_type, "evt")
        event_id = f"{prefix}-{effective_session_id}-{self._global_event_sequence}"
        evt = AudioEvent(
            event_id=event_id,
            event_type=event_type,
            session_id=effective_session_id,
            correlation_id=effective_correlation_id,
            sequence_number=seq,
            timestamp=max(0.0, float(timestamp)),
            chunk=chunk,
            segment_id=segment_id,
            metadata=metadata or {},
        )
        self._emitted_events.append(evt)
        self._unpolled_events.append(evt)
        if self._on_event_callback is not None:
            try:
                self._on_event_callback(evt)
            except Exception as exc:
                logger.warning("Event callback error for event %s: %s", event_id, exc)
        return evt

    def get_events_for_session(self, session_id: str) -> List[AudioEvent]:
        """Return all events filtered by session identifier, including across restarts (Week 3, D16 & B10)."""
        all_events = self._historical_events + self._emitted_events
        return [e for e in all_events if e.session_id == session_id]

    def trace_events(self, correlation_id: str) -> List[AudioEvent]:
        """Trace all events sharing the given correlation identifier (Week 3, D16 & B10)."""
        all_events = self._historical_events + self._emitted_events
        return [e for e in all_events if e.correlation_id == correlation_id]

    def get_events(self) -> List[AudioEvent]:
        """Return a chronological list of all normalized AudioEvents emitted in the current session."""
        return list(self._emitted_events)

    def poll_events(self) -> List[AudioEvent]:
        """Drain and return any new AudioEvents emitted since the previous poll."""
        events = list(self._unpolled_events)
        self._unpolled_events.clear()
        return events

    def get_events_by_type(self, event_type: AudioEventType) -> List[AudioEvent]:
        """Return all emitted events matching a specific AudioEventType."""
        return [e for e in self._emitted_events if e.event_type == event_type]

    def start(
        self,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Start the pipeline:
        Verifies permission, initializes device, starts lifecycle, and resets VAD.
        
        Restart Policy (Week 3, B10):
        Restart is supported from STOPPED or ERROR states. Buffer, VAD, and step history
        are reset for the new session, while historical events are preserved in the event ledger.
        """
        if session_id is not None:
            self.set_session(session_id, correlation_id)
        elif correlation_id is not None:
            self.set_session(self.session_id, correlation_id)

        self._is_cancelled = False
        self.last_error = None
        self._last_cancelled_event = None
        self._last_device_lost_event = None
        self._in_silence = False

        if self.lifecycle.state in (AudioLifecycleState.STOPPED, AudioLifecycleState.ERROR):
            self.buffer.clear()
            self.buffer.reset_metrics()
            self._processed_events.clear()
            self.last_push_result = None
            self._event_sequence = 0
            # Preserve prior events into historical ledger (B10)
            if self._emitted_events:
                self._historical_events.extend(self._emitted_events)
                self._emitted_events.clear()
            self._unpolled_events.clear()
            self._last_step_events.clear()
            self._current_segment_id = None
            self._segment_counter = 0
            self._segment_start_timestamp = None
            self._segment_chunk_count = 0
            self._segment_speech_duration_ms = 0.0

        self.lifecycle.start()
        self.vad.reset()

        # If transcription bridge is attached, inform it of new session (B4)
        if self._transcription_bridge is not None:
            try:
                self._transcription_bridge.start_new_session(self.session_id, self.correlation_id)
            except Exception as exc:
                logger.warning("Bridge session reset error on start: %s", exc)

    def pause(self) -> None:
        """Temporarily suspend audio capture without losing pipeline context."""
        self.lifecycle.pause()

    def resume(self) -> None:
        """Resume audio capture from paused state."""
        self.lifecycle.resume()

    def stop(self) -> None:
        """
        Terminate audio capture, release device resources, and clear buffer.
        If a speech segment is currently open, safely emit a SPEECH_END event to complete it.
        """
        if self._current_segment_id is not None:
            speech_dur_ms = round(self._segment_speech_duration_ms, 2) if self._segment_speech_duration_ms > 0 else (
                max(0.0, self._segment_chunk_count * 20.0)
            )
            last_ts = self._emitted_events[-1].timestamp if self._emitted_events else 0.0
            self._emit_event(
                event_type=AudioEventType.SPEECH_END,
                timestamp=last_ts,
                chunk=None,
                segment_id=self._current_segment_id,
                metadata={
                    "speech_duration_ms": speech_dur_ms,
                    "total_speech_chunks": self._segment_chunk_count,
                    "reason": "stream_stopped",
                    "segment_index": self._segment_counter,
                },
            )
            self._current_segment_id = None
            self._segment_chunk_count = 0
            self._segment_speech_duration_ms = 0.0
            self._segment_start_timestamp = None

        self.lifecycle.stop()
        self.buffer.clear()

    def handle_device_loss(self, error: Optional[AudioError] = None) -> AudioEvent:
        """
        Handle unexpected device disconnection or loss during active session (Week 3, D17).
        Safely transitions lifecycle, terminates any in-flight speech segment,
        emits DEVICE_LOST event, and ensures pipeline stability without crashing.
        Idempotent (Week 3, B11).
        """
        err = error or AudioError(
            message="Audio input device was unexpectedly disconnected or became unavailable.",
            code="DEVICE_UNAVAILABLE",
        )
        self.last_error = err

        # B11 (1 & 2): Idempotence check - do not emit duplicate DEVICE_LOST if already in ERROR
        if self.lifecycle.state == AudioLifecycleState.ERROR and self._last_device_lost_event is not None:
            return self._last_device_lost_event

        # B5 & B11 (6): If a speech segment was actively open, safely finalize it with device_loss reason
        if self._current_segment_id is not None:
            speech_dur_ms = round(self._segment_speech_duration_ms, 2) if self._segment_speech_duration_ms > 0 else (
                max(0.0, self._segment_chunk_count * 20.0)
            )
            last_ts = self._emitted_events[-1].timestamp if self._emitted_events else 0.0
            self._emit_event(
                event_type=AudioEventType.SPEECH_END,
                timestamp=last_ts,
                chunk=None,
                segment_id=self._current_segment_id,
                metadata={
                    "speech_duration_ms": speech_dur_ms,
                    "total_speech_chunks": self._segment_chunk_count,
                    "reason": "device_loss",
                    "segment_index": self._segment_counter,
                },
            )
            self._current_segment_id = None
            self._segment_chunk_count = 0
            self._segment_speech_duration_ms = 0.0
            self._segment_start_timestamp = None

        # B5: Reset active VAD state on device loss
        self.vad.reset()

        # Transition lifecycle controller safely
        self.lifecycle.handle_device_loss(err)

        # Emit normalized DEVICE_LOST event
        last_ts = self._emitted_events[-1].timestamp if self._emitted_events else 0.0
        loss_evt = self._emit_event(
            event_type=AudioEventType.DEVICE_LOST,
            timestamp=last_ts,
            chunk=None,
            segment_id=None,
            metadata={
                "error_code": err.code,
                "error_message": err.message,
                "session_id": self.session_id,
                "correlation_id": self.correlation_id,
            },
        )
        self._last_device_lost_event = loss_evt
        return loss_evt

    def reconnect_device(self, device_id: Optional[str] = None, resume_capture: bool = True) -> bool:
        """
        Restore device connection and resume capture if supported (Week 3, D18).
        """
        # B6: A cancelled session must remain cancelled! Reconnection must never reactivate it.
        if self._is_cancelled:
            logger.warning("reconnect_device: cannot reconnect on a cancelled session; session remains cancelled.")
            return False

        # B11 (3): Reconnecting an already-connected healthy device must not emit a false DEVICE_RECONNECTED event
        if getattr(self.device, "is_connected", True) and getattr(self.device, "is_open", False) and self.lifecycle.state == AudioLifecycleState.RUNNING:
            return True

        success = self.device.reconnect(device_id)
        if not success:
            err = AudioError(
                message="Audio device reconnection failed: device unavailable or unsupported.",
                code="DEVICE_RECONNECT_FAILED",
            )
            self.last_error = err
            return False

        self.last_error = None
        self._last_device_lost_event = None

        # B5: Reset VAD state during valid reconnection so stale segment IDs are not reused
        self.vad.reset()
        self._current_segment_id = None
        self._segment_chunk_count = 0
        self._segment_speech_duration_ms = 0.0
        self._segment_start_timestamp = None

        # Emit DEVICE_RECONNECTED event
        dev_info = self.device.selected_device
        last_ts = self._emitted_events[-1].timestamp if self._emitted_events else 0.0
        self._emit_event(
            event_type=AudioEventType.DEVICE_RECONNECTED,
            timestamp=last_ts,
            chunk=None,
            segment_id=None,
            metadata={
                "device_id": dev_info.device_id if dev_info else None,
                "device_name": dev_info.name if dev_info else None,
                "resumed": resume_capture,
            },
        )

        # B15: Use lifecycle method handle_device_reconnected
        self.buffer.clear()
        self.buffer.reset_metrics()
        return self.lifecycle.handle_device_reconnected(resume_capture=resume_capture)

    def cancel(self, reason: str = "user_cancelled") -> AudioEvent:
        """
        Immediately cancel active audio capture session and release all buffers (Week 3, D18).
        Safe and idempotent.
        """
        if self._is_cancelled and self._last_cancelled_event is not None:
            return self._last_cancelled_event

        if self._current_segment_id is not None:
            speech_dur_ms = round(self._segment_speech_duration_ms, 2) if self._segment_speech_duration_ms > 0 else (
                max(0.0, self._segment_chunk_count * 20.0)
            )
            last_ts = self._emitted_events[-1].timestamp if self._emitted_events else 0.0
            self._emit_event(
                event_type=AudioEventType.SPEECH_END,
                timestamp=last_ts,
                chunk=None,
                segment_id=self._current_segment_id,
                metadata={
                    "speech_duration_ms": speech_dur_ms,
                    "total_speech_chunks": self._segment_chunk_count,
                    "reason": "cancelled",
                    "segment_index": self._segment_counter,
                },
            )
            self._current_segment_id = None
            self._segment_chunk_count = 0
            self._segment_speech_duration_ms = 0.0
            self._segment_start_timestamp = None

        # B15: Use lifecycle method cancel
        self.lifecycle.cancel(reason=reason)
        self.buffer.clear()
        self.vad.reset()
        self._is_cancelled = True

        last_ts = self._emitted_events[-1].timestamp if self._emitted_events else 0.0
        cancel_evt = self._emit_event(
            event_type=AudioEventType.CANCELLED,
            timestamp=last_ts,
            chunk=None,
            segment_id=None,
            metadata={"reason": reason, "session_id": self.session_id},
        )
        self._last_cancelled_event = cancel_evt
        return cancel_evt

    def _process_chunk_vad_events(self, dequeued: AudioChunk) -> Tuple[VADEvent, List[AudioEvent]]:
        """Evaluate an AudioChunk through VAD and generate normalized events."""
        vad_event = self.vad.process_chunk(dequeued)
        step_events: List[AudioEvent] = []

        if vad_event.event_type == VADEventType.SPEECH_START:
            self._in_silence = False
            # Beginning of speech segment:
            if self._current_segment_id is None:
                self._segment_counter += 1
                self._current_segment_id = f"seg-{self.session_id}-{self._segment_counter}"
                self._segment_start_timestamp = vad_event.timestamp
                self._segment_chunk_count = 1
                self._segment_speech_duration_ms = dequeued.duration_ms

                # 1. Emit SPEECH_START event with true onset timestamp and metadata
                start_evt = self._emit_event(
                    event_type=AudioEventType.SPEECH_START,
                    timestamp=vad_event.timestamp,
                    chunk=dequeued,
                    segment_id=self._current_segment_id,
                    metadata={
                        "onset_sequence_id": vad_event.onset_sequence_id,
                        "energy": round(vad_event.energy, 4),
                        "speech_probability": round(vad_event.speech_probability, 4),
                        "segment_index": self._segment_counter,
                    },
                )
                step_events.append(start_evt)

            # 2. Emit normalized AUDIO_CHUNK event
            chunk_evt = self._emit_event(
                event_type=AudioEventType.AUDIO_CHUNK,
                timestamp=dequeued.timestamp,
                chunk=dequeued,
                segment_id=self._current_segment_id,
                metadata={
                    "is_speech": True,
                    "energy": round(vad_event.energy, 4),
                    "speech_probability": round(vad_event.speech_probability, 4),
                    "chunk_sequence_id": dequeued.sequence_id,
                    "duration_ms": dequeued.duration_ms,
                },
            )
            step_events.append(chunk_evt)

        elif vad_event.event_type == VADEventType.SPEECH_ONGOING:
            self._in_silence = False
            # Continuous speech in an existing segment:
            # Invariant: NO duplicate SPEECH_START is emitted!
            if self._current_segment_id is None:
                self._segment_counter += 1
                self._current_segment_id = f"seg-{self.session_id}-{self._segment_counter}"
                self._segment_start_timestamp = vad_event.timestamp
                self._segment_speech_duration_ms = 0.0
            self._segment_chunk_count += 1
            self._segment_speech_duration_ms += dequeued.duration_ms

            chunk_evt = self._emit_event(
                event_type=AudioEventType.AUDIO_CHUNK,
                timestamp=dequeued.timestamp,
                chunk=dequeued,
                segment_id=self._current_segment_id,
                metadata={
                    "is_speech": True,
                    "energy": round(vad_event.energy, 4),
                    "speech_probability": round(vad_event.speech_probability, 4),
                    "chunk_sequence_id": dequeued.sequence_id,
                    "duration_ms": dequeued.duration_ms,
                },
            )
            step_events.append(chunk_evt)

        elif vad_event.event_type == VADEventType.SPEECH_END:
            # Speech offset reached after debounce:
            # 1. Emit the final AUDIO_CHUNK of this transition
            chunk_evt = self._emit_event(
                event_type=AudioEventType.AUDIO_CHUNK,
                timestamp=dequeued.timestamp,
                chunk=dequeued,
                segment_id=self._current_segment_id,
                metadata={
                    "is_speech": False,
                    "energy": round(vad_event.energy, 4),
                    "speech_probability": round(vad_event.speech_probability, 4),
                    "chunk_sequence_id": dequeued.sequence_id,
                    "duration_ms": dequeued.duration_ms,
                },
            )
            step_events.append(chunk_evt)

            # 2. Emit SPEECH_END event if a segment was open (chunk=None to prevent duplicate STT input - B7)
            if self._current_segment_id is not None:
                start_t = self._segment_start_timestamp if self._segment_start_timestamp is not None else dequeued.timestamp
                speech_dur_ms = max(0.0, (dequeued.timestamp + dequeued.duration_seconds - start_t) * 1000.0)
                end_evt = self._emit_event(
                    event_type=AudioEventType.SPEECH_END,
                    timestamp=dequeued.timestamp + dequeued.duration_seconds,
                    chunk=None,
                    segment_id=self._current_segment_id,
                    metadata={
                        "speech_duration_ms": round(speech_dur_ms, 2),
                        "total_speech_chunks": self._segment_chunk_count,
                        "offset_sequence_id": dequeued.sequence_id,
                        "energy": round(vad_event.energy, 4),
                        "segment_index": self._segment_counter,
                    },
                )
                step_events.append(end_evt)
                self._current_segment_id = None
                self._segment_chunk_count = 0
                self._segment_speech_duration_ms = 0.0
                self._segment_start_timestamp = None
                self._in_silence = False

        else:
            # Silence (vad_event.event_type == VADEventType.SILENCE)
            # Emit SILENCE event on transition to silence (Week 3, B8)
            if not self._in_silence:
                self._in_silence = True
                silence_evt = self._emit_event(
                    event_type=AudioEventType.SILENCE,
                    timestamp=dequeued.timestamp,
                    chunk=None,
                    segment_id=None,
                    metadata={
                        "energy": round(vad_event.energy, 4),
                        "speech_probability": round(vad_event.speech_probability, 4),
                        "sequence_id": dequeued.sequence_id,
                    },
                )
                step_events.append(silence_evt)

            chunk_evt = self._emit_event(
                event_type=AudioEventType.AUDIO_CHUNK,
                timestamp=dequeued.timestamp,
                chunk=dequeued,
                segment_id=None,
                metadata={
                    "is_speech": False,
                    "energy": round(vad_event.energy, 4),
                    "speech_probability": round(vad_event.speech_probability, 4),
                    "chunk_sequence_id": dequeued.sequence_id,
                    "duration_ms": dequeued.duration_ms,
                },
            )
            step_events.append(chunk_evt)

        return vad_event, step_events

    def process_step(self) -> Optional[Tuple[AudioChunk, VADEvent]]:
        """
        Execute a single capture-enqueue-dequeue-VAD pipeline step:
        1. Validates RUNNING lifecycle state (and checks cancellation).
        2. Captures raw chunk from active device through lifecycle controller,
           safely catching device disconnections and permission revocation without crashing.
        3. Pushes chunk to bounded buffer (handling backpressure if full).
        4. Consumes oldest chunk from buffer in FIFO order (ensures buffer drains even during drops).
        5. Evaluates chunk with VAD to produce speech/silence event.
        6. Emits normalized AudioEvents (SPEECH_START, AUDIO_CHUNK, SPEECH_END, SILENCE).
        7. Returns (AudioChunk, VADEvent) for backward compatibility.
        """
        if self._is_cancelled:
            return None

        if self.lifecycle.state != AudioLifecycleState.RUNNING:
            return None

        # 1. Capture via lifecycle controller (safely catch device loss & permission revocation errors - B11)
        try:
            chunk = self.lifecycle.read_chunk()
        except AudioError as exc:
            if exc.code in ("DEVICE_UNAVAILABLE", "DEVICE_LOST", "DEVICE_DISCONNECTED", "DEVICE_NOT_OPEN", "PERMISSION_DENIED"):
                self.handle_device_loss(exc)
                return None
            raise

        if chunk is None:
            return None

        # 2. Push to bounded buffer (drops if capacity exceeded, records drop metrics)
        self.last_push_result = self.buffer.push(chunk)

        # 3. Dequeue oldest chunk from buffer (prevents starvation when buffer is full)
        dequeued = self.buffer.pop()
        if dequeued is None:
            return None

        # 4. Process through VAD and emit normalized events
        vad_event, step_events = self._process_chunk_vad_events(dequeued)
        self._last_step_events = step_events

        pair = (dequeued, vad_event)
        self._processed_events.append(pair)
        return pair

    def process_chunk_direct(
        self,
        chunk: AudioChunk,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[AudioEvent]:
        """
        Directly process a single AudioChunk through VAD and normalized event generation.
        Allows custom or chunk-level session_id and correlation_id propagation (Week 3, D16).
        Blocks processing and returns empty list if session was cancelled (Week 3, D18).
        """
        if self._is_cancelled:
            return []

        eff_session_id = session_id or chunk.metadata.get("session_id") or self.session_id
        eff_corr_id = correlation_id or chunk.metadata.get("correlation_id") or self.correlation_id

        # Temporarily switch context to ensure correct session attribution
        prev_session = self.session_id
        prev_corr = self.correlation_id
        self.session_id = eff_session_id
        self.correlation_id = eff_corr_id
        try:
            _, step_events = self._process_chunk_vad_events(chunk)
            self._last_step_events = step_events
            return step_events
        finally:
            self.session_id = prev_session
            self.correlation_id = prev_corr

    def attach_transcription(
        self,
        transcriber: Optional[Any] = None,
        accumulator: Optional[Any] = None,
    ) -> Any:
        """
        Connect audio event stream to Transcription Module (Week 3, D19).
        """
        from src.audio.transcription_integration import AudioTranscriptionBridge
        bridge = AudioTranscriptionBridge(
            pipeline=self,
            transcriber=transcriber,
            accumulator=accumulator,
            auto_feed=True,
        )
        self._transcription_bridge = bridge
        return bridge

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
        """Aggregate high-level pipeline status, metrics, and event telemetry."""
        device_info = self.device.selected_device
        return {
            "lifecycle_state": self.lifecycle.state.value,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "active_segment_id": self._current_segment_id,
            "is_cancelled": self._is_cancelled,
            "last_error": str(self.last_error) if self.last_error else None,
            "total_events_emitted": len(self._emitted_events),
            "last_step_events_count": len(self._last_step_events),
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
    metadata: Optional[Dict[str, Any]] = None,
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
        metadata=dict(metadata) if metadata else {},
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

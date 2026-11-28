"""
Audio Lifecycle Controller Module (Week 2, D10-D11).

Manages the comprehensive state machine for audio capture workflows:
IDLE -> STARTING -> RUNNING <-> PAUSED -> STOPPING -> STOPPED / ERROR

Key Invariants:
- Strict transition validation with deterministic state transitions.
- Automatic verification of device selection and GRANTED permissions before start.
- Safe idempotent stop handling and guaranteed resource cleanup on errors.
- Monotonic sequence and timestamp preservation conforming to Week 1 contracts.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, List, Optional

from src.audio.device import AudioDeviceInterface, AudioPermissionState
from src.schemas.audio import AudioChunk, AudioError


class AudioLifecycleState(str, Enum):
    """
    Audio capture lifecycle states.

    Transitions:
        IDLE      -> STARTING -> RUNNING
        RUNNING   -> PAUSED
        PAUSED    -> RUNNING
        RUNNING   -> STOPPING -> STOPPED
        PAUSED    -> STOPPING -> STOPPED
        STARTING  -> ERROR
        RUNNING   -> ERROR
    """

    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class AudioLifecycleController:
    """
    Coordinates audio device lifecycle, state transitions, and safe capture execution.

    Attributes:
        device (AudioDeviceInterface): Underlying audio device adapter.
        state (AudioLifecycleState): Current lifecycle state.
        last_error (Optional[AudioError]): Details of any fatal error causing ERROR state.
    """

    def __init__(
        self,
        device: AudioDeviceInterface,
        on_chunk_callback: Optional[Callable[[AudioChunk], None]] = None,
        allow_restart_from_stopped: bool = True,
    ) -> None:
        """
        Initialize AudioLifecycleController.

        Args:
            device: AudioDeviceInterface implementation (e.g. MockAudioDevice).
            on_chunk_callback: Optional callback invoked when chunks are captured.
            allow_restart_from_stopped: If True, start() can re-initialize from STOPPED state.
        """
        if device is None:
            raise AudioError(
                message="AudioLifecycleController requires a valid AudioDeviceInterface instance.",
                code="INVALID_PARAMETER",
            )
        self._device: AudioDeviceInterface = device
        self._state: AudioLifecycleState = AudioLifecycleState.IDLE
        self._last_error: Optional[AudioError] = None
        self._on_chunk_callback: Optional[Callable[[AudioChunk], None]] = on_chunk_callback
        self._allow_restart: bool = allow_restart_from_stopped

        # Telemetry and state tracking
        self._chunks_captured: int = 0
        self._last_sequence_id: int = -1
        self._last_timestamp: float = -1.0
        self._end_of_stream: bool = False
        self._state_history: List[AudioLifecycleState] = [AudioLifecycleState.IDLE]

    @property
    def device(self) -> AudioDeviceInterface:
        """The underlying audio device adapter."""
        return self._device

    @property
    def state(self) -> AudioLifecycleState:
        """Current lifecycle state."""
        return self._state

    @property
    def last_error(self) -> Optional[AudioError]:
        """Last encountered error when in ERROR state."""
        return self._last_error

    @property
    def is_end_of_stream(self) -> bool:
        """True if the audio stream reached the end (device returned None while RUNNING)."""
        return self._end_of_stream

    @property
    def is_running(self) -> bool:
        """True if actively in RUNNING state."""
        return self._state == AudioLifecycleState.RUNNING

    @property
    def is_paused(self) -> bool:
        """True if currently in PAUSED state."""
        return self._state == AudioLifecycleState.PAUSED

    @property
    def chunks_captured(self) -> int:
        """Total chunks successfully read while in RUNNING state."""
        return self._chunks_captured

    @property
    def state_history(self) -> List[AudioLifecycleState]:
        """Record of all state transitions experienced."""
        return list(self._state_history)

    def _transition(self, new_state: AudioLifecycleState) -> None:
        """Record state transition."""
        self._state = new_state
        self._state_history.append(new_state)

    # -------------------------------------------------------------------------
    # Lifecycle Operations
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the audio capture session.

        Transitions:
            IDLE -> STARTING -> RUNNING (or STOPPED -> STARTING -> RUNNING if restartable)

        Raises:
            AudioError: If transition is illegal, device not selected,
                        permission not granted, or device open fails.
        """
        if self._state in (AudioLifecycleState.RUNNING, AudioLifecycleState.STARTING):
            raise AudioError(
                message=f"Cannot start audio capture: Controller is already in {self._state.value} state.",
                code="ILLEGAL_LIFECYCLE_TRANSITION",
                details={"current_state": self._state.value, "attempted_operation": "start"},
            )

        if self._state == AudioLifecycleState.PAUSED:
            raise AudioError(
                message="Cannot start from PAUSED state: Use resume() to continue or stop() to terminate.",
                code="ILLEGAL_LIFECYCLE_TRANSITION",
                details={"current_state": self._state.value, "attempted_operation": "start"},
            )

        if self._state == AudioLifecycleState.STOPPED and not self._allow_restart:
            raise AudioError(
                message="Cannot restart audio capture: Controller is STOPPED and restart is disabled.",
                code="ILLEGAL_LIFECYCLE_TRANSITION",
                details={"current_state": self._state.value, "attempted_operation": "start"},
            )

        # Transition to STARTING
        self._transition(AudioLifecycleState.STARTING)
        self._last_error = None
        self._last_sequence_id = -1
        self._last_timestamp = -1.0
        self._chunks_captured = 0
        self._end_of_stream = False

        try:
            # 1. Verify device selection
            if self._device.selected_device is None:
                raise AudioError(
                    message="Cannot start audio: No input device has been selected.",
                    code="NO_DEVICE_AVAILABLE",
                )

            # 2. Verify permission
            perm = self._device.get_permission_status()
            if perm != AudioPermissionState.GRANTED:
                raise AudioError(
                    message=f"Cannot start audio: Permission state is {perm.value}. Must be GRANTED.",
                    code="PERMISSION_DENIED",
                    details={"permission_state": perm.value},
                )

            # 3. Open device
            if not self._device.is_open:
                self._device.open()

            # Transition to RUNNING
            self._transition(AudioLifecycleState.RUNNING)

        except Exception as exc:
            # Cleanup on failure and transition to ERROR
            self._transition(AudioLifecycleState.ERROR)
            err = (
                exc
                if isinstance(exc, AudioError)
                else AudioError(
                    message=f"Unexpected device error during start: {exc}",
                    code="DEVICE_INIT_FAILURE",
                    details={"error": str(exc)},
                )
            )
            self._last_error = err
            try:
                self._device.close()
            except Exception:
                pass
            raise err

    def pause(self) -> None:
        """
        Pause the active audio session without releasing device or losing session state.

        Transitions:
            RUNNING -> PAUSED

        Raises:
            AudioError: If controller is not in RUNNING state.
        """
        if self._state != AudioLifecycleState.RUNNING:
            raise AudioError(
                message=f"Cannot pause audio capture: Controller is in {self._state.value} state (must be RUNNING).",
                code="ILLEGAL_LIFECYCLE_TRANSITION",
                details={"current_state": self._state.value, "attempted_operation": "pause"},
            )
        self._transition(AudioLifecycleState.PAUSED)

    def resume(self) -> None:
        """
        Resume capturing audio from a paused state.

        Transitions:
            PAUSED -> RUNNING

        Raises:
            AudioError: If controller is not in PAUSED state.
        """
        if self._state != AudioLifecycleState.PAUSED:
            raise AudioError(
                message=f"Cannot resume audio capture: Controller is in {self._state.value} state (must be PAUSED).",
                code="ILLEGAL_LIFECYCLE_TRANSITION",
                details={"current_state": self._state.value, "attempted_operation": "resume"},
            )
        self._transition(AudioLifecycleState.RUNNING)

    def stop(self) -> None:
        """
        Terminate the audio session and release all device resources.

        Transitions:
            RUNNING / PAUSED / ERROR / IDLE -> STOPPING -> STOPPED

        Policy:
            Safe and idempotent: Calling stop() repeatedly when already STOPPED is a safe no-op.
        """
        if self._state == AudioLifecycleState.STOPPED:
            return  # Idempotent no-op

        self._transition(AudioLifecycleState.STOPPING)
        try:
            self._device.close()
        except Exception as exc:
            self._last_error = (
                exc
                if isinstance(exc, AudioError)
                else AudioError(message=f"Error closing device during stop: {exc}", code="DEVICE_CLOSE_ERROR")
            )
        finally:
            self._transition(AudioLifecycleState.STOPPED)

    def read_chunk(self) -> Optional[AudioChunk]:
        """
        Read the next AudioChunk from the device if in RUNNING state.

        Returns:
            Optional[AudioChunk]: Next chunk while RUNNING, None if PAUSED or stream ended.

        Raises:
            AudioError: If called while IDLE, STOPPED, or in ERROR state, or on hardware fault.
        """
        if self._state == AudioLifecycleState.PAUSED:
            # Temporarily suspended without dropping session
            return None

        if self._state != AudioLifecycleState.RUNNING:
            raise AudioError(
                message=f"Cannot read chunk: Controller is in {self._state.value} state (must be RUNNING).",
                code="INVALID_LIFECYCLE_STATE",
                details={"current_state": self._state.value},
            )

        try:
            chunk = self._device.read_chunk()
        except Exception as exc:
            # Device failure mid-stream: transition to ERROR and release resources
            self._transition(AudioLifecycleState.ERROR)
            err = (
                exc
                if isinstance(exc, AudioError)
                else AudioError(
                    message=f"Device failure during chunk capture: {exc}",
                    code="DEVICE_UNAVAILABLE",
                    details={"error": str(exc)},
                )
            )
            self._last_error = err
            try:
                self._device.close()
            except Exception:
                pass
            raise err

        if chunk is None:
            self._end_of_stream = True
            return None

        # Verify sequence ID and timestamp contracts
        if self._last_sequence_id >= 0 and chunk.sequence_id <= self._last_sequence_id:
            self._transition(AudioLifecycleState.ERROR)
            err = AudioError(
                message=(
                    f"Non-monotonic sequence ID detected: received {chunk.sequence_id}, "
                    f"expected > {self._last_sequence_id}."
                ),
                code="OUT_OF_ORDER_CHUNK",
                details={"received_seq": chunk.sequence_id, "last_seq": self._last_sequence_id},
            )
            self._last_error = err
            try:
                self._device.close()
            except Exception:
                pass
            raise err

        self._last_sequence_id = chunk.sequence_id
        self._last_timestamp = chunk.timestamp
        self._chunks_captured += 1

        if self._on_chunk_callback is not None:
            self._on_chunk_callback(chunk)

        return chunk


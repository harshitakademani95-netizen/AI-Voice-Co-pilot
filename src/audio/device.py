"""
Audio Device Abstraction and Permission Management Module (Week 2, D8-D9).

This module defines the abstract interface for audio devices and provides a deterministic
MockAudioDevice implementation for testing and development without physical microphone hardware.

Contracts:
- Conforms to existing Week 1 schemas (AudioFormat, AudioChunk, AudioError).
- Explicit permission state lifecycle: UNKNOWN -> REQUESTED -> GRANTED / DENIED / UNSUPPORTED.
- Robust error handling with clean resource teardown on failure.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.audio.mock_source import MockMicrophone
from src.schemas.audio import AudioChunk, AudioError, AudioFormat


class AudioPermissionState(str, Enum):
    """
    Audio capture permission states.

    States:
        UNKNOWN: Permission has not been requested yet.
        REQUESTED: Permission request is pending or in progress.
        GRANTED: User/system granted audio capture permission.
        DENIED: Permission was explicitly refused or blocked.
        UNSUPPORTED: Platform or device does not support audio capture permissions.
    """

    UNKNOWN = "UNKNOWN"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class AudioDeviceInfo:
    """
    Metadata representation of an audio input device.

    Attributes:
        device_id (str): Unique hardware/mock device identifier.
        name (str): Human-readable device label.
        channels (int): Supported input channel count (1=mono, 2=stereo).
        sample_rate (int): Nominal sample rate in Hz (e.g. 16000, 48000).
        is_default (bool): Whether this device is the system default.
        is_mock (bool): True if this is a synthetic simulation device.
        supported (bool): True if the device hardware is supported on this platform.
    """

    device_id: str
    name: str
    channels: int = 1
    sample_rate: int = 16000
    is_default: bool = False
    is_mock: bool = True
    supported: bool = True

    def __post_init__(self) -> None:
        if not self.device_id or not isinstance(self.device_id, str):
            raise AudioError(
                message="device_id must be a non-empty string.",
                code="INVALID_PARAMETER",
                details={"device_id": self.device_id},
            )
        if not self.name or not isinstance(self.name, str):
            raise AudioError(
                message="device name must be a non-empty string.",
                code="INVALID_PARAMETER",
                details={"name": self.name},
            )
        if self.channels not in (1, 2):
            raise AudioError(
                message=f"channels must be 1 or 2 (received: {self.channels}).",
                code="INVALID_CHANNELS",
                details={"channels": self.channels},
            )
        if self.sample_rate <= 0:
            raise AudioError(
                message=f"sample_rate must be positive (received: {self.sample_rate}).",
                code="INVALID_SAMPLE_RATE",
                details={"sample_rate": self.sample_rate},
            )


class AudioDeviceInterface(abc.ABC):
    """
    Abstract interface for audio capture devices.

    Decouples higher-level audio controllers and buffers from physical hardware or mock sources.
    Ready for future production integration (e.g. PyAudio, sounddevice) while allowing 100%
    deterministic offline simulation.
    """

    @abc.abstractmethod
    def list_devices(self) -> List[AudioDeviceInfo]:
        """List all discoverable audio input devices."""
        raise NotImplementedError

    @abc.abstractmethod
    def select_device(self, device_id: str) -> AudioDeviceInfo:
        """
        Select an audio input device by its device_id.

        Args:
            device_id (str): The unique ID of the target device.

        Returns:
            AudioDeviceInfo: Metadata of the selected device.

        Raises:
            AudioError: If device_id is invalid or device is unsupported.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def request_permission(
        self,
        auto_resolve: bool = True,
        pending_callback: Optional[Callable[[AudioPermissionState], None]] = None,
    ) -> AudioPermissionState:
        """
        Request audio capture permission from the user/OS.

        Returns:
            AudioPermissionState: Resulting permission status.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def resolve_permission(
        self,
        state: Optional[AudioPermissionState] = None,
    ) -> AudioPermissionState:
        """
        Resolve a pending permission request.

        Returns:
            AudioPermissionState: Resulting permission status.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_permission_status(self) -> AudioPermissionState:
        """
        Query current permission status without prompting.

        Returns:
            AudioPermissionState: Current permission status.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def open(self) -> None:
        """
        Initialize and open the selected audio device.

        Raises:
            AudioError: If permission is not GRANTED, no device is selected,
                        or device initialization fails.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """
        Close the audio device and release all hardware/stream resources.
        Must be safe to call repeatedly (idempotent).
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def is_open(self) -> bool:
        """True if the audio device is actively open and ready to emit chunks."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def selected_device(self) -> Optional[AudioDeviceInfo]:
        """Currently selected device metadata, or None if no device selected."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_chunk(self) -> Optional[AudioChunk]:
        """
        Read the next discrete AudioChunk from the device.

        Returns:
            Optional[AudioChunk]: Synthesized/captured chunk, or None if stream ended.

        Raises:
            AudioError: If device is not open or an IO error occurs during capture.
        """
        raise NotImplementedError


class MockAudioDevice(AudioDeviceInterface):
    """
    Deterministic mock audio device implementation.

    Employs the Week 1 MockMicrophone under the hood to emit byte-for-byte reproducible
    AudioChunks conforming strictly to the AudioFormat and AudioChunk contracts.
    """

    DEFAULT_DEVICES = [
        AudioDeviceInfo(
            device_id="mock-mic-default",
            name="Mock Studio Microphone (Synthetic Default)",
            channels=1,
            sample_rate=16000,
            is_default=True,
            is_mock=True,
        ),
        AudioDeviceInfo(
            device_id="mock-mic-headset",
            name="Mock Voice Headset (Synthetic)",
            channels=1,
            sample_rate=16000,
            is_default=False,
            is_mock=True,
        ),
        AudioDeviceInfo(
            device_id="mock-mic-stereo",
            name="Mock High-Res Stereo Array",
            channels=2,
            sample_rate=48000,
            is_default=False,
            is_mock=True,
        ),
    ]

    def __init__(
        self,
        devices: Optional[List[AudioDeviceInfo]] = None,
        default_device_id: Optional[str] = "mock-mic-default",
        initial_permission: AudioPermissionState = AudioPermissionState.UNKNOWN,
        permission_response: AudioPermissionState = AudioPermissionState.GRANTED,
        audio_format: Optional[AudioFormat] = None,
        chunk_duration_ms: float = 20.0,
        frequency_hz: float = 440.0,
        amplitude: float = 0.5,
        total_duration_sec: Optional[float] = 1.0,
        simulate_init_failure: bool = False,
        simulate_disconnect_after_chunks: Optional[int] = None,
    ) -> None:
        """
        Initialize MockAudioDevice.

        Args:
            devices: Custom device inventory. Defaults to DEFAULT_DEVICES.
            default_device_id: Pre-selected device ID (or None).
            initial_permission: Starting permission state (default: UNKNOWN).
            permission_response: State to transition to when request_permission() is invoked.
            audio_format: Desired audio format.
            chunk_duration_ms: Chunk duration in milliseconds (default: 20.0 ms).
            frequency_hz: Synthetic tone frequency.
            amplitude: Signal amplitude.
            total_duration_sec: Bounded stream duration limit.
            simulate_init_failure: If True, open() will fail with DEVICE_INIT_FAILURE.
            simulate_disconnect_after_chunks: If set, raises DEVICE_UNAVAILABLE after N chunks.
        """
        self._devices: List[AudioDeviceInfo] = (
            list(devices) if devices is not None else list(self.DEFAULT_DEVICES)
        )
        self._selected_device: Optional[AudioDeviceInfo] = None
        self._permission_state: AudioPermissionState = initial_permission
        self._permission_response: AudioPermissionState = permission_response

        self._audio_format: Optional[AudioFormat] = audio_format
        self._chunk_duration_ms: float = float(chunk_duration_ms)
        self._frequency_hz: float = float(frequency_hz)
        self._amplitude: float = float(amplitude)
        self._total_duration_sec: Optional[float] = total_duration_sec

        self._simulate_init_failure: bool = simulate_init_failure
        self._simulate_disconnect_after_chunks: Optional[int] = simulate_disconnect_after_chunks
        self._chunks_emitted: int = 0

        self._is_open: bool = False
        self._mock_mic: Optional[MockMicrophone] = None

        # Pre-select default device if available and supported
        if default_device_id is not None:
            for dev in self._devices:
                if dev.device_id == default_device_id:
                    if dev.supported:
                        self._selected_device = dev
                    break

    # -------------------------------------------------------------------------
    # Device discovery and selection
    # -------------------------------------------------------------------------

    def list_devices(self) -> List[AudioDeviceInfo]:
        """Return list of all configured mock devices."""
        return list(self._devices)

    def select_device(self, device_id: str) -> AudioDeviceInfo:
        """
        Select an audio input device by its device_id.

        Raises:
            AudioError: If device_id is invalid, device not found, or device is unsupported.
        """
        if not device_id or not isinstance(device_id, str):
            raise AudioError(
                message="Device ID must be a valid non-empty string.",
                code="INVALID_DEVICE_SELECTION",
                details={"device_id": device_id},
            )

        if not self._devices:
            raise AudioError(
                message="No audio input devices are available in the system.",
                code="NO_DEVICE_AVAILABLE",
                details={"requested_device_id": device_id},
            )

        target: Optional[AudioDeviceInfo] = None
        for dev in self._devices:
            if dev.device_id == device_id:
                target = dev
                break

        if target is None:
            raise AudioError(
                message=f"Device with ID '{device_id}' was not found in available devices.",
                code="INVALID_DEVICE_SELECTION",
                details={"device_id": device_id, "available": [d.device_id for d in self._devices]},
            )

        # Refuse to switch devices while currently open
        if self._is_open and self._selected_device is not None and self._selected_device != target:
            raise AudioError(
                message="Cannot switch audio device while device is actively open. Close the device first.",
                code="DEVICE_BUSY",
                details={"current_device": self._selected_device.device_id, "target_device": target.device_id},
            )

        # Handle unsupported simulated hardware (via explicit supported flag)
        if not target.supported:
            raise AudioError(
                message=f"Audio device '{target.name}' ({target.device_id}) is not supported on this platform.",
                code="UNSUPPORTED_DEVICE",
                details={"device_id": target.device_id, "device_name": target.name},
            )

        self._selected_device = target
        return self._selected_device

    # -------------------------------------------------------------------------
    # Permission management
    # -------------------------------------------------------------------------

    def request_permission(
        self,
        auto_resolve: bool = True,
        pending_callback: Optional[Callable[[AudioPermissionState], None]] = None,
    ) -> AudioPermissionState:
        """
        Request microphone access permission.
        
        If auto_resolve is False, transitions to and holds REQUESTED until resolve_permission() is invoked.
        If pending_callback is supplied, it is invoked while in the REQUESTED state.
        """
        self._permission_state = AudioPermissionState.REQUESTED
        if pending_callback is not None:
            pending_callback(AudioPermissionState.REQUESTED)

        if not auto_resolve:
            return self._permission_state

        self._permission_state = self._permission_response
        return self._permission_state

    def resolve_permission(
        self,
        state: Optional[AudioPermissionState] = None,
    ) -> AudioPermissionState:
        """Resolve a pending permission request to GRANTED, DENIED, etc."""
        if state is not None:
            self._permission_state = state
        else:
            self._permission_state = self._permission_response
        return self._permission_state

    def get_permission_status(self) -> AudioPermissionState:
        """Return current permission status."""
        return self._permission_state

    def set_permission_state(self, state: AudioPermissionState) -> None:
        """Manual control for testing explicit permission changes."""
        self._permission_state = state

    # -------------------------------------------------------------------------
    # Lifecycle: Open, Close, and Streaming
    # -------------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """True if the mock device is open and active."""
        return self._is_open

    @property
    def selected_device(self) -> Optional[AudioDeviceInfo]:
        """Currently selected AudioDeviceInfo or None."""
        return self._selected_device

    def open(self) -> None:
        """
        Open the selected audio device.

        Raises:
            AudioError: With codes NO_DEVICE_AVAILABLE, PERMISSION_DENIED,
                        or DEVICE_INIT_FAILURE.
        """
        if self._is_open:
            return  # Already open (idempotent)

        if self._selected_device is None:
            self._is_open = False
            raise AudioError(
                message="Cannot open audio device: No device has been selected.",
                code="NO_DEVICE_AVAILABLE",
            )

        if not self._selected_device.supported:
            self._is_open = False
            raise AudioError(
                message=f"Cannot open audio device: Device '{self._selected_device.name}' ({self._selected_device.device_id}) is not supported.",
                code="UNSUPPORTED_DEVICE",
                details={"device_id": self._selected_device.device_id},
            )

        if self._permission_state != AudioPermissionState.GRANTED:
            raise AudioError(
                message=(
                    f"Microphone permission not granted (current state: {self._permission_state.value}). "
                    "Call request_permission() and ensure GRANTED before opening device."
                ),
                code="PERMISSION_DENIED",
                details={"permission_state": self._permission_state.value},
            )

        if self._simulate_init_failure:
            # Clean up partially initialized resources on failure
            self._mock_mic = None
            self._is_open = False
            raise AudioError(
                message="Simulated hardware initialization failure occurred while opening audio device.",
                code="DEVICE_INIT_FAILURE",
                details={"device_id": self._selected_device.device_id},
            )

        # Validate format compatibility with selected device
        if self._audio_format is not None:
            if self._audio_format.channels != self._selected_device.channels:
                raise AudioError(
                    message=(
                        f"Audio format channels ({self._audio_format.channels}) do not match "
                        f"selected device '{self._selected_device.name}' ({self._selected_device.channels} channels)."
                    ),
                    code="INVALID_CHANNELS",
                    details={"format_channels": self._audio_format.channels, "device_channels": self._selected_device.channels},
                )
            if self._audio_format.sample_rate != self._selected_device.sample_rate:
                raise AudioError(
                    message=(
                        f"Audio format sample rate ({self._audio_format.sample_rate} Hz) does not match "
                        f"selected device '{self._selected_device.name}' ({self._selected_device.sample_rate} Hz)."
                    ),
                    code="INVALID_SAMPLE_RATE",
                    details={"format_rate": self._audio_format.sample_rate, "device_rate": self._selected_device.sample_rate},
                )

        # Prepare audio format compatible with selected device
        target_format = self._audio_format
        if target_format is None:
            target_format = AudioFormat(
                sample_rate=self._selected_device.sample_rate,
                channels=self._selected_device.channels,
                sample_width=2,
                encoding="pcm_s16le",
            )

        # Initialize underlying deterministic mock source
        try:
            self._mock_mic = MockMicrophone(
                audio_format=target_format,
                chunk_duration_ms=self._chunk_duration_ms,
                frequency_hz=self._frequency_hz,
                amplitude=self._amplitude,
                total_duration_sec=self._total_duration_sec,
            )
            self._chunks_emitted = 0
            self._is_open = True
        except Exception as exc:
            self._is_open = False
            self._mock_mic = None
            if isinstance(exc, AudioError):
                raise
            raise AudioError(
                message=f"Failed to initialize mock microphone stream: {exc}",
                code="DEVICE_INIT_FAILURE",
                details={"cause": str(exc)},
            ) from exc

    def close(self) -> None:
        """Close device and release all resources (idempotent)."""
        if self._mock_mic is not None:
            self._mock_mic.close()
            self._mock_mic = None
        self._is_open = False

    def read_chunk(self) -> Optional[AudioChunk]:
        """
        Read the next discrete AudioChunk from the mock audio device.

        Raises:
            AudioError: If device is not open (DEVICE_NOT_OPEN) or disconnects (DEVICE_UNAVAILABLE).
        """
        if not self._is_open or self._mock_mic is None:
            raise AudioError(
                message="Cannot read audio chunk: device is not open. Call open() first.",
                code="DEVICE_NOT_OPEN",
            )

        # Enforce permission continuously during active streaming
        if self._permission_state != AudioPermissionState.GRANTED:
            self.close()
            raise AudioError(
                message=f"Microphone permission revoked or not granted: current state is {self._permission_state.value}.",
                code="PERMISSION_DENIED",
                details={"permission_state": self._permission_state.value},
            )

        # Check for simulated device disconnection mid-stream
        if (
            self._simulate_disconnect_after_chunks is not None
            and self._chunks_emitted >= self._simulate_disconnect_after_chunks
        ):
            self.close()
            raise AudioError(
                message="Audio input device was unexpectedly disconnected or became unavailable.",
                code="DEVICE_UNAVAILABLE",
                details={"chunks_emitted_before_failure": self._chunks_emitted},
            )

        chunk = self._mock_mic.read_chunk()
        if chunk is not None:
            self._chunks_emitted += 1
            # Augment chunk metadata with hardware origin
            if self._selected_device:
                chunk.metadata["device_id"] = self._selected_device.device_id
                chunk.metadata["device_name"] = self._selected_device.name
        return chunk


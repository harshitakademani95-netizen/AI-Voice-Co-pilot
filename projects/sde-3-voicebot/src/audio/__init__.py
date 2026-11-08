"""
Audio Pipeline Components for AI Voice Copilot.

Week 1 & Week 2 Exports:
- AudioChunker: Deterministic chunking utility.
- MockMicrophone: Simulated microphone audio source.
- Device Adapter & Permissions :
    - AudioPermissionState
    - AudioDeviceInfo
    - AudioDeviceInterface
    - MockAudioDevice
- Lifecycle Controller :
    - AudioLifecycleState
    - AudioLifecycleController
- Voice Activity Detection :
    - VADEventType
    - VADConfig
    - VADEvent
    - VADInterface
    - MockVAD
- Bounded Audio Buffer:
    - BufferPushStatus
    - BufferPushResult
    - BufferMetrics
    - BoundedAudioBuffer
- Audio Pipeline & Fixtures :
    - AudioPipeline
    - create_deterministic_chunk
    - generate_speech_fixture
    - generate_silence_fixture
    - generate_noise_burst_fixture
"""

from src.audio.buffer import (
    BoundedAudioBuffer,
    BufferMetrics,
    BufferPushResult,
    BufferPushStatus,
)
from src.audio.chunker import AudioChunker
from src.audio.device import (
    AudioDeviceInfo,
    AudioDeviceInterface,
    AudioPermissionState,
    MockAudioDevice,
)
from src.audio.lifecycle import (
    AudioLifecycleController,
    AudioLifecycleState,
)
from src.audio.mock_source import MockMicrophone
from src.audio.pipeline import (
    AudioPipeline,
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.vad import (
    MockVAD,
    VADConfig,
    VADEvent,
    VADEventType,
    VADInterface,
)

__all__ = [
    # Week 1
    "AudioChunker",
    "MockMicrophone",
    # Week 2 - Device Adapter
    "AudioPermissionState",
    "AudioDeviceInfo",
    "AudioDeviceInterface",
    "MockAudioDevice",
    # Week 2 - Lifecycle
    "AudioLifecycleState",
    "AudioLifecycleController",
    # Week 2 - VAD
    "VADEventType",
    "VADConfig",
    "VADEvent",
    "VADInterface",
    "MockVAD",
    # Week 2 - Buffer
    "BufferPushStatus",
    "BufferPushResult",
    "BufferMetrics",
    "BoundedAudioBuffer",
    # Week 2 - Pipeline
    "AudioPipeline",
    "create_deterministic_chunk",
    "generate_speech_fixture",
    "generate_silence_fixture",
    "generate_noise_burst_fixture",
]

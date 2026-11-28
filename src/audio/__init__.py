"""
Audio Pipeline Components for AI Voice Copilot.

Exports:
- AudioChunker: Deterministic chunking utility.
- MockMicrophone: Simulated microphone audio source.
"""

from src.audio.chunker import AudioChunker
from src.audio.mock_source import MockMicrophone

__all__ = ["AudioChunker", "MockMicrophone"]

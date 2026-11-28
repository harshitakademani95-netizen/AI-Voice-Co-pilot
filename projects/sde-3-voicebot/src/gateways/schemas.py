"""Pydantic schemas for Gateway API requests and responses."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AudioProcessRequest(BaseModel):
    """Request payload for processing and chunking raw audio."""

    audio_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded raw audio bytes. If omitted or empty, error is raised unless raw bytes are passed.",
    )
    format: str = Field(default="LINEAR16", description="Audio format (LINEAR16, FLAC, MULAW, etc.)")
    sample_rate: int = Field(default=16000, description="Sampling rate in Hz (e.g. 16000, 44100)")
    chunk_duration_ms: Optional[float] = Field(default=20.0, description="Target duration of each chunk in ms")
    is_last: bool = Field(default=False, description="Whether this is the final audio chunk")


class TranscriptionProcessRequest(BaseModel):
    """Request payload for transcribing audio via Transcription Gateway."""

    audio_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded audio bytes for transcription.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session ID to associate with transcription accumulator.",
    )
    format: str = Field(default="LINEAR16", description="Audio format")
    is_last: bool = Field(default=False, description="Whether this is the final chunk of speech")


class SessionAudioIngestRequest(BaseModel):
    """Request payload for ingesting audio into an active session."""

    audio_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded audio bytes to ingest into session.",
    )
    format: str = Field(default="LINEAR16", description="Audio format")
    is_last: bool = Field(default=False, description="Whether this chunk concludes user utterance")
    correlation_id: Optional[str] = Field(
        default=None,
        description="Optional correlation ID for distributed tracing.",
    )

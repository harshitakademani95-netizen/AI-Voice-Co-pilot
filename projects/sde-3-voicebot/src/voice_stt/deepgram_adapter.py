"""Deepgram Speech-to-Text provider adapter implementing BaseSTTAdapter using httpx."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

import httpx

from voice_stt.adapter import (
    BaseSTTAdapter,
    STTAdapterConfig,
    STTAdapterState,
    STTAdapterStatus,
)
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)

logger = logging.getLogger("backend.voice_stt.deepgram")


class DeepgramSTTAdapter(BaseSTTAdapter):
    """Production-grade Deepgram Nova-2 speech-to-text adapter using httpx.
    
    Guarantees:
    - Never hardcodes API keys; requires valid secret configuration.
    - Uses configurable connection and read timeouts.
    - Supports mock transports (httpx.MockTransport) for offline testing without network/API keys.
    - Normalizes Deepgram JSON responses into unified TranscriptEvent schemas.
    """

    DEFAULT_API_URL = "https://api.deepgram.com/v1/listen"

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[STTAdapterConfig] = None,
        api_url: str = DEFAULT_API_URL,
        timeout_seconds: float = 10.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        super().__init__(config=config)
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DEEPGRAM_API_KEY must be provided or set in environment variables when using DeepgramSTTAdapter."
            )
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._client: Optional[httpx.Client] = None
        self._sequence_counter: int = 0

    def initialize(self, session_id: Optional[str] = None) -> None:
        """Initializes httpx client and session identifier."""
        self._session_id = session_id or f"dg-session-{uuid4().hex[:8]}"
        self._chunks_processed = 0
        self._events_emitted = 0
        self._sequence_counter = 0
        self._last_error = None

        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds, connect=5.0),
            transport=self.transport,
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "audio/raw",
            },
        )
        self._state = STTAdapterState.READY
        logger.info(f"DeepgramSTTAdapter initialized for session {self._session_id}.")

    def transcribe_chunk(
        self,
        audio_chunk: Union[AudioChunk, bytes],
        is_last: bool = False,
    ) -> List[TranscriptEvent]:
        """Submits audio bytes to Deepgram API and parses returned transcription."""
        if self._state == STTAdapterState.CLOSED:
            raise RuntimeError("Cannot transcribe chunk: DeepgramSTTAdapter is closed.")
        if self._state == STTAdapterState.UNINITIALIZED or self._client is None:
            self.initialize()

        raw_bytes = bytes(audio_chunk.data if hasattr(audio_chunk, "data") else audio_chunk)
        if len(raw_bytes) == 0:
            return []

        self._chunks_processed += 1
        self._state = STTAdapterState.PROCESSING

        params = {
            "model": self.config.model_name if self.config.model_name != "mock-stt-v1" else "nova-2",
            "language": self.config.language,
            "punctuate": str(self.config.punctuate).lower(),
            "interim_results": str(self.config.interim_results).lower(),
            "encoding": "linear16",
            "sample_rate": str(self.config.sample_rate),
            "channels": "1",
        }

        try:
            assert self._client is not None
            response = self._client.post(
                self.api_url,
                params=params,
                content=raw_bytes,
            )
            response.raise_for_status()
            data = response.json()
            events = self._parse_deepgram_response(data, is_last=is_last)
            self._state = STTAdapterState.READY
            return events

        except httpx.HTTPStatusError as err:
            self._state = STTAdapterState.ERROR
            error_detail = STTErrorDetail(
                code=f"DEEPGRAM_HTTP_{err.response.status_code}",
                message=f"Deepgram HTTP error: {err.response.text}",
                retryable=(err.response.status_code >= 500 or err.response.status_code == 429),
            )
            self._last_error = error_detail
            logger.error(f"Deepgram HTTP status error: {err.response.status_code}")
            raise RuntimeError(f"Deepgram API error ({err.response.status_code}): {err.response.text}") from err

        except (httpx.TimeoutException, httpx.NetworkError) as err:
            self._state = STTAdapterState.ERROR
            error_detail = STTErrorDetail(
                code="DEEPGRAM_NETWORK_TIMEOUT",
                message=f"Network error communicating with Deepgram: {str(err)}",
                retryable=True,
            )
            self._last_error = error_detail
            logger.error(f"Deepgram network/timeout error: {err}")
            raise RuntimeError(f"Deepgram network failure: {str(err)}") from err

        except Exception as err:
            self._state = STTAdapterState.ERROR
            self._last_error = STTErrorDetail(code="DEEPGRAM_UNKNOWN_ERROR", message=str(err), retryable=False)
            logger.error(f"Deepgram unexpected error: {err}")
            raise

    def _parse_deepgram_response(self, data: Dict[str, Any], is_last: bool = False) -> List[TranscriptEvent]:
        """Transforms raw Deepgram JSON into normalized TranscriptEvent instances."""
        events: List[TranscriptEvent] = []

        try:
            results = data.get("results", {})
            channels = results.get("channels", [{}])
            alt = channels[0].get("alternatives", [{}])[0] if channels else {}
            transcript_text = alt.get("transcript", "").strip()
            confidence = float(alt.get("confidence", 0.95))
            words_raw = alt.get("words", [])

            word_timings = [
                WordTiming(
                    word=w.get("word", ""),
                    start_time=float(w.get("start", 0.0)),
                    end_time=float(w.get("end", 0.0)),
                    confidence=float(w.get("confidence", 0.95)),
                )
                for w in words_raw
            ]

            start_t = float(alt.get("start", 0.0)) if "start" in alt else (word_timings[0].start_time if word_timings else 0.0)
            end_t = float(alt.get("end", 0.0)) if "end" in alt else (word_timings[-1].end_time if word_timings else 0.0)

            is_final = bool(data.get("is_final", is_last))

            if transcript_text or is_last:
                seg = TranscriptSegment(
                    text=transcript_text,
                    start_time=start_t,
                    end_time=end_t,
                    confidence=confidence,
                    is_final=is_final,
                    words=word_timings,
                )

                self._sequence_counter += 1
                ev = TranscriptEvent(
                    event_id=f"evt-dg-{uuid4().hex[:8]}",
                    event_type=TranscriptEventType.FINAL if is_final else TranscriptEventType.INTERIM,
                    sequence_number=self._sequence_counter,
                    timestamp=round(end_t, 3),
                    session_id=self._session_id,
                    segment=seg,
                )
                events.append(ev)
                self._events_emitted += 1

            if is_last:
                self._sequence_counter += 1
                end_ev = TranscriptEvent(
                    event_id=f"evt-dg-{uuid4().hex[:8]}",
                    event_type=TranscriptEventType.STREAM_COMPLETED,
                    sequence_number=self._sequence_counter,
                    timestamp=round(end_t, 3),
                    session_id=self._session_id,
                )
                events.append(end_ev)
                self._events_emitted += 1

        except Exception as exc:
            logger.warning(f"Error parsing Deepgram JSON response: {exc}")

        return events

    def reset(self) -> None:
        """Resets adapter state and sequence counters."""
        self._chunks_processed = 0
        self._events_emitted = 0
        self._sequence_counter = 0
        self._last_error = None
        self._state = STTAdapterState.READY

    def close(self) -> None:
        """Closes HTTP client connection pool."""
        self._state = STTAdapterState.CLOSED
        if self._client:
            self._client.close()
            self._client = None

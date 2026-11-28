"""Factory module for instantiating pluggable Speech-To-Text adapters."""
from __future__ import annotations

import os
from typing import Optional

import httpx

from voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.deepgram_adapter import DeepgramSTTAdapter


def get_stt_adapter(
    provider: Optional[str] = None,
    config: Optional[STTAdapterConfig] = None,
    api_key: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> BaseSTTAdapter:
    """Creates and returns the configured STT adapter.
    
    Supported providers:
    - 'mock' (default): Returns offline DeterministicFakeTranscriber.
    - 'deepgram': Returns DeepgramSTTAdapter (requires DEEPGRAM_API_KEY).
    
    Raises:
        ValueError: If provider is unsupported or required API credentials are missing.
    """
    chosen_provider = (provider or os.getenv("STT_PROVIDER", "mock")).strip().lower()

    if chosen_provider == "mock":
        return DeterministicFakeTranscriber(config=config)
    elif chosen_provider == "deepgram":
        key = api_key or os.getenv("DEEPGRAM_API_KEY")
        if not key:
            raise ValueError(
                "Configuration error: DEEPGRAM_API_KEY environment variable is required when STT_PROVIDER=deepgram."
            )
        return DeepgramSTTAdapter(
            api_key=key,
            config=config,
            transport=transport,
        )
    else:
        raise ValueError(
            f"Invalid STT_PROVIDER: '{chosen_provider}'. Permitted values are: ['deepgram', 'mock']."
        )

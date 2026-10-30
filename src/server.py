"""
FastAPI Localhost Web Server & Visualizer for AI Voice Copilot W1 Pipeline.

Provides:
- Web dashboard accessible at http://localhost:8000
- Real-time audio stream via Server-Sent Events (SSE)
- Live HTML5 Canvas waveform visualizer
- Schema and unit test runners
"""

from __future__ import annotations

import asyncio
import io
import json
import unittest
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from src.audio.mock_source import MockMicrophone
from src.schemas.audio import AudioError, AudioFormat

app = FastAPI(
    title="AI Voice Copilot - W1 Audio & VAD Foundation",
    description="Week 1 Audio Pipeline Interactive Visualizer and API",
    version="0.1.0",
)


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint adhering to SDD API specification."""
    return {
        "status": "healthy",
        "service": "AI Voice Copilot - Audio Pipeline",
        "workstream": "W1 - Audio and VAD",
        "version": "1.0.0",
    }


@app.get("/api/v1/stream")
async def stream_audio_events(
    sample_rate: int = Query(16000, description="Sample rate in Hz"),
    channels: int = Query(1, description="Channels: 1 for mono, 2 for stereo"),
    chunk_ms: float = Query(20.0, description="Chunk duration in ms"),
    frequency: float = Query(440.0, description="Tone frequency in Hz"),
    duration: float = Query(10.0, description="Max stream duration in seconds"),
    realtime: bool = Query(True, description="Paced real-time simulation"),
):
    """Stream real-time AudioChunk metadata and PCM waveform data via Server-Sent Events (SSE)."""
    try:
        audio_format = AudioFormat(sample_rate=sample_rate, channels=channels)
        mic = MockMicrophone(
            audio_format=audio_format,
            chunk_duration_ms=chunk_ms,
            frequency_hz=frequency,
            amplitude=0.7,
            total_duration_sec=duration,
        )
    except AudioError as err:
        return JSONResponse(status_code=400, content=err.to_dict())

    async def event_generator() -> AsyncGenerator[str, None]:
        chunk_interval = chunk_ms / 1000.0
        while mic.is_active:
            chunk = mic.read_chunk()
            if chunk is None:
                yield f"data: {json.dumps({'done': True})}\n\n"
                break

            # Convert PCM sample values into a downsampled list for the waveform canvas
            pcm_bytes = chunk.data
            # Sample a few amplitude values for canvas drawing
            samples = []
            step = max(2, len(pcm_bytes) // 32)
            for i in range(0, len(pcm_bytes) - 1, step):
                val = int.from_bytes(pcm_bytes[i : i + 2], byteorder="little", signed=True)
                samples.append(round(val / 32768.0, 3))

            chunk_payload = {
                "sequence_id": chunk.sequence_id,
                "timestamp": round(chunk.timestamp, 4),
                "size_bytes": chunk.size_bytes,
                "duration_ms": round(chunk.duration_ms, 1),
                "num_samples": chunk.num_samples,
                "sample_rate": chunk.format.sample_rate,
                "channels": chunk.format.channels,
                "encoding": chunk.format.encoding,
                "samples": samples,
            }
            yield f"data: {json.dumps(chunk_payload)}\n\n"

            if realtime:
                await asyncio.sleep(chunk_interval)
            else:
                await asyncio.sleep(0.001)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/v1/tests/run")
async def run_unit_tests():
    """Run the comprehensive unit test suite and return the structured report."""
    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)

    return {
        "tests_run": result.testsRun,
        "success": result.wasSuccessful(),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "output": stream.getvalue(),
    }


STATIC_HTML_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the premium dark-mode glassmorphic visualizer dashboard."""
    if STATIC_HTML_PATH.exists():
        html_content = STATIC_HTML_PATH.read_text(encoding="utf-8")
    else:
        html_content = "<h1>Dashboard HTML file not found</h1>"

    return HTMLResponse(
        content=html_content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def main():
    """Run FastAPI dev server on http://localhost:8000."""
    uvicorn.run("src.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()

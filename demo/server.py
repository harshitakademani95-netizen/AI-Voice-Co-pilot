#!/usr/bin/env python3
"""AI Voice Co-Pilot - Day 7 Localhost Web Demo & API Server.

Workstream: W2 - Speech-to-Text Pipeline Foundation
Author: Disha D K (SDE 3)

Provides:
- Interactive Browser Dashboard at http://localhost:8000
- API Endpoints from 04. API Specifications (GET /api/v1/health, POST /api/v1/voice/transcribe)
- Real-time Server-Sent Events (SSE) streaming chunk-to-transcript events.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure 'src' is importable from anywhere
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.adapter import STTAdapterConfig
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.schemas import AudioChunk, TranscriptEventType

app = FastAPI(
    title="AI Voice Co-Pilot - STT Service (W2)",
    version="0.1.0",
    description="Speech-to-Text pipeline foundation and mock server by Disha D K (SDE 3).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AI Voice Co-Pilot | STT Pipeline Live Demo</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #121826;
      --card-border: #1f293d;
      --primary: #38bdf8;
      --primary-glow: rgba(56, 189, 248, 0.25);
      --success: #34d399;
      --warning: #fbbf24;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --font-sans: 'Inter', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      min-height: 100vh;
      padding: 24px;
    }
    .container {
      max-width: 1100px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }
    .badge {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.15);
      color: var(--primary);
      border: 1px solid rgba(56, 189, 248, 0.3);
      display: inline-block;
      margin-bottom: 6px;
    }
    h1 {
      font-size: 1.6rem;
      font-weight: 700;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .subtitle {
      font-size: 0.85rem;
      color: var(--text-muted);
    }
    .status-pill {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 20px;
      background: #1e293b;
      font-size: 0.8rem;
      font-family: var(--font-mono);
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 10px var(--success);
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 24px;
    }
    @media (max-width: 800px) {
      .grid { grid-template-columns: 1fr; }
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      flex-direction: column;
    }
    .card-title {
      font-size: 0.95rem;
      font-weight: 600;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: #e2e8f0;
    }
    .controls {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    select, button {
      font-family: inherit;
      font-size: 0.9rem;
      border-radius: 8px;
      padding: 10px 14px;
      border: 1px solid var(--card-border);
      outline: none;
    }
    select {
      background: #1e293b;
      color: var(--text);
    }
    .btn-primary {
      background: linear-gradient(135deg, #0284c7, #2563eb);
      color: white;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
      box-shadow: 0 4px 14px var(--primary-glow);
    }
    .btn-primary:hover {
      opacity: 0.95;
      transform: translateY(-1px);
    }
    .btn-primary:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
    }
    .btn-secondary {
      background: #1e293b;
      color: var(--text-muted);
      cursor: pointer;
    }
    .btn-secondary:hover {
      background: #334155;
      color: var(--text);
    }
    .telemetry {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }
    .stat-box {
      background: #1a2234;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 12px;
    }
    .stat-label {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 4px;
    }
    .stat-value {
      font-family: var(--font-mono);
      font-size: 1.2rem;
      font-weight: 700;
      color: var(--primary);
    }
    .interim-banner {
      background: rgba(251, 191, 36, 0.08);
      border: 1px dashed rgba(251, 191, 36, 0.4);
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 16px;
      min-height: 54px;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .interim-tag {
      font-size: 0.7rem;
      font-weight: 700;
      background: var(--warning);
      color: #1e293b;
      padding: 2px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      font-family: var(--font-mono);
    }
    .interim-text {
      color: #fde68a;
      font-style: italic;
      font-size: 0.95rem;
    }
    .segments-list {
      max-height: 280px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding-right: 4px;
    }
    .segment-item {
      background: #182234;
      border-left: 3px solid var(--success);
      border-radius: 6px;
      padding: 10px 14px;
      font-size: 0.88rem;
    }
    .segment-meta {
      display: flex;
      justify-content: space-between;
      font-size: 0.72rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
      margin-bottom: 4px;
    }
    .confidence-pill {
      background: rgba(52, 211, 153, 0.15);
      color: var(--success);
      padding: 1px 6px;
      border-radius: 4px;
    }
    .full-transcript-box {
      background: #0f172a;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 14px;
      min-height: 80px;
      font-size: 1rem;
      line-height: 1.6;
      color: #f8fafc;
      white-space: pre-wrap;
    }
    .waveform {
      display: flex;
      align-items: center;
      gap: 4px;
      height: 24px;
    }
    .wave-bar {
      width: 4px;
      background: var(--primary);
      border-radius: 2px;
      height: 6px;
      transition: height 0.1s ease;
    }
    .active .wave-bar {
      animation: bounce 0.6s infinite ease-in-out alternate;
    }
    .active .wave-bar:nth-child(2) { animation-delay: 0.1s; }
    .active .wave-bar:nth-child(3) { animation-delay: 0.2s; }
    .active .wave-bar:nth-child(4) { animation-delay: 0.3s; }
    .active .wave-bar:nth-child(5) { animation-delay: 0.4s; }
    @keyframes bounce {
      0% { height: 4px; }
      100% { height: 22px; }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <span class="badge">Workstream W2 &bull; Speech-To-Text</span>
        <h1>AI Voice Co-Pilot &mdash; STT Foundation Live Demo</h1>
        <div class="subtitle">Author: <strong>Disha D K</strong> (SDE 3) &bull; Provider-Neutral Mock Pipeline (Day 1&ndash;7)</div>
      </div>
      <div class="status-pill">
        <span class="dot" id="server-dot"></span>
        <span id="server-status">MOCK READY</span>
      </div>
    </header>

    <div class="grid">
      <!-- Left Column: Controls & Telemetry -->
      <div class="card">
        <div class="card-title">
          <span>Streaming Controls</span>
          <div class="waveform" id="waveform">
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
            <div class="wave-bar"></div>
          </div>
        </div>

        <div class="controls">
          <label style="font-size:0.8rem; color:var(--text-muted)">Select Scenario / Persona:</label>
          <select id="scenario-select">
            <option value="p1">Persona 1: Student Developer ("Why is this application showing this error?")</option>
            <option value="p2">Persona 2: Research Student ("Explain the methodology shown on this page.")</option>
            <option value="p3">Persona 3: General User ("Find the project report I downloaded yesterday.")</option>
            <option value="multi">Multi-Turn Utterance (Full Vertical Slice Combination)</option>
          </select>

          <button class="btn-primary" id="btn-start" onclick="startStreaming()">
            Start Streaming Audio Chunks
          </button>
          <button class="btn-secondary" id="btn-reset" onclick="resetPipeline()">
            Reset Pipeline
          </button>
        </div>

        <div style="margin-top: 20px;">
          <div class="card-title">Telemetry &amp; Audit</div>
          <div class="telemetry">
            <div class="stat-box">
              <div class="stat-label">Audio Chunks</div>
              <div class="stat-value" id="stat-chunks">0</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Events Emitted</div>
              <div class="stat-value" id="stat-events">0</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Duration</div>
              <div class="stat-value" id="stat-duration">0.00s</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Avg Confidence</div>
              <div class="stat-value" id="stat-confidence">0.0%</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Live Stream & Segments -->
      <div class="card">
        <div class="card-title">
          <span>Live In-Flight Interim Hypothesis</span>
          <span style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono)">OrderedSegmentAccumulator</span>
        </div>

        <div class="interim-banner" id="interim-banner">
          <span class="interim-tag">Interim</span>
          <span class="interim-text" id="interim-text">Awaiting audio stream...</span>
        </div>

        <div class="card-title" style="margin-top: 8px;">Committed Final Segments (Chronological)</div>
        <div class="segments-list" id="segments-list">
          <div style="color:var(--text-muted); font-size:0.85rem; text-align:center; padding: 24px 0;">
            No finalized segments committed yet. Click 'Start Streaming' above.
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom: Consolidated Transcript -->
    <div class="card">
      <div class="card-title">
        <span>Accumulated Final Transcript</span>
        <span style="font-size:0.75rem; color:var(--success); font-family:var(--font-mono)">Deduplicated &amp; Verified</span>
      </div>
      <div class="full-transcript-box" id="full-transcript">Ready for transcription...</div>
    </div>
  </div>

  <script>
    let evtSource = null;

    function startStreaming() {
      const btn = document.getElementById('btn-start');
      btn.disabled = true;
      btn.innerText = 'Streaming Audio Chunks...';
      document.getElementById('waveform').classList.add('active');

      const scenario = document.getElementById('scenario-select').value;
      const segmentsList = document.getElementById('segments-list');
      segmentsList.innerHTML = '';
      document.getElementById('full-transcript').innerText = '';

      if (evtSource) {
        evtSource.close();
      }

      evtSource = new EventSource('/api/v1/voice/stream?scenario=' + encodeURIComponent(scenario));

      evtSource.onmessage = function(e) {
        const payload = JSON.parse(e.data);

        if (payload.type === 'interim') {
          document.getElementById('interim-text').innerText = payload.text;
          updateTelemetry(payload.telemetry);
        } else if (payload.type === 'final') {
          addFinalSegment(payload);
          document.getElementById('interim-text').innerText = '(finalized clause committed)';
          updateTelemetry(payload.telemetry);
          document.getElementById('full-transcript').innerText = payload.telemetry.full_transcript;
        } else if (payload.type === 'done') {
          evtSource.close();
          btn.disabled = false;
          btn.innerText = 'Start Streaming Audio Chunks';
          document.getElementById('waveform').classList.remove('active');
          document.getElementById('interim-text').innerText = 'Streaming completed.';
        }
      };

      evtSource.onerror = function(err) {
        console.error('SSE Stream error:', err);
        document.getElementById('interim-text').innerHTML = '<span style="color:#f87171;">Connection issue. Retrying...</span>';
        evtSource.close();
        btn.disabled = false;
        btn.innerText = 'Start Streaming Audio Chunks';
        document.getElementById('waveform').classList.remove('active');
      };
    }

    function addFinalSegment(item) {
      const list = document.getElementById('segments-list');
      const div = document.createElement('div');
      div.className = 'segment-item';
      div.innerHTML = `
        <div class="segment-meta">
          <span>t=${item.start_time.toFixed(1)}s &rarr; ${item.end_time.toFixed(1)}s [${item.segment_id.slice(0, 8)}]</span>
          <span class="confidence-pill">${(item.confidence * 100).toFixed(0)}% conf</span>
        </div>
        <div style="font-weight: 500; color: #fff;">"${item.text}"</div>
      `;
      list.appendChild(div);
      list.scrollTop = list.scrollHeight;
    }

    function updateTelemetry(tel) {
      if (!tel) return;
      document.getElementById('stat-chunks').innerText = tel.chunks_processed || 0;
      document.getElementById('stat-events').innerText = tel.events_processed || 0;
      document.getElementById('stat-duration').innerText = (tel.total_duration_seconds || 0).toFixed(2) + 's';
      document.getElementById('stat-confidence').innerText = ((tel.average_confidence || 0) * 100).toFixed(1) + '%';
    }

    async function resetPipeline() {
      if (evtSource) evtSource.close();
      await fetch('/api/v1/voice/reset', { method: 'POST' });
      document.getElementById('segments-list').innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; text-align:center; padding: 24px 0;">Pipeline reset. Ready for new stream.</div>';
      document.getElementById('interim-text').innerText = 'Awaiting audio stream...';
      document.getElementById('full-transcript').innerText = 'Ready for transcription...';
      document.getElementById('waveform').classList.remove('active');
      const btn = document.getElementById('btn-start');
      btn.disabled = false;
      btn.innerText = 'Start Streaming Audio Chunks';
      updateTelemetry({ chunks_processed: 0, events_processed: 0, total_duration_seconds: 0, average_confidence: 0 });
    }
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_dashboard() -> str:
    """Serve the interactive Day 7 demonstration dashboard."""
    return HTML_DASHBOARD


@app.get("/api/v1/health")
async def get_health() -> Dict[str, Any]:
    """Standard health check endpoint conforming to 04. API Specifications."""
    return {
        "status": "ok",
        "service": "voice-speech-to-text",
        "workstream": "W2 - Speech-to-Text Foundation",
        "engineer": "Disha D K (SDE 3)",
        "mode": "deterministic-mock",
        "api_version": "v1",
    }


class TranscribeRequest(BaseModel):
    session_id: Optional[str] = None
    chunks: Optional[List[Dict[str, Any]]] = None
    script: Optional[List[str]] = None


@app.post("/api/v1/voice/transcribe")
async def post_transcribe(payload: Optional[TranscribeRequest] = None) -> Dict[str, Any]:
    """API endpoint conforming to 04. API Specifications: POST /api/v1/voice/transcribe."""
    phrases = payload.script if (payload and payload.script) else [
        "Why is this application showing this error?",
        "Explain the methodology shown on this page.",
    ]
    transcriber = DeterministicFakeTranscriber(script=phrases, seed=42)
    accumulator = OrderedSegmentAccumulator()
    transcriber.initialize()

    dummy_pcm = b"\x00\x01" * 1600
    for idx in range(16):
        chunk = AudioChunk(
            data=dummy_pcm,
            sequence_number=idx,
            timestamp=idx * 0.1,
            duration_ms=100.0,
            is_last=(idx == 15),
        )
        for ev in transcriber.transcribe_chunk(chunk):
            accumulator.ingest_event(ev)

    summary = accumulator.get_summary()
    return {
        "status": "completed",
        "session_id": payload.session_id if payload else "mock-session-001",
        "transcript": summary["full_transcript"],
        "segments": [s.model_dump() for s in accumulator.get_final_segments()],
        "metrics": summary,
    }


@app.post("/api/v1/voice/reset")
async def post_reset() -> Dict[str, str]:
    """Reset endpoint for the mock session."""
    return {"status": "reset_successful"}


@app.get("/api/v1/voice/stream")
async def stream_audio_events(scenario: str = "p1") -> StreamingResponse:
    """Stream real-time STT events via Server-Sent Events (SSE)."""
    scenarios = {
        "p1": ["Why is this application showing this error?"],
        "p2": ["Explain the methodology shown on this page."],
        "p3": ["Find the project report I downloaded yesterday."],
        "multi": [
            "Why is this application showing this error?",
            "Explain the methodology shown on this page.",
        ],
    }
    script = scenarios.get(scenario, scenarios["p1"])

    async def event_generator():
        transcriber = DeterministicFakeTranscriber(
            config=STTAdapterConfig(interim_results=True),
            script=script,
            seed=42,
        )
        accumulator = OrderedSegmentAccumulator()
        transcriber.initialize()

        dummy_pcm = b"\x00\x02" * 1600
        total_chunks = len(script) * 8 + 4

        for idx in range(total_chunks):
            await asyncio.sleep(0.12)  # Simulate 120ms streaming network packets
            chunk = AudioChunk(
                data=dummy_pcm,
                sequence_number=idx,
                timestamp=idx * 0.1,
                duration_ms=100.0,
                is_last=(idx == total_chunks - 1),
            )
            events = transcriber.transcribe_chunk(chunk)
            for evt in events:
                accumulator.ingest_event(evt)
                tel = accumulator.get_summary()
                tel["chunks_processed"] = idx + 1

                if evt.event_type == TranscriptEventType.INTERIM and evt.segment:
                    data = {
                        "type": "interim",
                        "text": evt.segment.text,
                        "confidence": evt.segment.confidence,
                        "start_time": evt.segment.start_time,
                        "end_time": evt.segment.end_time,
                        "telemetry": tel,
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                elif evt.event_type == TranscriptEventType.FINAL and evt.segment:
                    data = {
                        "type": "final",
                        "segment_id": evt.segment.segment_id,
                        "text": evt.segment.text,
                        "confidence": evt.segment.confidence,
                        "start_time": evt.segment.start_time,
                        "end_time": evt.segment.end_time,
                        "telemetry": tel,
                    }
                    yield f"data: {json.dumps(data)}\n\n"

            if accumulator.final_count >= len(script):
                break

        tel = accumulator.get_summary()
        yield f"data: {json.dumps({'type': 'done', 'telemetry': tel})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def main() -> None:
    import uvicorn
    print("=" * 72)
    print("   AI Voice Co-Pilot (W2 - STT Foundation) - Localhost Web Server")
    print("   Author: Disha D K (SDE 3) | Workstream: Speech-to-Text Pipeline")
    print("   Web Dashboard URL: http://localhost:8000")
    print("=" * 72)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

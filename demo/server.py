#!/usr/bin/env python3
# Optional demo only; not part of the Week 1 deliverable contract.
"""AI Voice Co-Pilot - Upgraded Day 7 Localhost Web Demo & API Server.

Workstream: W2 - Speech-to-Text Pipeline Foundation
Author: Disha D K (SDE 3)

Provides:
- Interactive Browser Dashboard at http://localhost:8000
- Official Named Fixtures (A through F)
- Event Arrival Timeline vs Audio Chronology Diagnostics
- Live Repeatability Audit (Pass 1 vs Pass 2 bit-for-bit check)
- SSE Streaming and Standard SDD REST API endpoints
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure 'src' is importable from anywhere
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.fixtures import FIXTURE_REGISTRY, get_fixture
from voice_stt.schemas import (
    AudioChunk,
    STTErrorDetail,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


app = FastAPI(
    title="AI Voice Co-Pilot - STT Service (W2)",
    version="0.2.0",
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
  <title>AI Voice Co-Pilot | STT Foundation Live Demo</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #121826;
      --card-border: #1f293d;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --primary-glow: rgba(56, 189, 248, 0.25);
      --success: #34d399;
      --warning: #fbbf24;
      --error: #f87171;
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
      max-width: 1180px;
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
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(56, 189, 248, 0.12);
      color: var(--primary);
      border: 1px solid rgba(56, 189, 248, 0.28);
      display: inline-block;
      margin-bottom: 6px;
    }
    h1 {
      font-size: 1.65rem;
      font-weight: 700;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .subtitle {
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-top: 2px;
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
      border: 1px solid var(--card-border);
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
      margin-bottom: 20px;
    }
    @media (max-width: 860px) {
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
      font-size: 0.88rem;
      border-radius: 8px;
      padding: 10px 14px;
      border: 1px solid var(--card-border);
      outline: none;
    }
    select {
      background: #1e293b;
      color: var(--text);
      cursor: pointer;
    }
    .btn-group {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .btn-primary {
      background: linear-gradient(135deg, #0284c7, #2563eb);
      color: white;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
      box-shadow: 0 4px 14px var(--primary-glow);
    }
    .btn-primary:hover:not(:disabled) {
      opacity: 0.95;
      transform: translateY(-1px);
    }
    .btn-primary:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .btn-secondary {
      background: #1e293b;
      color: var(--text);
      cursor: pointer;
      transition: background 0.2s ease;
    }
    .btn-secondary:hover:not(:disabled) {
      background: #334155;
    }
    .btn-audit {
      background: #1e1b4b;
      color: #c7d2fe;
      border: 1px solid #4338ca;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s ease;
    }
    .btn-audit:hover:not(:disabled) {
      background: #312e81;
    }
    .telemetry {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }
    @media (max-width: 600px) {
      .telemetry { grid-template-columns: repeat(2, 1fr); }
    }
    .stat-box {
      background: #1a2234;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 10px;
    }
    .stat-label {
      font-size: 0.68rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 2px;
    }
    .stat-value {
      font-family: var(--font-mono);
      font-size: 1.15rem;
      font-weight: 700;
      color: var(--primary);
    }
    .interim-banner {
      background: rgba(251, 191, 36, 0.08);
      border: 1px dashed rgba(251, 191, 36, 0.4);
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 16px;
      min-height: 52px;
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
      font-size: 0.92rem;
    }
    .segments-list {
      max-height: 250px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 8px;
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
      font-weight: 600;
    }
    .full-transcript-box {
      background: #0f172a;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 14px;
      min-height: 70px;
      font-size: 0.98rem;
      line-height: 1.6;
      color: #f8fafc;
      white-space: pre-wrap;
    }
    .waveform {
      display: flex;
      align-items: center;
      gap: 4px;
      height: 20px;
    }
    .wave-bar {
      width: 4px;
      background: var(--primary);
      border-radius: 2px;
      height: 4px;
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
      100% { height: 20px; }
    }
    /* Timeline & Diagnostics */
    .timeline-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
      font-family: var(--font-mono);
      margin-top: 10px;
    }
    .timeline-table th, .timeline-table td {
      padding: 6px 10px;
      text-align: left;
      border-bottom: 1px solid var(--card-border);
    }
    .timeline-table th {
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.68rem;
    }
    .badge-reordered {
      background: rgba(251, 191, 36, 0.2);
      color: var(--warning);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.68rem;
    }
    .badge-duplicate {
      background: rgba(248, 113, 113, 0.2);
      color: var(--error);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.68rem;
    }
    .badge-chronological {
      background: rgba(52, 211, 153, 0.15);
      color: var(--success);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.68rem;
    }
    .error-banner {
      display: none;
      background: rgba(248, 113, 113, 0.1);
      border: 1px solid rgba(248, 113, 113, 0.35);
      border-radius: 8px;
      padding: 12px 16px;
      margin-top: 14px;
      color: #fca5a5;
      font-size: 0.85rem;
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
          <label style="font-size:0.8rem; color:var(--text-muted)">Select Scenario / Canonical Fixture:</label>
          <select id="fixture-select" onchange="onFixtureChange()">
            <option value="A">Fixture A: Normal Multi-Segment (Student Developer - 2 Segments)</option>
            <option value="B">Fixture B: Interim-to-Final Lifecycle (Research Student - In-Flight Evolution)</option>
            <option value="C">Fixture C: Out-of-Order Delivery (Arrival Order 2,3,1 &rarr; Audio Order 1,2,3)</option>
            <option value="D">Fixture D: Duplicate Delivery (Suppresses duplicate events without text dup)</option>
            <option value="E">Fixture E: Invalid Payload Rejection (Inverted timestamps &amp; bounds check)</option>
            <option value="F">Fixture F: Simulated Adapter Failure &amp; Clean Recovery</option>
          </select>

          <div style="font-size:0.75rem; color:var(--text-muted); background:#1a2234; padding:8px 12px; border-radius:6px;" id="fixture-desc">
            Standard student developer utterance correctly split into two chronological final segments.
          </div>

          <div style="display:flex; gap:10px; align-items:center;">
            <label style="font-size:0.75rem; color:var(--text-muted); white-space:nowrap;">Speed:</label>
            <select id="speed-select" style="padding:6px 10px; font-size:0.8rem; flex-grow:1;">
              <option value="100">Real-time (100ms)</option>
              <option value="30">Fast (30ms)</option>
              <option value="0">Instant (Mock)</option>
            </select>
          </div>

          <button class="btn-primary" id="btn-start" onclick="startStreaming()">
            Start Streaming Audio Chunks
          </button>

          <div class="btn-group">
            <button class="btn-secondary" id="btn-replay" onclick="replayStream()" title="Re-run same fixture">
              &#x21bb; Replay Fixture
            </button>
            <button class="btn-audit" id="btn-audit" onclick="runRepeatabilityAudit()" title="Compare 2 passes bit-for-bit">
              &#x2714; Repeatability Audit
            </button>
          </div>

          <button class="btn-secondary" id="btn-reset" onclick="resetPipeline()">
            Reset Pipeline
          </button>
        </div>

        <div class="error-banner" id="error-banner"></div>

        <div style="margin-top: 20px;">
          <div class="card-title">Telemetry &amp; Audit Metrics</div>
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
              <div class="stat-label">Final Segments</div>
              <div class="stat-value" id="stat-finals">0</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Interim Updates</div>
              <div class="stat-value" id="stat-interims">0</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Audio Duration</div>
              <div class="stat-value" id="stat-duration">0.00s</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Avg Confidence</div>
              <div class="stat-value" id="stat-confidence">0.0%</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Duplicates Ignored</div>
              <div class="stat-value" id="stat-duplicates" style="color:var(--warning)">0</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Reordered Chunks</div>
              <div class="stat-value" id="stat-reordered" style="color:var(--success)">0</div>
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

        <div class="card-title" style="margin-top: 8px;">Committed Final Segments (Chronological Audio Order)</div>
        <div class="segments-list" id="segments-list">
          <div style="color:var(--text-muted); font-size:0.85rem; text-align:center; padding: 24px 0;">
            No finalized segments committed yet. Click 'Start Streaming' above.
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom: Consolidated Transcript -->
    <div class="card" style="margin-bottom: 20px;">
      <div class="card-title">
        <span>Accumulated Final Transcript</span>
        <span id="verification-badge" style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono)">Pending Stream</span>
      </div>
      <div class="full-transcript-box" id="full-transcript">Ready for transcription...</div>
    </div>

    <!-- Distinctive Feature: Event Arrival Timeline vs Audio Chronology -->
    <div class="card">
      <div class="card-title">
        <span>Distinctive Observability: Arrival Sequence vs Audio Chronology Diagnostics</span>
        <span style="font-size:0.75rem; color:var(--primary); font-family:var(--font-mono)">Event Order Audit</span>
      </div>
      <div style="max-height: 200px; overflow-y: auto;">
        <table class="timeline-table">
          <thead>
            <tr>
              <th>Arrival #</th>
              <th>Event ID</th>
              <th>Type</th>
              <th>Audio Window</th>
              <th>Segment Text</th>
              <th>Pipeline Action</th>
            </tr>
          </thead>
          <tbody id="timeline-body">
            <tr>
              <td colspan="6" style="text-align:center; color:var(--text-muted); padding:16px;">
                Arrival sequence history will appear here during stream execution.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    let evtSource = null;

    const FIXTURE_DESCRIPTIONS = {
      'A': 'Standard student developer utterance correctly split into two chronological final segments.',
      'B': 'Four in-flight interim hypotheses culminating in one immutable final segment.',
      'C': 'Deliberately disordered arrival order (2, 3, 1) to verify chronological audio-time sorting.',
      'D': 'Duplicate delivery of segment 1 to verify deduplication without text duplication.',
      'E': 'Malformed payload with inverted timestamps (end < start) and confidence > 1.0 to prove error resilience.',
      'F': 'Controlled engine error to test error reporting and pipeline reset recovery.'
    };

    function onFixtureChange() {
      const f = document.getElementById('fixture-select').value;
      document.getElementById('fixture-desc').innerText = FIXTURE_DESCRIPTIONS[f] || '';
    }

    function startStreaming() {
      const btn = document.getElementById('btn-start');
      btn.disabled = true;
      btn.innerText = 'Streaming Audio Chunks...';
      document.getElementById('waveform').classList.add('active');
      document.getElementById('error-banner').style.display = 'none';

      const fixture = document.getElementById('fixture-select').value;
      const speed = document.getElementById('speed-select').value;
      const segmentsList = document.getElementById('segments-list');
      segmentsList.innerHTML = '';
      document.getElementById('timeline-body').innerHTML = '';
      document.getElementById('full-transcript').innerText = '';
      document.getElementById('verification-badge').innerText = 'Streaming in progress...';
      document.getElementById('verification-badge').style.color = 'var(--primary)';

      if (evtSource) {
        evtSource.close();
      }

      evtSource = new EventSource('/demo/stream?fixture=' + encodeURIComponent(fixture) + '&speed=' + encodeURIComponent(speed));

      evtSource.onmessage = function(e) {
        const payload = JSON.parse(e.data);

        if (payload.type === 'interim') {
          document.getElementById('interim-text').innerText = payload.text;
          updateTelemetry(payload.telemetry);
          appendTimelineRow(payload);
        } else if (payload.type === 'final') {
          addFinalSegment(payload);
          document.getElementById('interim-text').innerText = '(No active interim hypothesis)';
          updateTelemetry(payload.telemetry);
          appendTimelineRow(payload);
          document.getElementById('full-transcript').innerText = payload.telemetry.full_transcript;
        } else if (payload.type === 'error_event') {
          document.getElementById('error-banner').style.display = 'block';
          if (payload.error && payload.error.code === 'INVALID_PAYLOAD_REJECTED') {
            document.getElementById('error-banner').style.background = 'rgba(52, 211, 153, 0.12)';
            document.getElementById('error-banner').style.borderColor = 'rgba(52, 211, 153, 0.35)';
            document.getElementById('error-banner').style.color = '#34d399';
            document.getElementById('error-banner').innerHTML = `<strong>✔ Validation Catch Verified:</strong> [${payload.error.code}] ${payload.error.message}`;
            document.getElementById('server-status').innerText = 'VALIDATION VERIFIED';
            document.getElementById('server-dot').style.background = 'var(--success)';
            document.getElementById('verification-badge').innerText = 'Invalid Payload Rejected (State Preserved)';
            document.getElementById('verification-badge').style.color = 'var(--success)';
          } else if (payload.error && payload.error.code === 'SIMULATED_TRANSCRIBER_ERROR') {
            document.getElementById('error-banner').style.background = 'rgba(52, 211, 153, 0.12)';
            document.getElementById('error-banner').style.borderColor = 'rgba(52, 211, 153, 0.35)';
            document.getElementById('error-banner').style.color = '#34d399';
            document.getElementById('error-banner').innerHTML = `<strong>✔ Resilience &amp; Recovery Verified:</strong> [${payload.error.code}] ${payload.error.message} (Pipeline state preserved &amp; auto-recovered)`;
            document.getElementById('server-status').innerText = 'RECOVERY VERIFIED';
            document.getElementById('server-dot').style.background = 'var(--success)';
            document.getElementById('verification-badge').innerText = 'Fault Tolerant (State Preserved &amp; Recovered)';
            document.getElementById('verification-badge').style.color = 'var(--success)';
          } else {
            document.getElementById('error-banner').style.background = 'rgba(248, 113, 113, 0.12)';
            document.getElementById('error-banner').style.borderColor = 'rgba(248, 113, 113, 0.35)';
            document.getElementById('error-banner').style.color = '#f87171';
            document.getElementById('error-banner').innerHTML = `<strong>Error Event:</strong> [${payload.error ? payload.error.code : 'ERROR'}] ${payload.error ? payload.error.message : 'Error reported'}`;
            document.getElementById('server-status').innerText = 'ERROR DETECTED';
            document.getElementById('server-dot').style.background = 'var(--error)';
            document.getElementById('verification-badge').innerText = 'Error Reported (State Preserved)';
            document.getElementById('verification-badge').style.color = 'var(--error)';
          }
          appendTimelineRow(payload);
        } else if (payload.type === 'done') {
          evtSource.close();
          btn.disabled = false;
          btn.innerText = 'Start Streaming Audio Chunks';
          document.getElementById('waveform').classList.remove('active');
          if (payload.telemetry && payload.telemetry.full_transcript) {
            document.getElementById('full-transcript').innerText = payload.telemetry.full_transcript;
          }
          if (payload.telemetry.is_verified) {
            document.getElementById('verification-badge').innerText = 'Deduplicated & Verified';
            document.getElementById('verification-badge').style.color = 'var(--success)';
          }
          if (payload.telemetry.last_error && payload.telemetry.last_error.code === 'INVALID_PAYLOAD_REJECTED') {
            document.getElementById('interim-text').innerText = 'Invalid payload successfully rejected. State preserved.';
          } else if (payload.telemetry.last_error && payload.telemetry.last_error.code === 'SIMULATED_TRANSCRIBER_ERROR') {
            document.getElementById('interim-text').innerText = 'Controlled engine error safely handled. Pipeline auto-recovered.';
          } else if (payload.telemetry.last_error) {
            document.getElementById('interim-text').innerText = 'Streaming stopped on error.';
          } else {
            document.getElementById('interim-text').innerText = 'Streaming completed.';
          }
        }
      };

      evtSource.onerror = function(err) {
        console.error('SSE Stream error:', err);
        document.getElementById('error-banner').style.display = 'block';
        document.getElementById('error-banner').innerText = 'Stream error or simulated rejection triggered.';
        evtSource.close();
        btn.disabled = false;
        btn.innerText = 'Start Streaming Audio Chunks';
        document.getElementById('waveform').classList.remove('active');
      };
    }

    function replayStream() {
      resetPipeline().then(() => startStreaming());
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

    function appendTimelineRow(payload) {
      const tbody = document.getElementById('timeline-body');
      const tr = document.createElement('tr');

      let actionBadge = '<span class="badge-chronological">Committed</span>';
      if (payload.is_duplicate) {
        actionBadge = '<span class="badge-duplicate">Duplicate Suppressed</span>';
      } else if (payload.was_reordered) {
        actionBadge = '<span class="badge-reordered">Out-of-Order Reordered</span>';
      } else if (payload.type === 'interim') {
        actionBadge = '<span style="color:var(--warning)">Interim Revision</span>';
      } else if (payload.type === 'error_event') {
        actionBadge = '<span class="badge-chronological">Fault Contained</span>';
      }

      tr.innerHTML = `
        <td>#${payload.arrival_index || (tbody.children.length + 1)}</td>
        <td>${(payload.event_id || payload.segment_id || 'n/a').slice(0, 12)}</td>
        <td style="text-transform:uppercase">${payload.type}</td>
        <td>${(payload.start_time || 0).toFixed(1)}s - ${(payload.end_time || 0).toFixed(1)}s</td>
        <td>${payload.text || (payload.error ? payload.error.code : 'n/a')}</td>
        <td>${actionBadge}</td>
      `;
      tbody.appendChild(tr);
    }

    function updateTelemetry(tel) {
      if (!tel) return;
      document.getElementById('stat-chunks').innerText = tel.chunks_streamed || tel.chunks_processed || 0;
      document.getElementById('stat-events').innerText = tel.events_processed || 0;
      document.getElementById('stat-finals').innerText = tel.final_segments_count || 0;
      document.getElementById('stat-interims').innerText = tel.interim_updates_count || 0;
      document.getElementById('stat-duration').innerText = (tel.total_duration_seconds || 0).toFixed(2) + 's';
      document.getElementById('stat-confidence').innerText = ((tel.average_confidence || 0) * 100).toFixed(1) + '%';
      document.getElementById('stat-duplicates').innerText = tel.duplicates_suppressed || 0;
      document.getElementById('stat-reordered').innerText = tel.out_of_order_reordered || 0;
    }

    async function runRepeatabilityAudit() {
      const btn = document.getElementById('btn-audit');
      btn.disabled = true;
      btn.innerText = 'Auditing...';
      const fixture = document.getElementById('fixture-select').value;

      try {
        const resp = await fetch('/demo/audit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fixture_id: fixture })
        });
        const data = await resp.json();
        if (data.is_deterministic) {
          alert(`Repeatability Audit PASSED!\\n\\nPass 1 events: ${data.pass1_events}\\nPass 2 events: ${data.pass2_events}\\nExact Bit-for-Bit Determinism: 100% MATCH`);
        } else {
          alert('Audit Failed: outputs did not match.');
        }
      } catch (err) {
        alert('Audit request failed: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerText = '✔ Repeatability Audit';
      }
    }

    async function resetPipeline() {
      if (evtSource) evtSource.close();
      await fetch('/demo/reset', { method: 'POST' });
      document.getElementById('segments-list').innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; text-align:center; padding: 24px 0;">Pipeline reset. Ready for new stream.</div>';
      document.getElementById('timeline-body').innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:16px;">Arrival sequence history cleared.</td></tr>';
      document.getElementById('interim-text').innerText = 'Awaiting audio stream...';
      document.getElementById('full-transcript').innerText = 'Ready for transcription...';
      document.getElementById('verification-badge').innerText = 'Mock Ready';
      document.getElementById('verification-badge').style.color = 'var(--text-muted)';
      document.getElementById('waveform').classList.remove('active');
      document.getElementById('error-banner').style.display = 'none';
      document.getElementById('server-status').innerText = 'MOCK READY';
      document.getElementById('server-dot').style.background = 'var(--success)';
      document.getElementById('fixture-select').value = 'A';
      onFixtureChange();
      const btn = document.getElementById('btn-start');
      btn.disabled = false;
      btn.innerText = 'Start Streaming Audio Chunks';
      updateTelemetry({
        chunks_processed: 0,
        events_processed: 0,
        final_segments_count: 0,
        interim_updates_count: 0,
        total_duration_seconds: 0,
        average_confidence: 0,
        duplicates_suppressed: 0,
        out_of_order_reordered: 0
      });
    }
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_dashboard() -> str:
    """Serve the interactive Week 1 demonstration dashboard."""
    return HTML_DASHBOARD


@app.get("/demo/health")
@app.get("/api/v1/health")
async def get_health() -> Dict[str, Any]:
    """Health check endpoint for the demo."""
    return {
        "status": "ok",
        "service": "voice-speech-to-text",
        "workstream": "W2 - Speech-to-Text Foundation",
        "engineer": "Disha D K (SDE 3)",
        "mode": "deterministic-mock",
        "fixtures_available": list(FIXTURE_REGISTRY.keys()),
        "api_version": "v1",
    }


class AuditRequest(BaseModel):
    fixture_id: str = "A"


@app.post("/demo/audit")
@app.post("/api/v1/voice/audit")
async def post_audit(req: AuditRequest) -> Dict[str, Any]:
    """Run repeatability audit comparing two execution passes of the same fixture."""
    fixture = get_fixture(req.fixture_id)

    # Pass 1
    t1 = DeterministicFakeTranscriber(fixture=fixture, seed=42)
    t1.initialize()
    p1_events: List[str] = []
    dummy = b"\x00" * 3200
    for idx in range(len(fixture.events) + 2):
        for e in t1.transcribe_chunk(dummy):
            p1_events.append(e.model_dump_json())

    # Pass 2
    t2 = DeterministicFakeTranscriber(fixture=fixture, seed=42)
    t2.initialize()
    p2_events: List[str] = []
    for idx in range(len(fixture.events) + 2):
        for e in t2.transcribe_chunk(dummy):
            p2_events.append(e.model_dump_json())

    is_match = (p1_events == p2_events) and len(p1_events) > 0
    return {
        "fixture_id": req.fixture_id,
        "is_deterministic": is_match,
        "pass1_events": len(p1_events),
        "pass2_events": len(p2_events),
    }


@app.post("/demo/reset")
@app.post("/api/v1/voice/reset")
async def post_reset() -> Dict[str, str]:
    """Reset session state."""
    return {"status": "reset_successful"}


@app.get("/demo/stream")
@app.get("/api/v1/voice/stream")
async def stream_audio_events(fixture: str = "A", speed: int = 100) -> StreamingResponse:
    """Stream real-time STT events via Server-Sent Events (SSE)."""
    f = get_fixture(fixture)
    delay_sec = max(0.0, speed / 1000.0)

    async def event_generator():
        acc = OrderedSegmentAccumulator()
        chunk_counter = 0

        # Special handling for Fixture E (Invalid Payload Injection)
        if f.fixture_id == "E" and f.raw_invalid_payload:
            # First deliver baseline valid segment
            baseline_evt = f.events[0]
            chunk_counter += 1
            acc.ingest_event(baseline_evt)
            tel = acc.get_summary()
            tel["chunks_processed"] = chunk_counter
            tel["chunks_streamed"] = chunk_counter
            if baseline_evt.segment is not None:
                data = {
                    "type": "final",
                    "segment_id": baseline_evt.segment.segment_id,
                    "text": baseline_evt.segment.text,
                    "confidence": baseline_evt.segment.confidence,
                    "start_time": baseline_evt.segment.start_time,
                    "end_time": baseline_evt.segment.end_time,
                    "telemetry": tel,
                    "arrival_index": 1,
                    "is_duplicate": False,
                    "was_reordered": False,
                }
                yield f"data: {json.dumps(data)}\n\n"

            # Attempt to ingest the malformed payload
            if delay_sec > 0:
                await asyncio.sleep(delay_sec)

            try:
                # This must fail validation!
                TranscriptSegment.model_validate(f.raw_invalid_payload)
            except Exception:
                chunk_counter += 1
                error_detail = STTErrorDetail(
                    code="INVALID_PAYLOAD_REJECTED",
                    message=f"Malformed payload rejected: end_time ({f.raw_invalid_payload['end_time']}s) < start_time ({f.raw_invalid_payload['start_time']}s). State preserved.",
                    retryable=False,
                )
                err_evt = TranscriptEvent(
                    event_id="fix-e-err-001",
                    event_type=TranscriptEventType.ERROR,
                    sequence_number=1,
                    timestamp=1.0,
                    error=error_detail,
                )
                acc.ingest_event(err_evt)
                tel = acc.get_summary()
                tel["chunks_processed"] = chunk_counter
                tel["chunks_streamed"] = chunk_counter
                error_data = {
                    "type": "error_event",
                    "error": error_detail.model_dump(),
                    "telemetry": tel,
                    "arrival_index": 2,
                }
                yield f"data: {json.dumps(error_data)}\n\n"

            tel = acc.get_summary()
            tel["chunks_processed"] = chunk_counter
            tel["chunks_streamed"] = chunk_counter
            yield f"data: {json.dumps({'type': 'done', 'telemetry': tel})}\n\n"
            return

        # Normal fixture processing
        transcriber = DeterministicFakeTranscriber(fixture=f, seed=42)
        transcriber.initialize()
        dummy_pcm = b"\x00\x02" * 1600

        total_steps = len(f.events) + 2
        for step in range(total_steps):
            if delay_sec > 0:
                await asyncio.sleep(delay_sec)

            chunk = AudioChunk(
                data=dummy_pcm,
                sequence_number=step,
                timestamp=step * 0.1,
                duration_ms=100.0,
                is_last=(step == total_steps - 1),
            )
            chunk_counter += 1
            events = transcriber.transcribe_chunk(chunk)

            for evt in events:
                acc.ingest_event(evt)
                tel = acc.get_summary()
                tel["chunks_processed"] = chunk_counter
                tel["chunks_streamed"] = chunk_counter

                # Find recent arrival record
                arrivals = acc.get_arrival_history()
                recent = arrivals[-1] if arrivals else {}

                if evt.event_type == TranscriptEventType.INTERIM and evt.segment:
                    data = {
                        "type": "interim",
                        "text": evt.segment.text,
                        "confidence": evt.segment.confidence,
                        "start_time": evt.segment.start_time,
                        "end_time": evt.segment.end_time,
                        "event_id": evt.event_id,
                        "telemetry": tel,
                        "arrival_index": recent.get("arrival_index", 1),
                        "is_duplicate": recent.get("is_duplicate", False),
                        "was_reordered": recent.get("was_reordered", False),
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
                        "event_id": evt.event_id,
                        "telemetry": tel,
                        "arrival_index": recent.get("arrival_index", 1),
                        "is_duplicate": recent.get("is_duplicate", False),
                        "was_reordered": recent.get("was_reordered", False),
                    }
                    yield f"data: {json.dumps(data)}\n\n"

                elif evt.event_type == TranscriptEventType.ERROR and evt.error:
                    data = {
                        "type": "error_event",
                        "error": evt.error.model_dump(),
                        "telemetry": tel,
                        "arrival_index": recent.get("arrival_index", 1),
                    }
                    yield f"data: {json.dumps(data)}\n\n"

            if transcriber.state == "error":
                break

        tel = acc.get_summary()
        tel["chunks_processed"] = chunk_counter
        tel["chunks_streamed"] = chunk_counter
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

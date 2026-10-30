# AI Voice Copilot — Audio Pipeline Foundation (W1)

**Product Name:** AI Voice Copilot (Academia AI Voice Bot)  
**Team:** SDE 3  
**Student:** Harshita G Kademani  
**Workstream:** W1 – Audio and VAD  
**Duration:** Day 1 – Day 7 (Week 1 – Foundation and first vertical slice)  
**Branch:** `feature/w1-audio-foundation`

---

## 1. Overview & Architecture

This repository delivers the **Week 1 foundation and first vertical slice** for the AI Voice Copilot audio ingestion pipeline. It adheres strictly to the System Design Document (SDD) and Product Requirements Document (PRD):

- **Canonical Audio Schemas (`src/schemas/audio.py`)**: Defined once as the single source of truth for downstream VAD, STT (Whisper), and agent workflows.
  - `AudioFormat`: Audio format metadata (sample rate in Hz, channel count, bit depth, encoding).
  - `AudioChunk`: Discrete audio frame slice with monotonically increasing `sequence_id`, precise `timestamp` in seconds, raw binary PCM payload, duration calculations, and serialization.
  - `AudioError`: Standardized error exception conforming to the SDD error format (`{"error": {"code": "...", "message": "...", "details": {...}}}`).
- **Deterministic Audio Chunker (`src/audio/chunker.py`)**: Slices continuous byte streams into fixed-duration `AudioChunk`s with strict frame alignment validation and reproducible outputs.
- **Deterministic Mock Microphone Source (`src/audio/mock_source.py`)**: Generates deterministic synthetic audio streams (16-bit linear PCM) for testing and pipeline integration without requiring physical microphone hardware.
- **Single-Command CLI Demo (`src/cli.py`)**: Real-time or batch streaming CLI demonstrating sequential chunk generation, timing progression, and metadata output.
- **Unit Test Suite (`tests/`)**: 45 passing unit tests covering valid paths, invalid parameters, empty chunks, corrupt unaligned payloads, sequence ordering, and schema serialization.

---

## 2. Project Structure

```
AI Voice Bot/
├── .gitignore               # Ignores bytecode, caches, environments, recordings, secrets
├── README.md                # Project documentation and usage guide
├── PULL_REQUEST.md          # GitHub Pull Request description with test outputs
├── DAILY_PROGRESS_REPORT.md # Daily task comment logs for Day 1 through Day 7
├── src/
│   ├── __init__.py
│   ├── schemas/
│   │   ├── __init__.py      # Re-exports canonical contracts
│   │   └── audio.py         # AudioFormat, AudioChunk, AudioError defined once
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── chunker.py       # Deterministic AudioChunker
│   │   └── mock_source.py   # MockMicrophone emitting AudioChunks
│   └── cli.py               # Single documented CLI demo
└── tests/
    ├── __init__.py
    ├── test_schemas.py      # Schema happy path & property tests
    ├── test_audio_errors.py # Invalid, empty, and corrupt chunk tests
    ├── test_chunker.py      # Deterministic chunking & replay tests
    └── test_mock_source.py  # Mock microphone streaming & determinism tests
```

---

## 3. Schemas Contract Specification

| Schema | Field | Type | Units | Constraints / Description |
| :--- | :--- | :--- | :--- | :--- |
| **`AudioFormat`** | `sample_rate` | `int` | Hz | Must be in supported list (`8000`, `11025`, `12000`, `16000`, `22050`, `24000`, `32000`, `44100`, `48000`, `96000`). Default `16000`. |
| | `channels` | `int` | Count | Must be `1` (mono) or `2` (stereo). Default `1`. |
| | `sample_width`| `int` | Bytes/Sample | Must be `1`, `2`, or `4`. Default `2` (16-bit PCM). |
| | `encoding` | `str` | Codec ID | Supported codec compatible with sample width (`pcm_u8`, `pcm_s8`, `pcm_s16le`, `pcm_s16be`, `pcm_s32le`, `pcm_s32be`, `pcm_f32le`, `pcm_f32be`). |
| **`AudioChunk`** | `sequence_id` | `int` | Counter | Strictly non-negative integer (`>= 0`), monotonically increasing. |
| | `timestamp` | `float` | Seconds | Strictly non-negative, finite (`>= 0.0`, rejects NaN/inf), advancing by chunk duration. |
| | `data` | `bytes` | Raw PCM | Non-empty binary bytes (bytearray input is defensively copied); byte length must be exact multiple of `format.frame_size`. |
| | `format` | `AudioFormat` | Contract | Valid `AudioFormat` instance. |
| | `metadata` | `dict` | Key/Value | Optional contextual metadata. |
| **`AudioError`** | `message` | `str` | Text | Human-readable explanation of error. |
| | `code` | `str` | Code | Standardized machine-readable error code (`INVALID_SAMPLE_RATE`, `EMPTY_CHUNK_DATA`, `CORRUPT_CHUNK_DATA`, `INVALID_ENCODING`, etc.). |
| | `request_id` | `str` | Tracking ID | Optional correlation tracking ID per Doc 04 section 5. |
| | `details` | `dict` | Key/Value | Contextual debugging dictionary. |

---

## 4. Installation & Setup

> **Note on Zero-Dependency Execution:** The core audio pipeline, schemas, mock microphone, CLI demo, and entire unit test suite run using **Python standard library only** (no external packages or `pip install` required). Installing `requirements.txt` is **only required for the optional FastAPI web visualizer dashboard** (`src/server.py`).

Set up the project using a Python virtual environment:

1. **Create a virtual environment:**
   ```powershell
   python -m venv venv
   ```

2. **Activate the virtual environment:**
   - **Windows (PowerShell):**
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **Windows (CMD):**
     ```cmd
     venv\Scripts\activate.bat
     ```
   - **Linux / macOS:**
     ```bash
     source venv/bin/activate
     ```

3. **Install optional web visualizer dependencies (FastAPI & Uvicorn):**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Quick execution summary:**
   - **Run CLI Demo (Zero-install):** `python -m src.cli --short`
   - **Run Unit Tests (Zero-install):** `python -m unittest discover tests -v`
   - **Run Web Dashboard (Requires requirements.txt):** `python -m src.server` (visit `http://localhost:8000`)

---

## 5. How to Run the CLI Demo

*(Note: The CLI demo uses a synthetic mock audio source for testing and local simulation. No physical microphone hardware is needed or captured.)*

Run the CLI demo with a single command from your terminal:

```powershell
python -m src.cli
```

### Command Options:

```text
--short              Run a quick short demo (5 chunks / 100 ms)
--realtime           Simulate real-time streaming pacing
--duration FLOAT     Total stream duration in seconds (default: 1.0)
--chunk-ms FLOAT     Chunk duration in milliseconds (default: 20.0 ms)
--sample-rate INT    Audio sample rate in Hz (default: 16000)
--channels INT       Number of channels: 1 (mono) or 2 (stereo) (default: 1)
--frequency FLOAT    Synthetic tone frequency in Hz (default: 440.0)
```

### Simple Example Commands:

```powershell
# 1. Quick short demo (fast 5 chunks / 100ms)
python -m src.cli --short

# 2. Real-time simulation mode (simulates live streaming pacing)
python -m src.cli --duration 0.5 --realtime

# 3. Custom sample rate and stereo channels (e.g. 48kHz stereo)
python -m src.cli --duration 0.2 --sample-rate 48000 --channels 2
```

---

## 6. How to Run the Unit Tests

Execute the comprehensive test suite with Python's built-in test runner (no third-party dependencies required):

```powershell
python -m unittest discover tests -v
```

All 45 unit tests pass, validating:
1. Valid schema creation and metrics calculations.
2. Rejection of invalid sample rates (negative, zero, non-integer, unsupported rates).
3. Rejection of invalid channel counts (zero, negative, 3+ channels).
4. Rejection of invalid chunk sequence IDs and timestamps (including finite checking for NaN / infinity).
5. Rejection of empty chunk data (`b""` -> `EMPTY_CHUNK_DATA`).
6. Rejection of corrupt / unaligned byte lengths (`CORRUPT_CHUNK_DATA`).
7. Determinism: identical outputs across multiple chunker and mock source runs.
8. Support for 1, 2, and 4-byte sample widths in `MockMicrophone` with accurate byte counts and zero drift.
9. Stream overshoot protection preventing sample rounding drift at non-standard rates (e.g. 22050 Hz).
10. Defensive copy of mutable `bytearray` inputs to preserve `AudioChunk` immutability.
11. Robust error wrapping in `from_dict()` for missing keys, corrupt base64, and non-dict payloads.
12. Required field validation in `AudioFormat.from_dict()` preventing silent default assignments.
13. Strict monotonic sequence ID and timestamp stream ordering validation (`AudioChunker.validate_sequence`).
14. Encoding compatibility validation against sample widths (rejecting invalid names like `"banana"`).
15. API error dictionary serialization with `request_id` per Doc 04, section 5.

---

## 7. How to Run the Interactive Web Visualizer Dashboard

Start the local visualizer dashboard server:

```powershell
python -m src.server
```

Then open your browser and navigate to:
```
http://localhost:8000
```

Features included in the dashboard:
- **Real-Time Audio Waveform:** HTML5 Canvas visualizer rendering live PCM chunks.
- **Start / Stop Stream & Clear:** Real-time Server-Sent Events (SSE) streaming with live metric meters.
- **AudioChunks Table:** Real-time log of received chunks showing sequence IDs, timestamps, byte sizes, and formats.
- **Dynamic Unit Test Runner:** Runs the 45-test suite on demand and displays actual test execution results.


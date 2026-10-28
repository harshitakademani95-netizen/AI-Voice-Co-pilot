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
- **Unit Test Suite (`tests/`)**: 30 passing unit tests covering valid paths, invalid parameters, empty chunks, and corrupt unaligned payloads.

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
| **`AudioFormat`** | `sample_rate` | `int` | Hz | Must be in supported list (`8000`, `16000`, `22050`, `24000`, `32000`, `44100`, `48000`, `96000`). Default `16000`. |
| | `channels` | `int` | Count | Must be `1` (mono) or `2` (stereo). Default `1`. |
| | `sample_width`| `int` | Bytes/Sample | Must be `1`, `2`, or `4`. Default `2` (16-bit PCM). |
| | `encoding` | `str` | Codec ID | Non-empty string. Default `"pcm_s16le"`. |
| **`AudioChunk`** | `sequence_id` | `int` | Counter | Strictly non-negative integer (`>= 0`), monotonically increasing. |
| | `timestamp` | `float` | Seconds | Strictly non-negative (`>= 0.0`), advancing by chunk duration. |
| | `data` | `bytes` | Raw PCM | Non-empty binary bytes; byte length must be exact multiple of `format.frame_size`. |
| | `format` | `AudioFormat` | Contract | Valid `AudioFormat` instance. |
| | `metadata` | `dict` | Key/Value | Optional contextual metadata. |
| **`AudioError`** | `message` | `str` | Text | Human-readable explanation of error. |
| | `code` | `str` | Code | Standardized machine-readable error code (`INVALID_SAMPLE_RATE`, `EMPTY_CHUNK_DATA`, `CORRUPT_CHUNK_DATA`, etc.). |
| | `details` | `dict` | Key/Value | Contextual debugging dictionary. |

---

## 4. How to Run the CLI Demo

Run the CLI demo with a single command from the project root:

```powershell
python -m src.cli
```

### Options:

```
--duration FLOAT     Total stream duration in seconds (default: 1.0)
--chunk-ms FLOAT     Chunk duration in milliseconds (default: 20.0)
--sample-rate INT    Audio sample rate in Hz (default: 16000)
--channels INT       Number of channels: 1 (mono) or 2 (stereo) (default: 1)
--frequency FLOAT    Synthetic tone frequency in Hz (default: 440.0)
--realtime           Simulate real-time hardware mic pacing
```

### Example Runs:

```powershell
# 1. Quick 100ms stream verification (5 chunks of 20ms)
python -m src.cli --duration 0.1 --chunk-ms 20

# 2. High fidelity 48kHz stereo stream
python -m src.cli --duration 0.2 --sample-rate 48000 --channels 2 --chunk-ms 20

# 3. Real-time microphone pacing simulation
python -m src.cli --duration 0.5 --realtime
```

---

## 5. How to Run the Unit Tests

Execute the comprehensive test suite with Python's built-in test runner:

```powershell
python -m unittest discover tests -v
```

All 30 unit tests pass, validating:
1. Valid schema creation and metrics calculations.
2. Rejection of invalid sample rates (negative, zero, non-integer, unsupported rates).
3. Rejection of invalid channel counts (zero, negative, 3+ channels).
4. Rejection of invalid chunk sequence IDs and timestamps.
5. Rejection of empty chunk data (`b""` -> `EMPTY_CHUNK_DATA`).
6. Rejection of corrupt / unaligned byte lengths (`CORRUPT_CHUNK_DATA`).
7. Determinism: identical outputs across multiple chunker and mock source runs.

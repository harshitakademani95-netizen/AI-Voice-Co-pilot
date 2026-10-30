# AI-Voice-Co-pilot
An AI-powered voice assistant that understands spoken commands and answers user queries using artificial intelligence. It uses speech recognition and text-to-speech technology to enable natural voice-based interactions.

**Team**: SDE 3  
**Sprint / Duration**: Week 1 (Day 1 – Day 7 Foundation & First Vertical Slice)  
**Contributions**:
- **Workstream W1 – Audio and VAD Foundation** (Developer: Harshita G Kademani)
- **Workstream W3 – Context & Reasoning** (Developer: Amruta A J)
- **Status**: Completed, Validated & Harmonized (99/99 Unit Tests Passing: 45 W1 Audio Tests + 54 W3 Context Tests)

---

# Directory Structure

```text
.
├── src/
│   ├── __init__.py
│   ├── audio/                  # [W1] Audio ingestion and chunking pipeline
│   │   ├── __init__.py
│   │   ├── chunker.py          # Deterministic AudioChunker
│   │   └── mock_source.py      # Deterministic MockMicrophone emitting AudioChunks
│   ├── schemas/                # [W1] Audio foundation schemas
│   │   ├── __init__.py
│   │   └── audio.py            # AudioFormat, AudioChunk, AudioError defined once
│   ├── cli.py                  # [W1] Interactive single-command audio streaming CLI
│   ├── server.py               # [W1] Optional audio FastAPI visualizer backend
│   ├── static/                 # [W1] Audio visualizer dashboard (index.html)
│   ├── context/                # [W3] Context schemas & synthetic fixtures
│   │   ├── __init__.py
│   │   ├── schemas.py          # Core context Pydantic models
│   │   └── fixtures.py         # Synthetic fixtures (capture disabled by default)
│   ├── prompts/                # [W3] Prompt registry & prompt injection defense
│   │   ├── __init__.py
│   │   └── versioned_prompts.py
│   └── reasoning/              # [W3] Deterministic reasoning & grounding
│       ├── __init__.py
│       └── mock_engine.py
│
├── tests/
│   ├── __init__.py
│   ├── test_audio_schemas.py   # [W1] AudioFormat & AudioChunk unit tests
│   ├── test_audio_errors.py    # [W1] AudioError, corrupt & empty chunk tests
│   ├── test_chunker.py         # [W1] Chunker & sequence validation tests
│   ├── test_mock_source.py     # [W1] Mock microphone & sample width tests
│   ├── test_schemas.py         # [W3] Context & reasoning schema tests (19 tests)
│   ├── test_synthetic.py       # [W3] Synthetic fixtures & safety defaults (4 tests)
│   ├── test_mock_reasoning.py  # [W3] Deterministic reasoning & safety gates (22 tests)
│   └── test_prompts.py         # [W3] Prompt versioning & injection tests (9 tests)
│
├── web/                        # [W3] Context web dashboard
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── demo.py                     # [W3] Interactive reasoning demonstration script
├── run_tests.py                # Standalone test runner (runs all 99 tests)
├── server.py                   # [W3] Localhost development server (port 8000)
├── DAILY_PROGRESS_REPORT.md    # [W1] Daily task logs for Day 1 through Day 7
├── PULL_REQUEST.md             # [W1] Detailed PR documentation & test outputs
├── requirements.txt            # Dependency specification (pydantic, fastapi, uvicorn)
├── .gitignore                  # Repository hygiene ignores
└── README.md                   # Complete technical documentation
```

---

# Part 1: Workstream W1 – Audio and VAD Foundation

**Developer**: Harshita G Kademani  
**Workstream**: W1 – Audio and VAD  
**Test Suite**: 45 Automated Unit Tests (100% Passing)

## 1. Overview & Architecture

This module delivers the **Week 1 foundation and first vertical slice** for the audio ingestion pipeline. It adheres strictly to the System Design Document (SDD) and Product Requirements Document (PRD):

- **Canonical Audio Schemas (`src/schemas/audio.py`)**: Single source of truth for downstream VAD, STT (Whisper), and agent workflows:
  - `AudioFormat`: Audio format metadata (sample rate in Hz, channel count, bit depth, encoding).
  - `AudioChunk`: Discrete audio frame slice with monotonically increasing `sequence_id`, precise `timestamp` in seconds, raw binary PCM payload, duration calculations, and serialization.
  - `AudioError`: Standardized error exception conforming to the SDD error format (`{"error": {"code": "...", "message": "...", "request_id": "...", "details": {...}}}`).
- **Deterministic Audio Chunker (`src/audio/chunker.py`)**: Slices continuous byte streams into fixed-duration `AudioChunk`s with strict frame alignment validation and reproducible outputs.
- **Deterministic Mock Microphone Source (`src/audio/mock_source.py`)**: Generates deterministic synthetic audio streams (16-bit linear PCM) for testing and pipeline integration without requiring physical microphone hardware.
- **Single-Command CLI Demo (`src/cli.py`)**: Real-time or batch streaming CLI demonstrating sequential chunk generation, timing progression, and metadata output.
- **Optional FastAPI Web Visualizer (`src/server.py` + `src/static/index.html`)**: Interactive browser visualizer with real-time waveform rendering and chunk metrics.

## 2. Audio Schemas Specification

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

## 3. How to Run W1 Audio Features

### CLI Demonstration
```powershell
# Short 100ms quick demo
python -m src.cli --short

# Full 1.0s real-time streaming simulation
python -m src.cli --realtime --duration 1.0
```

### Optional FastAPI Web Visualizer
```powershell
python -m src.server
```
Navigate to [http://localhost:8000](http://localhost:8000) for real-time waveform visualization.

---

# Part 2: Workstream W3 – Context & Reasoning

**Developer**: Amruta A J  
**Workstream**: W3 – Context & Reasoning  
**Test Suite**: 54 Automated Unit Tests (100% Passing)

## 1. Overview & Scope

This module establishes the foundational **Context and Reasoning Layer** for the AI Voice Co-Pilot:
1. **Context Schemas**: Strongly-typed Pydantic models (`ScreenContext`, `ContextItem`, `SourceReference`, `ReasoningRequest`, `ReasoningResult`) with strict schema validation (`extra="forbid"`), length limits, pattern enforcement, and timezone-aware datetimes.
2. **Synthetic Context Fixtures**: Fictional developer and document workspace fixtures with **screen capture disabled by default** (`capture_enabled=False`, enforced by model validators).
3. **Deterministic Mock Reasoning**: A predictable, repeatable reasoning engine that produces grounded responses with source citations, risk categorization (Categories A, B, C, D), Human-in-the-Loop safety gates, and structured error handling (`reason_safe`).
4. **Hardened Versioned Prompts & Security Boundaries**: Immutable prompt templates that strictly separate **trusted system instructions** from **untrusted contextual content**, escaping HTML entities (`&`, `<`, `>`, `"`, `'`) and neutralizing section headers to prevent prompt injection and XML boundary breakouts.

## 2. Context Schemas Summary

| Schema | Field | Type | Default | Constraints / Validation Rules | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SourceReference` | `source_id` | `str` | *Required* | `min_length=1` | Identifier of referenced context item. |
| `SourceReference` | `source_type` | `str` | *Required* | `min_length=1` | Category (`code`, `terminal`, `document`, `screen`). |
| `SourceReference` | `confidence_score`| `float` | `1.0` | `0.0 <= score <= 1.0` | Confidence level of cited source. |
| `ScreenContext` | `capture_enabled` | `bool` | `False` | **Must be False** | Enforced by validator: live hardware capture disabled. |
| `ScreenContext` | `is_synthetic` | `bool` | `True` | **Must be True** | Enforced by validator: only synthetic frames allowed. |
| `ContextItem` | `item_id` | `str` | *Required* | `min_length=1` | Unique context item identifier. |
| `ContextItem` | `content` | `str` | *Required* | `max_length=100_000` | Untrusted contextual content payload. |
| `ReasoningRequest` | `request_id` | `str` | *Required* | `min_length=1` | Unique end-to-end trace ID. |
| `ReasoningRequest` | `user_query` | `str` | *Required* | `1 <= len <= 2000` | Spoken or typed user question/command. |
| `ReasoningRequest` | `context_items` | `List[ContextItem]` | `[]` | `max_length=50`, unique IDs | Ingested context items. |
| `ReasoningResult` | `status` | `Literal` | `"success"` | `"success"`, `"error"`, `"needs_clarification"` | Outcome status of reasoning pipeline. |
| `ReasoningResult` | `risk_level` | `RiskCategory`| `CATEGORY_A` | `A`, `B`, `C`, `D` | PRD Risk classification. |
| `ReasoningResult` | `requires_approval`| `bool` | `False` | **Auto-enforced for C & D** | Human-in-the-loop approval gate. |

## 3. How to Run W3 Context & Reasoning Features

### Interactive Demonstration
```powershell
python demo.py
```

### Localhost Server
```powershell
python server.py
```

---

# Installation, Testing & Verification

### 1. Installation
```powershell
python -m pip install -r requirements.txt
```

### 2. Running All Automated Unit Tests (99 Tests)
Run via standard unittest discovery:
```powershell
python -m unittest discover tests -v
```

Or run via the structured test runner:
```powershell
python run_tests.py
```

### Execution Results:
```text
SUMMARY: Ran 99 tests in 0.058s
Passed: 99
Failures: 0
Errors: 0
Status: ALL TESTS PASSED [OK]
```
*(45 tests from Workstream W1 Audio & VAD + 54 tests from Workstream W3 Context & Reasoning)*

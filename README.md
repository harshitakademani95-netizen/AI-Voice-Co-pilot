# AI Voice Co-Pilot - Speech-to-Text Pipeline Foundation (Workstream W2)

[![CI - Test Suite](https://img.shields.io/badge/pytest-43%20passed-brightgreen.svg)]()
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![Workstream](https://img.shields.io/badge/workstream-W2%20Speech--to--Text-orange.svg)]()
[![Team](https://img.shields.io/badge/team-SDE%203-purple.svg)]()

> **Engineer:** Disha D K (SDE 3)  
> **Workstream:** W2 – Speech-to-Text Foundation (Week 1, Day 1–Day 7)  
> **Status:** Completed & Ready for Review  
> **Branch:** `feature/w2-speech-to-text-foundation`

---

## 1. Overview & Architecture

This package implements the foundation and first vertical slice of the **AI Voice Co-Pilot** Speech-to-Text (STT) pipeline. Designed strictly against the PRD (`01. PRD`), System Design Document (`02. SDD`), and API Specifications (`04. API Specifications`), this module provides:

1. **Transcript Schemas (`TranscriptSegment`, `TranscriptEvent`)**:
   - Single authoritative source of truth defined once in `src/voice_stt/schemas.py`.
   - Explicit constraints: timestamps in seconds, normalized confidence `[0.0, 1.0]`, ISO language tags, structured error objects, and word-level timings.
   - Strict rejection of invalid payloads with human-readable error descriptions.
2. **Provider-Neutral Adapter (`BaseSTTAdapter`)**:
   - Provider-agnostic interface allowing real engines (Whisper, Deepgram, Google Cloud STT) or test doubles to be swapped without changing downstream orchestration.
   - Fully runnable in mock mode with **no external API keys, credentials, or network dependencies**.
3. **Deterministic Fake Transcriber (`DeterministicFakeTranscriber`)**:
   - Guarantees: **identical audio chunk input sequences produce 100% bit-for-bit identical transcript events**.
   - Simulates streaming interim hypotheses and finalized segments.
   - Built-in error injection support for resilience testing.
4. **Ordered Segment Accumulator (`OrderedSegmentAccumulator`)**:
   - Aggregates streaming events into a strictly chronological, deduplicated transcript.
   - Cleanly isolates unconfirmed interim hypotheses from committed immutable segments.
   - Automatically handles out-of-order segment arrivals (re-orders on arrival).
5. **Day 7 Live Demonstration (`demo/live_demo.py`)**:
   - Complete chunk-to-transcript simulation with streaming terminal output and determinism audit.

---

## 2. Directory Structure

```text
AI Voice Co-Pilot/
├── .gitignore                      # Comprehensive ignores (no recordings, venvs, secrets)
├── pyproject.toml                  # Package configuration, dependencies & pytest settings
├── requirements.txt                # Production and test dependencies
├── README.md                       # Workstream documentation
├── src/
│   └── voice_stt/
│       ├── __init__.py             # Public package exports
│       ├── schemas.py              # Day 1-2: TranscriptSegment, TranscriptEvent, AudioChunk, STTErrorDetail
│       ├── adapter.py              # Day 3-4: BaseSTTAdapter, STTAdapterConfig, STTAdapterStatus
│       ├── fake_transcriber.py     # Day 3-4: DeterministicFakeTranscriber (same input -> identical events)
│       └── accumulator.py          # Day 5-6: OrderedSegmentAccumulator (ordering, interim/final, dedup)
├── tests/
│   ├── conftest.py                 # Reusable test fixtures (audio chunks, segments, edge cases)
│   ├── test_schemas.py             # Schema boundary and invalid payload rejection tests
│   ├── test_adapter_and_fake.py    # Adapter interface and determinism verification tests
│   ├── test_accumulator.py         # Accumulator ordering, interim lifecycle, deduplication tests
│   └── test_end_to_end_flow.py     # End-to-end chunk-to-transcript integration tests
├── demo/
│   └── live_demo.py                # Day 7: Live chunk-to-transcript streaming demonstration
└── docs/
    └── PULL_REQUEST.md             # Complete GitHub Pull Request documentation with test output
```

---

## 3. Schema Data Contracts

### `TranscriptSegment`
| Field | Type | Units / Constraints | Description |
| :--- | :--- | :--- | :--- |
| `segment_id` | `str` | UUID string | Unique segment identifier |
| `text` | `str` | UTF-8 String | Transcribed text |
| `start_time` | `float` | Seconds (`>= 0.0`) | Onset timestamp from stream start |
| `end_time` | `float` | Seconds (`>= start_time`) | Offset timestamp from stream start |
| `confidence` | `float` | Normalized `[0.0, 1.0]` | Statistical transcription confidence |
| `is_final` | `bool` | Boolean | `True` for committed final; `False` for interim |
| `language` | `str` | ISO 639-1 / BCP-47 (`en`, `es`, etc.) | Spoken language tag |
| `words` | `List[WordTiming]`| List of word objects | Optional word-level alignments and confidences |

### `TranscriptEvent`
| Field | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `event_id` | `str` | UUID string | Unique event identifier |
| `event_type` | `TranscriptEventType`| `interim`, `final`, `error`, etc. | Nature of the stream event |
| `sequence_number`| `int` | Monotonic integer (`>= 0`) | Sequential position in session stream |
| `timestamp` | `float` | POSIX timestamp in seconds | Generation timestamp |
| `session_id` | `Optional[str]` | Alphanumeric string | Optional correlation identifier |
| `segment` | `Optional[TranscriptSegment]`| Required if `interim` or `final` | Transcribed segment payload |
| `error` | `Optional[STTErrorDetail]` | Required if `error` | Structured diagnostic error (SDD Section 5) |
| `metadata` | `Dict[str, Any]`| Key-value dictionary | Provider-neutral diagnostic telemetry |

---

## 4. Quickstart & Installation

### Setup Environment
```bash
# Create and activate virtual environment
python -m venv .venv

# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install package dependencies
pip install -r requirements.txt
```

---

## 5. Running Tests

Run the complete 43-test unit test suite:
```bash
pytest -v
```

All 43 unit tests cover normal operation, boundary values, invalid payload rejections, determinism audits, and lifecycle management.

---

## 6. Running the Day 7 Live Demo

Execute the streaming chunk-to-transcript simulation:
```bash
# Real-time streaming simulation with visual updates:
python demo/live_demo.py

# Non-interactive / CI fast execution:
python demo/live_demo.py --fast
```

Sample output:
```text
========================================================================
   AI Voice Co-Pilot (W2 - STT Foundation) - Day 7 Live Demonstration
   Author: Disha D K (SDE 3) | Workstream: Speech-to-Text Pipeline
   Mode: Mock / Deterministic (No paid API keys required)
========================================================================

[*] Initialized STT Adapter: deterministic-mock-v1
[*] Target Utterance Scenario: 2 phrases
[*] Streaming 20 audio chunks (100ms each) into adapter...
------------------------------------------------------------------------
  [STREAMING INTERIM] t=0.0s..0.1s | Why                                           (conf: 0.88)
  ...
  [COMMITTED FINAL ]  t=0.6s..0.7s | "Why is this application showing this error?" (conf: 0.96)
  ...
  [COMMITTED FINAL ]  t=1.3s..1.4s | "Explain the methodology shown on this page." (conf: 0.96)

------------------------------------------------------------------------
   ACCUMULATOR CONSOLIDATED TRANSCRIPT & METRICS
------------------------------------------------------------------------
  Total Committed Segments : 2
  Events Ingested          : 14
  Total Audio Duration     : 0.80 seconds
  Average Confidence       : 96.00%

  Full Transcript Reconstructed:
  >>> "Why is this application showing this error? Explain the methodology shown on this page."

------------------------------------------------------------------------
   DETERMINISM AUDIT (Pass 1 vs Pass 2 bit-for-bit check)
------------------------------------------------------------------------
  Event Count Pass 1 : 14
  Event Count Pass 2 : 14
  Exact Bit-for-Bit Match : PASSED (100% Deterministic)
========================================================================
   Day 7 Live Demonstration Complete! All criteria met.
========================================================================
```

---

## 7. Acceptance Criteria Checklist

- [x] **Single Schema Definition:** Both `TranscriptSegment` and `TranscriptEvent` are defined once in `src/voice_stt/schemas.py`.
- [x] **Field Documentation:** All fields documented with types, physical units (seconds, normalized confidence), and constraints.
- [x] **Payload Validation:** Clear validation errors on inverted timestamps, negative offsets, confidence out of `[0.0, 1.0]`, invalid language tags, and mismatched event states.
- [x] **Deterministic Transcriber:** Repeated execution with identical audio chunk inputs produces identical `TranscriptEvent` sequences.
- [x] **Provider-Neutral Interface:** `BaseSTTAdapter` requires no real provider or paid API keys.
- [x] **Ordered Accumulator:** Out-of-order segments automatically ordered chronologically; interim hypotheses cleanly separated from committed final segments.
- [x] **Test Suite Passing:** 43 comprehensive unit tests passing with 100% success rate.
- [x] **Feature Branch:** All development on `feature/w2-speech-to-text-foundation`; zero direct pushes to `main`.
- [x] **Zero Secrets / Personal Data:** `.gitignore` excludes audio recordings, secrets, `.env`, and virtual environments.
- [x] **Day 7 Live Demo:** `demo/live_demo.py` ready and verified.


# AI-Voice-Co-pilot
An AI-powered voice assistant that understands spoken commands and answers user queries using artificial intelligence. It uses speech recognition and text-to-speech technology to enable natural voice-based interactions.

---

# Speech-to-Text Subsystem (W2 – Speech-to-Text)

> **Engineer:** Disha D K (SDE 3)<br>
> **Workstream:** W2 – Speech-to-Text (Week 2 & Week 3, Days 8–21)<br>
> **Current Branch:** `feature/w2-speech-to-text-2`<br>
> **Test Status:** 180 / 180 Tests Passing (100% Pass Rate)

---

## 1. Overview & Architecture

The Speech-to-Text subsystem provides a production-grade, fault-tolerant orchestration and preprocessing engine. It accepts continuous audio streams from authentic or simulated audio sources, standardizes format contracts, transcribes speech through real-time adapters or deterministic test doubles, reconciles out-of-order and revised hypotheses, and dispatches structured event streams into the backend session repository.

### End-to-End Architectural Flow

```
[Audio Pipeline] (W1 Authentic)
   ├── MockAudioDevice / Physical Mic
   ├── AudioLifecycleController (RUNNING/PAUSED/STOPPED)
   ├── BoundedAudioBuffer (Capacity=100 chunks, Ring Drop Policy)
   └── MockVAD (Speech Detection & Event Transitions)
            │  AudioChunk (PCM 16kHz, mono, sequence_id, timestamps)
            ▼
[AudioSTTBridge] (Integration Layer)
   ├── Duplicate Chunk Suppression
   ├── Monotonic Sequence Tracking & Session ID Enrichment
   └── Lifecycle Cancellation Synchronization
            │
            ▼
[TranscriptionOrchestrator] (W2/W3 Engine)
   ├── Preprocessing (Resample, Downmix, Safe Normalize)
   ├── Primary STT Adapter (Mock / Cloud Speech Provider)
   ├── Fault-Tolerant Fallback Switch (Mock Provider Fallback on 429/503/Network)
   ├── In-Flight Cooperative Cancellation Token
   └── Confidence Threshold Guard (Default: 0.50)
            │  TranscriptEvents (INTERIM / REVISION / FINALIZATION / ERROR)
            ▼
[OrderedSegmentAccumulator] (Reconciliation & Ordering)
   ├── Multi-Level Deduplication (Event ID, Segment ID, Audio Boundaries)
   ├── Chronological Arrival Reordering (Audio Start/End Times)
   ├── Hypothesis Replacement (Interim/Revision superseded by Finalization)
   ├── Late Delivery Discard & Cancellation Cleanup
   └── Defensive Low-Confidence Quarantine
            │
            ▼
[BackendEventStreamBridge] (W5 Event Dispatch)
   ├── Canonical STT-to-Backend Event Mapping
   ├── Fault Isolation & Duplicate Emission Suppression
   └── InMemorySessionRepository (SSE & Event History)
```

---

## 2. Core Features: Week 2 vs. Week 3

| Capability | Week 2 Implementation (Days 8–14) | Week 3 Enhancements (Days 15–21) |
|---|---|---|
| **Audio Processing** | Stereo downmix, linear resampling, peak normalization | Full integration with authentic W1 `AudioPipeline` and bounded buffer |
| **Event Types** | `INTERIM`, `FINAL`, `STREAM_COMPLETED`, `ERROR` | Added `REVISION` (in-flight text correction) and `FINALIZATION` (immutable committed text) |
| **Session Isolation** | Basic session ID tagging | Strict validation (non-empty, non-whitespace), rejection of foreign session events |
| **Confidence Scoring** | Confidence score capture on segments | Configurable threshold (`min_confidence_threshold=0.50`); defensive quarantine of low-confidence text |
| **Cancellation** | Timeout-based worker thread termination | Cooperative in-flight cancellation (`cancel()`), atomic interim hypothesis purge, chunk rejection |
| **Resilience & Fallback** | Bounded retries with exponential backoff | Automatic provider fallback on quota (HTTP 429), connection loss, or service outage (HTTP 503) |
| **Backend Integration** | Isolated STT accumulator | `BackendEventStreamBridge` dispatching to authentic W5 `InMemorySessionRepository` |
| **Test Baseline** | 106 tests passing | **180 tests passing** across 15 comprehensive test suites |

---

## 3. Week 3 Feature Details

### A. Revision and Finalization Events (`src/voice_stt/schemas.py`)
- **`TranscriptEventType.REVISION` (`"revision"`):** Dispatched when a speech provider updates tentative interim words with higher accuracy before sentence boundary completion. Replaces active in-flight hypotheses without word duplication.
- **`TranscriptEventType.FINALIZATION` (`"finalization"`):** Dispatched upon voice boundary detection or end-of-speech. Commits the segment to immutable historical memory and atomically clears active interim text.

### B. Session Management & Validation
- Orchestrators and accumulators enforce strict string session identifiers (`session_id`).
- Empty strings, whitespace-only strings, or non-string inputs immediately raise `STTValidationError`.
- The accumulator rejects events tagged with mismatched session IDs, preventing cross-session contamination in multi-tenant environments.

### C. Configurable Confidence Thresholding
- **Default Threshold:** `0.50` (configurable between `0.0` and `1.0`).
- Segments with confidence $\ge 0.50$ are committed to the public transcript.
- Low-confidence segments ($< 0.50$) are quarantined in `_low_confidence_segments`, preserving audit and debugging telemetry while preventing inaccurate text from polluting downstream agent context.

### D. Cooperative In-Flight Cancellation
- Invoking `orchestrator.cancel()` sets internal cancellation tokens on both the orchestrator and the underlying adapter.
- In-flight audio chunk processing is aborted immediately, and late provider responses arriving after cancellation are discarded.
- In-flight interim hypotheses are atomically purged via `accumulator.clear_interim()`.

### E. Automatic Mock Provider Fallback
- Automatic fallback from a failing primary adapter to a secondary offline mock adapter:
  - **HTTP 429 / Rate Limit / Quota Exceeded:** Triggers fallback.
  - **Network Connection Failures:** (Connection refused, connection reset, broken pipe) Triggers fallback.
  - **HTTP 503 / Provider Unavailable:** Triggers fallback.
  - **Exhausted Timeouts:** Triggers fallback.
- **Non-Fallback Errors:** Programming errors (`ValueError`, `TypeError`), validation errors, authentication failures, and cancelled states are preserved and never masked.
- Fallback activation preserves the active session ID, chunk sequence counters, and sanitizes credentials.

### F. Audio-to-STT Integration (`AudioSTTBridge`)
- Connects the authentic Week 1 `AudioPipeline` (including `MockAudioDevice`, `BoundedAudioBuffer`, and `MockVAD`) directly to `TranscriptionOrchestrator`.
- Performs chunk-level sequence deduplication and timestamp synchronization.
- Propagates VAD speech transitions (e.g. `VADEventType.SPEECH_END`) to automatically trigger chunk finalization.

### G. Backend Event-Stream Integration (`BackendEventStreamBridge`)
- Forwards STT events to the Week 5 `InMemorySessionRepository`:
  - `TranscriptEventType.INTERIM` $\rightarrow$ `"voice_stt.interim"`
  - `TranscriptEventType.REVISION` $\rightarrow$ `"voice_stt.revision"`
  - `TranscriptEventType.FINALIZATION` $\rightarrow$ `"voice_stt.finalization"`
  - `TranscriptEventType.ERROR` $\rightarrow$ `"voice_stt.error"`
- Features fault isolation: backend repository failures or missing sessions never crash the STT pipeline or corrupt accumulated transcripts.

---

## 4. Error Models & API Specifications

Two complementary error envelopes are maintained to serve distinct architectural layers:
1. **`STTErrorDetail` (`src/voice_stt/schemas.py`):**
   Internal STT domain error model conforming to API Specifications (doc 04, Section 5). Used for transcript events, orchestrator telemetry, and accumulator error history. Includes automatic credential masking for API keys (`sk-...`) and bearer tokens.
2. **`ErrorPayload` (`src/models/error.py`):**
   W5 Backend HTTP REST API typed response envelope. Bridges domain STT errors to public HTTP clients via `ErrorPayload.from_stt_error()`.

---

## 5. Running the Demonstrations

### Dedicated Week 3 Full Integration Demo (10 Scenarios)
Demonstrates audio pipeline capture, interim, revision, finalization, session isolation, low-confidence quarantine, cancellation, network fallback, quota fallback, and backend repository streaming:

```powershell
.\.venv\Scripts\python.exe examples/week3_stt_integration_demo.py
```

### Day 14 Audio Preprocessing & Mock STT Demo
Demonstrates synthetic 48kHz stereo downmixing, linear resampling, and peak normalization:

```powershell
.\.venv\Scripts\python.exe examples/day14_stt_demo.py
```

---

## 6. Running the Test Suite

Execute the complete 180-test test suite across all Week 2 and Week 3 modules:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

### Test Suite Breakdown (180 Tests Total)

| Test Suite | Focus Area | Tests |
|---|---|---|
| `test_day9_end_to_end.py` | Week 2 Day 9: End-to-end streaming transcription | 10 |
| `test_day10_ordering_and_dedup.py` | Week 2 Day 10: Chronological sorting & deduplication | 15 |
| `test_day11_interim_final_reconciliation.py` | Week 2 Day 11: Interim-to-final hypothesis replacement | 10 |
| `test_day12_timeout_retries_errors.py` | Week 2 Day 12: Bounded retries, timeouts & errors | 23 |
| `test_day13_audio_preprocessing.py` | Week 2 Day 13: Downmix, resample & normalize | 16 |
| `test_day14_adapter_contract.py` | Week 2 Day 14: STT adapter lifecycle contracts | 12 |
| `test_day14_event_contract.py` | Week 2 Day 14: Transcript event schemas & serialization | 10 |
| `test_orchestrator.py` | Base orchestrator unit verification | 10 |
| `test_day15_revision_finalization.py` | Week 3 Day 15: Revision & Finalization event flow | 9 |
| `test_day16_session_confidence.py` | Week 3 Day 16: Session isolation & confidence quarantine | 13 |
| `test_day17_cancellation.py` | Week 3 Day 17: In-flight cancellation & state cleanup | 10 |
| `test_day18_fallback.py` | Week 3 Day 18: Quota & network provider fallback | 10 |
| `test_day19_audio_stt_integration.py` | Week 3 Day 19: Authentic audio pipeline to STT bridge | 10 |
| `test_day20_backend_event_integration.py` | Week 3 Day 20: STT to backend session repository bridge | 11 |
| `test_fallback_classification.py` | Week 3 Code Quality: Structured fallback & error models | 11 |

---

## 7. Known Technical Limitations

1. **CPython Thread Interruption:**
   In standard Python, executing threads cannot be forcefully killed from another thread. Worker timeouts and cancellations use explicit `ThreadPoolExecutor` shutdown with cooperative cancellation checks (`is_cancelled`).
2. **Linear Interpolation Resampling:**
   Resampling uses first-order linear interpolation rather than sinc/polyphase anti-aliasing to keep the implementation purely within the standard library without binary wheels (`numpy`/`scipy`).
3. **Deterministic Mock Mode:**
   The mock demonstration scripts and test suites use deterministic test doubles (`DeterministicFakeTranscriber` and `MockAudioDevice`) operating 100% offline without live microphone hardware or external cloud costs.

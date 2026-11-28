# AI-Voice-Co-pilot
An AI-powered voice assistant that understands spoken commands and answers user queries using artificial intelligence. It uses speech recognition and text-to-speech technology to enable natural voice-based interactions.

---

# Week 2 – Speech-to-Text Implementation

> **Engineer:** Disha D K (SDE 3)<br>
> **Workstream:** W2 – Speech-to-Text (Week 2, Days 8–14)<br>
> **Status:** Completed & Verified (106 Week 2 Tests Passing)<br>
> **Target Branch:** `feature/w2-speech-to-text-1`

---

## 1. Overview of the Week 2 STT Pipeline

The Week 2 Speech-to-Text implementation builds directly on the foundational Week 1 contracts, providing a production-grade orchestration and preprocessing layer. It handles streaming audio ingestion, downmixing and resampling, safe amplitude normalization, bounded retries with exponential backoff, worker timeouts without caller-blocking, chronological reconciliation of out-of-order events, and duplicate suppression.

### End-to-End Pipeline Diagram

```
Audio Chunks → Audio Preprocessing → STT Orchestrator → Fake/Provider Adapter → Transcript Events → Ordered Accumulator → Final Transcript
```

---

## 2. Architecture & Component Responsibilities

### A. Transcription Orchestrator (`src/voice_stt/orchestrator.py`)
- **Lifecycle Management:** Coordinates session setup, per-session state resetting, and clean shutdown across components.
- **Provider-Neutral Ingestion:** Consumes `AudioChunk` dataclasses or raw PCM bytes and routes them through the configured preprocessor and adapter.
- **Resilience Engine:** Implements strict per-chunk timeout guards and bounded retries with exponential backoff for transient failures.
- **Streaming Coordination (`process_stream`):** Sequences continuous audio streams with one-item lookahead so terminating chunks cleanly flush active sentences. Handles closed state via normalized error events.

### B. Audio Preprocessor (`src/audio/preprocessing.py`)
- **Stereo-to-Mono Downmixing:** Averages dual-channel 16-bit PCM: `(left + right) // 2` with $[-32768, 32767]$ clamping.
- **Linear Interpolation Resampling:** Converts arbitrary input rates (e.g. 48kHz, 44.1kHz, 8kHz) to standard 16kHz without third-party C dependencies (`scipy`/`numpy`). Includes zero-copy fast-path when rates match.
- **Peak Normalization:** Elevates low-amplitude audio up to a configurable target peak ratio (default: 0.95), safely leaves silence unmodified, and clamps all samples to prevent clipping.

### C. Deterministic Fake Transcriber (`src/voice_stt/fake_transcriber.py`)
- **Zero-Dependency Mock Mode:** Operates 100% offline without network connections, cloud credentials, or paid APIs.
- **Scripted & Hash Modes:** Generates deterministic streaming events (`TranscriptEventType.INTERIM`, `TranscriptEventType.FINAL`, and `TranscriptEventType.STREAM_COMPLETED`).
- **Simulated Error Injection:** Configurable error injection at designated chunks to test recovery and fallback paths.

### D. Ordering & Duplicate Suppression (`src/voice_stt/accumulator.py`)
- **Chronological Sorting:** Inserts segments ordered by `start_time` (secondary: `end_time`), reconciling out-of-order deliveries.
- **Multi-Level Deduplication:** Suppresses duplicate `event_id`s, duplicate `segment_id`s, and identical audio boundaries. Preserves legitimate repeated utterances at distinct timestamps.

### E. Interim-to-Final Reconciliation
- **Hypothesis Replacement:** Tracks in-flight interim hypotheses and atomically clears them when finalized segments arrive covering the same audio span.
- **Late Interim Discard:** Safely discards delayed interim updates arriving after the corresponding audio span has been committed.

---

## 3. Configuration & Limitations

### Default Retry & Timeout Settings (`RetryConfig`)
- `max_retries`: `3` (maximum retry attempts on retryable failures).
- `retry_delay`: `0.0` s (base delay between retries; defaults to 0.0 for deterministic local testing).
- `backoff_factor`: `1.0` (multiplicative exponential backoff factor).
- `timeout_seconds`: `None` (optional timeout limit per operation; e.g. 2.0s).

### Known Technical Limitations
1. **Thread Timeout Termination Limitation:**
   In standard Python (CPython), an executing thread cannot be forcefully stopped or killed from the outside. To prevent the caller from blocking when a timeout occurs, `_execute_with_timeout` uses explicit `ThreadPoolExecutor` management with `executor.shutdown(wait=False, cancel_futures=True)`. The caller returns immediately within the configured timeout, but the worker thread finishes in the background. In production network adapters, native socket/HTTP timeouts or cooperative cancellation tokens must be used.
2. **Linear Interpolation Resampling Limitation:**
   Resampling uses first-order linear interpolation rather than a sinc/polyphase anti-aliasing filter to keep the codebase pure standard-library Python without binary wheels. For voice STT, vocal energy is concentrated below 4kHz, so this is sufficient for development and testing.
3. **Synthetic Audio & Fake Transcriber Disclaimer:**
   The Day 14 demonstration and mock tests use mathematically generated synthetic audio tones and a deterministic test double (`DeterministicFakeTranscriber`). **They do not perform actual speech recognition on human voices.**

---

## 4. How to Execute the Day 14 Demo

The end-to-end demonstration generates a synthetic 48kHz stereo fixture outside the repository in system temp, passes it through the preprocessor, orchestrates it with `DeterministicFakeTranscriber`, and outputs real-time events and telemetry.

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\python.exe examples/day14_stt_demo.py
```

---

## 5. How to Run the Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

# API Contract: Backend Audio & Transcription Gateways

## Overview
The Backend Gateway layer provides modular, thread-safe integration points connecting the core session management service to:
1. **Audio Module (`src.audio`)**: Continuous audio streaming, PCM validation, bounded ThreadPoolExecutor timeout enforcement, and frame-aligned chunking (`AudioChunker`, `MockMicrophone`).
2. **Transcription Module (`src.voice_stt`)**: Speech-to-text adapter integration, pluggable providers (`mock`, `deepgram`), exponential retry backoff, circuit breaker protection, and chronological transcript accumulation (`DeterministicFakeTranscriber`, `DeepgramSTTAdapter`, `OrderedSegmentAccumulator`).
3. **Session Orchestrator (`src.gateways.service`)**: End-to-end audio ingestion, synchronous/asynchronous transcription, and automatic `speech_transcript` event broadcasting to Server-Sent Events (SSE) queues.

---

## Gateway Endpoints

### 1. Gateway Status & Telemetry
- **Method**: `GET`
- **Paths**: `/api/v1/gateways/status` | `/gateways/status`
- **Tags**: `Gateways & Module Integration`
- **Response**: `200 OK`
```json
{
  "audio_gateway": {
    "gateway": "AudioGateway",
    "is_available": true,
    "circuit_state": "CLOSED",
    "total_calls": 12,
    "error_count": 0,
    "avg_latency_ms": 1.45,
    "last_success_at": "2026-11-18T15:00:00.000000+00:00",
    "total_chunks_produced": 36,
    "total_bytes_processed": 23040,
    "default_format": {
      "sample_rate": 16000,
      "channels": 1,
      "sample_width": 2,
      "encoding": "pcm_s16le"
    },
    "last_error": null
  },
  "transcription_gateway": {
    "gateway": "TranscriptionGateway",
    "is_available": true,
    "circuit_state": "CLOSED",
    "total_calls": 12,
    "error_count": 0,
    "avg_latency_ms": 2.10,
    "last_success_at": "2026-11-18T15:00:00.000000+00:00",
    "adapter_state": "ready",
    "adapter_model": "mock-stt-v1",
    "adapter_language": "en",
    "total_chunks_transcribed": 36,
    "total_events_emitted": 36,
    "active_accumulators_count": 1,
    "last_error": null
  },
  "health": {
    "status": "healthy",
    "audio_gateway": { "status": "healthy" },
    "transcription_gateway": { "status": "healthy" },
    "session_repository": { "status": "healthy" },
    "timestamp": "2026-11-18T15:00:00.000000+00:00"
  }
}
```

---

### 2. Audio Processing & Chunking
- **Method**: `POST`
- **Paths**: `/api/v1/audio/process` | `/audio/process`
- **Request Headers**:
  - `Content-Type: application/json`
  - `X-Correlation-ID: <optional-uuid>`
- **Request Body**:
```json
{
  "audio_base64": "<base64-encoded-pcm-bytes>",
  "format": "linear16",
  "sample_rate": 16000,
  "chunk_duration_ms": 20.0,
  "is_last": false
}
```
- **Response (`200 OK`)**:
```json
{
  "status": "success",
  "chunks_count": 2,
  "chunks": [
    {
      "sequence_id": 0,
      "duration_ms": 20.0,
      "format": {
        "sample_rate": 16000,
        "channels": 1,
        "encoding": "pcm_s16le"
      },
      "is_final": false,
      "byte_length": 640
    }
  ]
}
```
- **Error Responses**:
  - `400 Bad Request`: Invalid base64 or unsupported audio encoding.
  - `413 Payload Too Large`: Audio payload exceeds `MAX_AUDIO_BYTES` (1MB) or exceeds `MAX_CHUNKS_PER_REQUEST` (500).
  - `504 Gateway Timeout`: Audio chunking execution exceeds configured deadline.

---

### 3. Transcription Processing
- **Method**: `POST`
- **Paths**: `/api/v1/transcription/process` | `/transcription/process`
- **Request Body**:
```json
{
  "audio_base64": "<base64-encoded-pcm-bytes>",
  "session_id": "session-optional",
  "format": "linear16",
  "is_last": true
}
```
- **Response (`200 OK`)**:
```json
{
  "status": "success",
  "events_count": 1,
  "events": [
    {
      "event_id": "b18a2249-f0bd-4fa6-a36f-e300d603a146",
      "event_type": "final",
      "sequence_number": 0,
      "timestamp": 0.02,
      "segment": {
        "segment_id": "seg-001",
        "text": "Hello world",
        "start_time": 0.0,
        "end_time": 0.02,
        "confidence": 0.95,
        "is_final": true,
        "language": "en"
      }
    }
  ]
}
```
- **Error Responses**:
  - `503 Service Unavailable`: Circuit breaker is OPEN or downstream STT module unavailable.
  - `504 Gateway Timeout`: Transcription adapter call exceeds deadline.

---

### 4. Session Audio Ingestion (End-to-End Pipeline)
- **Method**: `POST`
- **Paths**: `/api/v1/sessions/{session_id}/audio` | `/sessions/{session_id}/audio`
- **Description**: Chunks incoming audio via `AudioGateway`, transcribes via `TranscriptionGateway`, accumulates segments in `OrderedSegmentAccumulator`, updates session metadata, and appends `speech_transcript` events to the active session for real-time SSE distribution.
- **Request Body**:
```json
{
  "audio_base64": "<base64-encoded-pcm-bytes>",
  "format": "linear16",
  "is_last": true,
  "correlation_id": "corr-voice-123"
}
```
- **Response (`200 OK`)**:
```json
{
  "session_id": "session-a1b2c3d4",
  "status": "success",
  "chunks_processed": 3,
  "events_count": 1,
  "transcript_events": [ ... ],
  "full_transcript": "Hello world"
}
```

---

### 5. Transcript Readback Endpoint
- **Method**: `GET`
- **Paths**: `/api/v1/sessions/{session_id}/transcript` | `/sessions/{session_id}/transcript`
- **Tags**: `Gateways & Module Integration`
- **Description**: Reads back aggregated transcript history and ordered segments for a specific session.
- **Response (`200 OK`)**:
```json
{
  "session_id": "session-a1b2c3d4",
  "full_transcript": "Hello voice copilot",
  "segments": [
    {
      "segment_id": "seg-001",
      "text": "Hello voice copilot",
      "start_time": 0.0,
      "end_time": 0.06,
      "confidence": 0.95,
      "is_final": true,
      "words": []
    }
  ],
  "chunks_processed": 3,
  "last_updated": "2026-11-18T15:01:23.456789+00:00"
}
```

---

### 6. Full End-to-End Pipeline (Day 21)
- **Method**: `POST`
- **Paths**: `/api/v1/sessions/{session_id}/pipeline` | `/pipeline/process`
- **Tags**: `Gateways & Module Integration`
- **Description**: Executes the complete 4-stage pipeline: Audio Gateway -> Transcription Gateway -> Reasoning Gateway -> Workflow Gateway Policy Evaluation.
- **Request Headers**:
  - `Content-Type: application/json`
  - `X-Request-ID: <string>`
  - `X-Correlation-ID: <string>`
- **Request Body**:
```json
{
  "audio_base64": "<base64-pcm-audio-or-null>",
  "user_query": "Optional query override",
  "format": "linear16",
  "sample_rate": 16000,
  "prompt_version": "v1.0.0"
}
```
- **Response (`200 OK`)**:
```json
{
  "session_id": "session-bedca5a7",
  "status": "completed | requires_approval",
  "approval_id": "appr-acc27d02c5",
  "audio_chunks_processed": 2,
  "chunks_count": 2,
  "transcript": "copilot copilot",
  "reasoning": {
    "request_id": "req-pipe-...",
    "status": "success",
    "response_text": "...",
    "action_required": false,
    "confidence": 0.95
  },
  "workflow": {
    "policy_evaluated": true,
    "requires_approval": false,
    "approval_id": null
  },
  "events_recorded": 6
}
```
- **Error Responses**:
  - `400 Bad Request`: Invalid audio base64 or empty query.
  - `401 Unauthorized`: Lacks valid credentials outside local boundary.
  - `429 Too Many Requests`: Sliding window rate limit exceeded (`Retry-After`).
  - `503 Service Unavailable`: Dependent module unavailable (`AUDIO_MODULE_UNAVAILABLE`, `TRANSCRIPTION_MODULE_UNAVAILABLE`, `REASONING_MODULE_UNAVAILABLE`, `WORKFLOW_MODULE_UNAVAILABLE`).
  - `504 Gateway Timeout`: Module processing exceeded deadline.

---

### 7. Event History Replay & Reconnection (Days 17-18)
- **Method**: `GET`
- **Paths**: `/api/v1/sessions/{session_id}/events` (Cursor replay) | `/api/v1/sessions/{session_id}/events/stream` (SSE)
- **Replay & Cursor Pagination**:
  - `cursor`: Event ID to paginate after.
  - `limit`: Max events to return (1-100).
- **SSE Stream & Reconnection**:
  - `Last-Event-ID`: Client reconnect header; replays missing events strictly after the specified event ID without duplicates.
  - `replay_only`: If `true`, closes connection immediately following history replay.

---

### 8. Health & Readiness Aggregation (Days 19-20)
- **Method**: `GET`
- **Paths**: `/api/v1/gateways/status`, `/ready`, `/api/v1/health`
- **Readiness (`/ready`)**:
  - Returns `200 OK` (`status: "ready"`) when all four modules (`audio`, `transcription`, `reasoning`, `workflow`) and the session repository are healthy.
  - Returns `503 Service Unavailable` (`status: "not_ready"`) if any single module fails.
- **Gateways Status (`/api/v1/gateways/status`)**:
  - Returns individual status (`healthy` / `unhealthy`), metrics, and latencies across each module gateway.
- **Error Responses**:
  - `404 Not Found`: Session does not exist (`SESSION_NOT_FOUND`).

---

## Standard Error Envelopes
All gateway routes conform to the unified system error envelope:
```json
{
  "error": {
    "code": "PAYLOAD_TOO_LARGE | GATEWAY_TIMEOUT | CIRCUIT_BREAKER_OPEN | TRANSCRIPTION_MODULE_UNAVAILABLE | AUDIO_EMPTY_DATA | UNSUPPORTED_AUDIO_FORMAT | SESSION_NOT_FOUND | INVALID_STATE_TRANSITION",
    "message": "Human-readable description",
    "request_id": "req-...",
    "correlation_id": "corr-...",
    "details": { ... }
  }
}
```

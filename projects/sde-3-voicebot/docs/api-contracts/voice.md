# API Contract: Voice Audio Transcription

### API Name
Voice Audio Transcription API

### HTTP Method
`POST`

### Endpoint
`/api/v1/voice/transcribe`

### Purpose
Converts user speech/audio input captured from the microphone into text for downstream natural language understanding and contextual AI reasoning (as specified in *04. API Specifications & Interface Contracts*, Section 3; *03. Technical Architecture & Design*, Section 3; and *01. Product Requirements Document*, Section 13.1).

---

### Request Headers
| Header | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `Content-Type` | `string` | Yes | `multipart/form-data` (for audio binary) or `application/json` (for base64/URL payload) `[TBD based on final voice pipeline]` |
| `X-Request-ID` | `string` | Optional | Unique request tracking identifier (auto-generated if omitted) |
| `X-Correlation-ID` | `string` | Optional | Distributed correlation identifier across pipeline services |
| `Authorization` | `string` | Optional | Bearer token (`JWT / OAuth` per Technical Architecture) `[TBD]` |

---

### Request Body
*Note: The exact binary or JSON structure for audio submission is pending finalization with the Voice team.*

**Expected JSON / Payload Example:**
```json
{
  "session_id": "session-001",
  "audio_format": "wav",
  "audio_content": "TBD (base64 encoded audio or multipart binary stream)",
  "language_code": "en-US"
}
```

---

### Response Body
**Example JSON (Success):**
```json
{
  "request_id": "req-001",
  "session_id": "session-001",
  "status": "completed",
  "transcript": "Explain this error in my terminal",
  "confidence": 0.98,
  "detected_language": "en"
}
```

---

### Status Codes

#### Success Codes
- `200 OK`: Audio successfully transcribed into text.

#### Error Codes
- `400 Bad Request`: Audio payload is missing, empty, or unreadable.
- `401 Unauthorized`: Missing or invalid authentication token.
- `404 Not Found`: The specified `session_id` does not exist.
- `422 Unprocessable Entity`: Audio format is not supported or violates payload size limits.
- `500 Internal Server Error`: Downstream speech-to-text service failure.

---

### Validation Rules
1. Audio input must be captured through an authorized microphone (PRD: FR-VOICE-001).
2. The payload must not be empty.
3. System must detect completion of spoken request (PRD: FR-VOICE-003).
4. Audio format must be compatible with the Whisper / STT engine (Architecture: Section 1).

---

### Authentication & Permission Requirements
- **Microphone Access Permission:** User must explicitly grant microphone recording permission (PRD: FR-VOICE-001, Section 19).
- **Service Authentication:** JWT / OAuth token verification where applicable (Architecture: Section 1).

---

### Approval Requirements
- **Not Applicable (Category A — Informational):** Capturing and transcribing audio is an informational input activity and does not require explicit human approval gates (PRD: Section 18).

---

### Implementation Status
- **Status:** `Planned`
- **Notes:** Not implemented in the Week 1 foundation backend. Week 1 provides the session state machine and mock route capability to simulate voice transcript events.


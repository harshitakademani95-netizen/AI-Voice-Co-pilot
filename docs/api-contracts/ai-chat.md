# API Contract: Multimodal AI Chat Processing

### API Name
Multimodal AI Chat Processing API

### HTTP Method
`POST`

### Endpoint
`/api/v1/ai/chat`

### Purpose
Processes user conversational requests by combining spoken/text intent, application context, visual screen data, and active session history to generate answers or determine required tool actions (as specified in *04. API Specifications & Interface Contracts*, Section 3 & Section 4; *02. System Design Document*, Section 5; and *01. Product Requirements Document*, Section 16).

---

### Request Headers
| Header | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `Content-Type` | `string` | Yes | `application/json` |
| `X-Request-ID` | `string` | Optional | Unique request tracking identifier (auto-generated if omitted) |
| `X-Correlation-ID` | `string` | Optional | Distributed correlation identifier across pipeline services |
| `Authorization` | `string` | Optional | Bearer token (`JWT / OAuth` per Technical Architecture) `[TBD]` |

---

### Request Body
*(Schema exactly as defined in API Specifications & Interface Contracts, Section 4)*

**Example JSON:**
```json
{
  "session_id": "session-001",
  "message": "Explain this error",
  "context_id": "context-001"
}
```

#### Field Specifications:
- `session_id` (`string`, required): Identifier of an existing active session.
- `message` (`string`, required): The transcribed spoken text or direct user prompt.
- `context_id` (`string`, optional): Identifier referencing captured application/screen context.

---

### Response Body
*(Schema exactly as defined in API Specifications & Interface Contracts, Section 4)*

**Example JSON:**
```json
{
  "request_id": "req-001",
  "status": "completed",
  "response": "The error indicates a missing import.",
  "requires_approval": false
}
```

#### Field Specifications:
- `request_id` (`string`): Tracking ID for the completed request.
- `status` (`string`): Execution state (`completed`, `in_progress`, `failed`).
- `response` (`string`): Natural language answer or guidance provided to the user.
- `requires_approval` (`boolean`): Set to `true` if the recommended next action involves sensitive or high-risk operations requiring user authorization; otherwise `false`.

---

### Status Codes

#### Success Codes
- `200 OK`: Request processed successfully; response text and approval status returned.

#### Error Codes
- `400 Bad Request`: Missing mandatory fields (`session_id` or `message`).
- `401 Unauthorized`: Missing or invalid authentication token.
- `404 Not Found`: Specified `session_id` or `context_id` does not exist.
- `422 Unprocessable Entity`: Input validation failure.
- `500 Internal Server Error`: LLM reasoning or downstream inference service failure.

---

### Validation Rules
1. `session_id` must match a session currently in the `active` state.
2. `message` must be a non-empty string.
3. System must fail-safe: when uncertain, it asks the user for clarification instead of guessing (SDD: Section 2).

---

### Authentication & Permission Requirements
- **User Authentication:** Valid JWT / OAuth token required to protect user information and conversational history (Architecture: Section 1; PRD: Section 19).

---

### Approval Requirements
- If the AI reasoning determines a tool action is needed, the action risk is classified (A, B, C, D).
- For Category C (e.g. modify files, send emails) and Category D (e.g. delete files, privileged operations), `requires_approval` will be set to `true`, and the action cannot execute until the user approves via `/api/v1/approvals` (PRD: Section 18; API Specs: Section 6, Rule 6).

---

### Implementation Status
- **Status:** `Planned`
- **Notes:** Not implemented in the Week 1 backend. Week 1 provides the session state machine and mock event dispatcher simulating AI agent events.


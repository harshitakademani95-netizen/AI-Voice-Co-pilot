# API Contract: Context Submission

### API Name
Application & Screen Context Submission API

### HTTP Method
`POST`

### Endpoint
`/api/v1/context`

### Purpose
Submits relevant workspace and screen context (active application, visible code/text, active window title, open document, or user query) to the Context Engine, enabling the AI to answer requests without requiring manual copying or window switching (as specified in *04. API Specifications & Interface Contracts*, Section 3; *02. System Design Document*, Section 4.4 & Section 5; and *01. Product Requirements Document*, Section 15).

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
*(Schema per System Design Document, Section 5)*

**Example JSON:**
```json
{
  "application": "VS Code",
  "screen": "...",
  "user_query": "Explain this error",
  "session_id": "session-001",
  "active_window": "TBD",
  "open_document": "TBD"
}
```

---

### Response Body
*(Schema per System Design Document, Section 5)*

**Example JSON:**
```json
{
  "context_id": "context-001",
  "relevant_context": "VS Code editor showing terminal error on line 42 with missing import statement.",
  "status": "processed"
}
```

---

### Status Codes

#### Success Codes
- `200 OK`: Context processed and filtered into relevant context successfully.

#### Error Codes
- `400 Bad Request`: Payload is malformed or missing required context fields.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: User permission denied for screen or window capture.
- `422 Unprocessable Entity`: Input parameters failed validation.
- `500 Internal Server Error`: Internal error while processing OCR or multimodal context.

---

### Validation Rules
1. System must capture only the required context, rather than continuously processing the entire screen (SDD: Section 3 & 4.3).
2. The Context Engine must remove unnecessary information before sending context to the AI (SDD: Section 5).
3. The system shall not assume all application information is available; if context cannot be reliably obtained, clarification must be requested (PRD: Section 15).

---

### Authentication & Permission Requirements
- **Screen Capture Authorization:** Screen/region capture is strictly gated by explicit user permission (PRD: FR-VISION-001, Section 19; SDD: Section 4.3).
- **Privacy Enforcement:** Minimize unnecessary screen data collection and storage of visual data (PRD: FR-VISION-006, Section 19).

---

### Approval Requirements
- **Not Applicable (Category A — Informational):** Submitting context for reasoning is classified as informational and does not trigger sensitive action approvals (PRD: Section 18).

---

### Implementation Status
- **Status:** `Planned`
- **Notes:** Not implemented in the Week 1 backend. Week 1 supports storing arbitrary context metadata inside the session model.


# API Contract: Human-in-the-Loop Approvals

### API Name
Human-in-the-Loop Approval Decision API

### HTTP Method
`POST`

### Endpoint
`/api/v1/approvals`

### Purpose
Allows the user to review, approve, or reject sensitive or high-risk tool operations before they are executed by the AI system (as specified in *04. API Specifications & Interface Contracts*, Section 3; *01. Product Requirements Document*, Section 18; *02. System Design Document*, Section 5; and *03. Technical Architecture & Design*, Section 7).

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
*(Schema per Safety & Approval Layer in System Design Document, Section 5)*

**Example JSON:**
```json
{
  "session_id": "session-001",
  "action_id": "act-001",
  "tool_name": "controlled_file_ops",
  "risk_level": "C",
  "decision": "approved",
  "user_feedback": "Approved renaming file"
}
```

#### Field Specifications:
- `session_id` (`string`, required): Identifier of an active session.
- `action_id` (`string`, required): Identifier of the proposed action requiring approval.
- `tool_name` (`string`, required): Name of the tool to be executed.
- `risk_level` (`string`, required): Classification (`A`, `B`, `C`, `D`).
- `decision` (`string`, required): Must be either `"approved"` or `"rejected"`.
- `user_feedback` (`string`, optional): User comments or modifications.

---

### Response Body
**Example JSON:**
```json
{
  "approval_id": "appr-001",
  "session_id": "session-001",
  "action_id": "act-001",
  "decision": "approved",
  "status": "confirmed",
  "timestamp": "2026-10-28T18:00:00Z"
}
```

#### Field Specifications:
- `approval_id` (`string`): Unique identifier for the recorded approval decision token.
- `session_id` (`string`): Associated session.
- `action_id` (`string`): Associated proposed action.
- `decision` (`string`): Recorded decision (`approved` or `rejected`).
- `status` (`string`): Status of the decision processing (`confirmed`, `expired`).
- `timestamp` (`string`): ISO 8601 timestamp when user made the decision.

---

### Status Codes

#### Success Codes
- `200 OK`: Approval decision recorded; approval token issued.

#### Error Codes
- `400 Bad Request`: Invalid decision (must be `"approved"` or `"rejected"`).
- `401 Unauthorized`: Missing or invalid authentication token.
- `404 Not Found`: Unknown `action_id` or `session_id`.
- `409 Conflict`: The action has already been approved, rejected, or has expired.
- `422 Unprocessable Entity`: Input validation failure.
- `500 Internal Server Error`: Internal failure recording approval state.

---

### Validation Rules
1. Never bypass approval requirements for sensitive tool actions (API Specs: Section 6, Rule 6; Section 8).
2. `decision` value must be strictly `"approved"` or `"rejected"`.
3. Actions are classified by risk:
   - **Level A (Informational):** Answer question — No confirmation normally required.
   - **Level B (Low-Risk Interaction):** Search information — Policy based.
   - **Level C (Sensitive):** Modify file, change settings, send email — User confirmation required.
   - **Level D (High-Risk / Destructive):** Delete files, privileged operations — Explicit confirmation must be required.

---

### Authentication & Permission Requirements
- **User Authentication:** Valid JWT / OAuth token ensuring only authorized human users can submit approval decisions (Architecture: Section 1; PRD: Section 19).

---

### Approval Requirements
- This endpoint is the core authority governing human-in-the-loop approvals for Level C and Level D actions. If the decision is `"rejected"`, the tool action is immediately canceled and the session informed.

---

### Implementation Status
- **Status:** `Planned`
- **Notes:** Not implemented in the Week 1 backend. Week 1 provides the foundational session repository and mock route structure.


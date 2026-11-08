# API Contract: Agent Action Planning

### API Name
Agent Action Planning API

### HTTP Method
`POST`

### Endpoint
`/api/v1/agent/plan`

### Purpose
Generates a structured, multi-step action plan to accomplish complex user requests using controlled tool workflows (as specified in *04. API Specifications & Interface Contracts*, Section 3; *03. Technical Architecture & Design*, Section 6; *02. System Design Document*, Section 6; and *01. Product Requirements Document*, Section 17).

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
*(Schema per Agent Orchestrator architecture in System Design Document, Section 6)*

**Example JSON:**
```json
{
  "session_id": "session-001",
  "goal": "Find this PDF and summarize it",
  "context_id": "context-001"
}
```

#### Field Specifications:
- `session_id` (`string`, required): Identifier of an existing active session.
- `goal` (`string`, required): High-level task to decompose (e.g., "Find this PDF and summarize it").
- `context_id` (`string`, optional): Reference to relevant workspace context.

---

### Response Body
*(Schema per Agent Planning and Safety Gate architecture in System Design Document, Section 6 & Section 7)*

**Example JSON:**
```json
{
  "plan_id": "plan-001",
  "session_id": "session-001",
  "goal": "Find this PDF and summarize it",
  "status": "planned",
  "steps": [
    {
      "step_number": 1,
      "tool_name": "file_search",
      "description": "Find relevant PDF files in permitted directories",
      "risk_level": "B",
      "requires_approval": false
    },
    {
      "step_number": 2,
      "tool_name": "file_reading",
      "description": "Read content of selected PDF file",
      "risk_level": "A",
      "requires_approval": false
    },
    {
      "step_number": 3,
      "tool_name": "document_processing",
      "description": "Extract text content from document",
      "risk_level": "A",
      "requires_approval": false
    },
    {
      "step_number": 4,
      "tool_name": "multimodal_ai",
      "description": "Analyze content and generate summary for user",
      "risk_level": "A",
      "requires_approval": false
    }
  ]
}
```

---

### Status Codes

#### Success Codes
- `200 OK`: Action plan decomposed and generated successfully.

#### Error Codes
- `400 Bad Request`: Missing mandatory fields (`session_id` or `goal`).
- `401 Unauthorized`: Missing or invalid authentication token.
- `404 Not Found`: Specified `session_id` does not exist.
- `422 Unprocessable Entity`: Input parameters failed schema validation.
- `500 Internal Server Error`: Agent orchestrator planning failure.

---

### Validation Rules
1. `session_id` must reference an active, non-terminal session.
2. The agent follows the workflow: `observe → understand → plan → select tool → execute → verify → respond` (SDD: Section 6).
3. Tools selected in steps must exist in the approved tool registry (PRD: Section 17).
4. Unrestricted operating system access or privileged command execution is strictly forbidden (PRD: NG2, NG4).

---

### Authentication & Permission Requirements
- **Session Authentication:** Valid user JWT / OAuth token (Architecture: Section 1).
- **Tool Permissions:** Tools in the plan must conform to permitted application integrations and user filesystem boundaries (PRD: Section 17).

---

### Approval Requirements
- Each planned step is classified by risk level (Level A: Informational, Level B: Low-risk, Level C: Sensitive, Level D: High-Risk/Destructive).
- If any step is Level C or Level D, the agent cannot execute it automatically and must request explicit user approval (SDD: Section 7; PRD: Section 18).

---

### Implementation Status
- **Status:** `Planned`
- **Notes:** Not implemented in the Week 1 backend. Week 1 supports recording mock agent plan events via `/api/v1/sessions/{id}/events`.


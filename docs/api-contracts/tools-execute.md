# API Contract: Controlled Tool Execution

### API Name
Controlled Tool Execution API

### HTTP Method
`POST`

### Endpoint
`/api/v1/tools/execute`

### Purpose
Executes a sandboxed, permission-gated tool operation requested by the AI agent on behalf of the user, preventing unrestricted operating system access (as specified in *04. API Specifications & Interface Contracts*, Section 3; *01. Product Requirements Document*, Section 17 & Section 18; and *02. System Design Document*, Section 5).

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
*(Schema per Tool & Action Framework in Product Requirements Document, Section 17)*

**Example JSON:**
```json
{
  "session_id": "session-001",
  "tool_name": "file_search",
  "parameters": {
    "query": "report.pdf",
    "directory": "Documents"
  },
  "approval_id": null
}
```

#### Field Specifications:
- `session_id` (`string`, required): Active session identifier.
- `tool_name` (`string`, required): One of the permitted tools (`file_search`, `file_reading`, `browser_search`, `document_processing`, `calculator`, `app_context_retrieval`, `data_analysis`, `controlled_file_ops`).
- `parameters` (`object`, required): Tool-specific arguments matching the defined tool input schema.
- `approval_id` (`string`, optional): Approval token received from `/api/v1/approvals` for Category C or D actions.

---

### Response Body
**Example JSON:**
```json
{
  "execution_id": "exec-001",
  "tool_name": "file_search",
  "status": "completed",
  "result": {
    "matched_files": ["Documents/report.pdf"],
    "total_found": 1
  },
  "requires_approval": false
}
```

#### Field Specifications:
- `execution_id` (`string`): Unique identifier for the tool execution invocation.
- `tool_name` (`string`): Name of the executed tool.
- `status` (`string`): Execution result state (`completed`, `failed`, `approval_required`).
- `result` (`object`): Structured output matching the tool output schema.
- `requires_approval` (`boolean`): Indicates if execution paused awaiting human approval.

---

### Status Codes

#### Success Codes
- `200 OK`: Tool executed successfully and output returned.

#### Error Codes
- `400 Bad Request`: Invalid tool parameters or missing arguments.
- `401 Unauthorized`: Missing or invalid authentication token.
- `403 Forbidden`: Attempted sensitive or destructive action without valid user approval (`approval_id`).
- `404 Not Found`: Unknown `tool_name` or invalid `session_id`.
- `422 Unprocessable Entity`: Parameters failed tool schema validation.
- `500 Internal Server Error`: Tool runtime failure.

---

### Validation Rules
1. Tool name must exist in the controlled tool registry (PRD: Section 17).
2. Never bypass approval requirements for sensitive tool actions (API Specs: Section 6, Rule 6; Section 8).
3. The AI is strictly barred from unrestricted system-level commands or administrative privileges (PRD: NG4).

---

### Authentication & Permission Requirements
- **Permission Boundaries:** Tools operate only on user-permitted locations and approved integrations (PRD: Section 17, Section 19).
- **Authentication:** Valid user credentials via JWT / OAuth (Architecture: Section 1).

---

### Approval Requirements
- **Risk Level A (Informational):** No confirmation required (e.g. calculator, read document).
- **Risk Level B (Low-Risk Interaction):** May execute per configured policy (e.g. search permitted files).
- **Risk Level C (Sensitive):** Requires verified user approval (`approval_id`) (e.g. modify files, send emails).
- **Risk Level D (High-Risk/Destructive):** Explicit human confirmation strictly mandatory (e.g. delete files, privileged operations).

---

### Implementation Status
- **Status:** `Planned`
- **Notes:** Not implemented in the Week 1 backend. Week 1 provides the foundation session repository and mock event logging.


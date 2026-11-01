# AI Voice Co-Pilot — Cross-Team Integration Guide

---

## 1. Introduction
The **AI Voice Co-Pilot** is an intelligent assistant that runs alongside a user's everyday desktop workflow. Rather than requiring users to switch away from their applications and type prompts manually, the Co-Pilot listens to spoken voice requests, inspects relevant screen and application context, plans multi-step actions, and executes tools under safe human supervision.

Building this system involves coordinated engineering across eight functional domains: Desktop/Frontend, Voice, Vision, Context, Multimodal AI, Agentic Planning, Safety, and Backend.

---

## 2. Purpose of the Integration Guide
This guide defines how all engineering teams communicate with and integrate into the **Backend Service**. It provides:
- A clear definition of each team's responsibilities.
- The lifecycle of a session and how it connects client requests to AI actions.
- Practical request and response examples.
- Step-by-step instructions for running and testing the backend locally.
- A transparent inventory of what is currently implemented versus what is planned for upcoming sprints.

---

## 3. System Overview
The complete system operates as a unified processing loop:

```
[User Speaks]
      │
      ▼
[Voice Pipeline] ──────► Speech-to-Text
                              │
[Screen / App Context] ──► Context Engine ──► Multimodal AI Layer
                                                    │
                                                    ▼
                                            Agent Orchestrator
                                             (Plans actions)
                                                    │
                                                    ▼
                                            Safety Gate & Approvals
                                                    │
                                       ┌────────────┴────────────┐
                                       ▼                         ▼
                                [Low-Risk: Run]           [Sensitive: Ask User]
                                       │                         │
                                       ▼                         ▼
                              [Tool Execution]           [User Approves via UI]
                                       │                         │
                                       └────────────┬────────────┘
                                                    ▼
                                          [Voice + UI Response]
```

---

## 4. Backend Responsibilities
The backend serves as the central coordination hub and is responsible for:
1. **API Gateway & Routing:** Exposing versioned REST endpoints (`/api/v1/...`).
2. **Session Management:** Storing and enforcing session lifecycle states (`created`, `active`, `paused`, `stopping`, `completed`, `failed`, `expired`).
3. **Audit & Event Logging:** Maintaining a chronological event stream for every active session.
4. **Distributed Request Tracing:** Injecting and propagating `X-Request-ID` and `X-Correlation-ID` across all transactions.
5. **Typed Error Enveloping:** Returning safe, structured error responses that never leak internal stack traces or secrets.
6. **Health & Readiness Probing:** Exposing monitoring endpoints (`/health` and `/ready`) for system vitality.

---

## 5. Frontend Responsibilities
The Frontend / Desktop application (built with React + Electron / Tauri / Python) is responsible for:
1. **Microphone Capture & Voice Feedback:** Capturing audio and showing visual indicators when listening, processing, or speaking (PRD: FR-VOICE-006).
2. **Context Permission Controls:** Giving users explicit toggles to authorize screen and window capture (PRD: FR-VISION-001).
3. **Session Lifecycle Initialization:** Calling `POST /api/v1/sessions` when the user starts a session, and `transition` when pausing or stopping.
4. **Approval Dialogs:** Displaying confirmation prompts for Category C (Sensitive) and Category D (Destructive) actions.
5. **Presenting AI Responses:** Rendering text guidance and playing back synthesized speech.

---

## 6. AI/LLM Integration Responsibilities
The Multimodal AI reasoning layer is responsible for:
1. **Intent Understanding:** Parsing the user's spoken request together with visible context.
2. **Clarification Handling:** If context is missing or ambiguous, asking the user clarifying questions instead of guessing (SDD: Section 2).
3. **Action Decision:** Deciding whether an informational text answer is sufficient or if an agent tool must be invoked.
4. **Interface Contract:** Consuming `POST /api/v1/ai/chat` and returning response text along with a `requires_approval` flag.

*Status:* `Planned` (Mock event recording implemented in Week 1).

---

## 7. Voice Input and Output Integration
1. **Input (Speech-to-Text):** The desktop app captures microphone audio and sends it to `POST /api/v1/voice/transcribe`, which uses a Whisper-compatible STT engine to produce text.
2. **Interruption Handling:** The frontend provides a mechanism for users to interrupt an ongoing AI voice response (PRD: FR-VOICE-004).
3. **Output (Text-to-Speech):** Generated response text is converted back to voice via a TTS service and played through the user's speakers.

*Status:* `Planned` (Mock voice transcript events can be dispatched to `/api/v1/sessions/{id}/events` in Week 1).

---

## 8. Context Management Integration
1. **Context Extraction:** The Context Engine captures authorized active-window titles, visible code/text, open document names, and recent conversation history.
2. **Minimization & Privacy:** The engine must minimize data collection, capturing only relevant regions rather than recording the entire screen continuously (PRD: FR-VISION-006).
3. **Submission:** Context is submitted to `POST /api/v1/context` and associated with the active session.

*Status:* `Planned` (Sessions in Week 1 support arbitrary context metadata).

---

## 9. Agent Planning Integration
When a user asks for a complex multi-step task (e.g. *"Find my project report and summarize it"*):
1. The request is sent to `POST /api/v1/agent/plan`.
2. The Agent Orchestrator decomposes the task into sequential steps:
   - Step 1: `file_search` (Search files)
   - Step 2: `file_reading` (Read file)
   - Step 3: `document_processing` (Extract text)
   - Step 4: `multimodal_ai` (Summarize)
3. Each step is assigned a risk level (A, B, C, or D).

*Status:* `Planned` (Contract defined in `docs/api-contracts/agent-plan.md`).

---

## 10. Tool Execution Integration
1. Tools run inside controlled sandbox boundaries and are invoked through `POST /api/v1/tools/execute`.
2. **Permitted Tools:** `file_search`, `file_reading`, `browser_search`, `document_processing`, `calculator`, `app_context_retrieval`, `data_analysis`, `controlled_file_ops`.
3. Unrestricted shell access, administrative escalation, and arbitrary destructive operations are forbidden (PRD: NG4).

*Status:* `Planned` (Contract defined in `docs/api-contracts/tools-execute.md`).

---

## 11. Approval and Safety Integration
Actions are categorized by risk level (PRD: Section 18; SDD: Section 5):

| Risk Level | Category | Examples | Approval Rule |
| :--- | :--- | :--- | :--- |
| **A** | Informational | Answer question, summarize code | No confirmation required |
| **B** | Low-Risk | Search files, read permitted docs | Allowed per policy |
| **C** | Sensitive | Modify file, change settings, send email | **User confirmation required** |
| **D** | High-Risk / Destructive | Delete file, run privileged actions | **Explicit user confirmation mandatory** |

If an action is Level C or D:
1. Tool execution pauses with status `requires_approval = true`.
2. The UI displays an approval card to the user: *"AI wants to modify `main.py`. Allow?"*
3. The user's decision is submitted to `POST /api/v1/approvals`.
4. Only upon a confirmed `"approved"` decision does tool execution resume.

*Status:* `Planned` (Contract defined in `docs/api-contracts/approvals.md`).

---

## 12. API Communication Flow
Here is the step-by-step sequence for a complete interaction:

```
Frontend               Backend (/api/v1)              Context / AI Engine
   │                          │                               │
   ├──── POST /sessions ─────►│ (Initializes state: created)  │
   │◄─── 201 Created ─────────┤                               │
   │                          │                               │
   ├─ POST /sessions/.../trans►│ (Transitions to: active)     │
   │◄─── 200 OK ──────────────┤                               │
   │                          │                               │
   ├─ POST /context ─────────►│──────────────────────────────►│ (Stores screen context)
   │◄─── 200 OK ──────────────│◄──────────────────────────────┤
   │                          │                               │
   ├─ POST /ai/chat ─────────►│──────────────────────────────►│ (Reasons with context)
   │◄─── 200 OK ──────────────│◄─── {requires_approval: true}─┤
   │     (Shows approval card)│                               │
   │                          │                               │
   ├─ POST /approvals ───────►│ (Records approval token)      │
   │◄─── 200 OK ──────────────┤                               │
   │                          │                               │
   ├─ POST /tools/execute ───►│ (Executes tool with token)    │
   │◄─── 200 OK ──────────────┤                               │
```

---

## 13. Request and Response Examples

### A. Create a Session (`POST /api/v1/sessions`)
**Request:**
```http
POST /api/v1/sessions HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
X-Correlation-ID: corr-client-001

{
  "metadata": {
    "active_application": "VS Code",
    "user_id": "vaishnavi"
  }
}
```

**Response (HTTP 201 Created):**
```json
{
  "session_id": "session-837da9c4",
  "state": "created",
  "created_at": "2026-10-28T14:34:56.568303+00:00",
  "updated_at": "2026-10-28T14:34:56.568303+00:00",
  "metadata": {
    "active_application": "VS Code",
    "user_id": "vaishnavi"
  },
  "events_count": 1,
  "events": [
    {
      "event_id": "evt-1234567890",
      "event_type": "session_created",
      "payload": { "initial_state": "created" },
      "timestamp": "2026-10-28T14:34:56.568303+00:00"
    }
  ]
}
```

### B. Transition Session State (`POST /api/v1/sessions/{id}/transition`)
**Request:**
```http
POST /api/v1/sessions/session-837da9c4/transition HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{
  "to_state": "active",
  "reason": "User started voice listening mode"
}
```

**Response (HTTP 200 OK):**
```json
{
  "session_id": "session-837da9c4",
  "state": "active",
  "created_at": "2026-10-28T14:34:56.568303+00:00",
  "updated_at": "2026-10-28T14:34:56.575809+00:00",
  "metadata": { "active_application": "VS Code" },
  "events_count": 2,
  "events": [ ... ]
}
```

### C. Record a Mock Event (`POST /api/v1/sessions/{id}/events`)
**Request:**
```http
POST /api/v1/sessions/session-837da9c4/events HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{
  "event_type": "mock_voice_transcript",
  "payload": {
    "transcript": "Explain this syntax error on line 42",
    "confidence": 0.985
  }
}
```

**Response (HTTP 201 Created):**
```json
{
  "event_id": "evt-b53942f860",
  "event_type": "mock_voice_transcript",
  "payload": {
    "transcript": "Explain this syntax error on line 42",
    "confidence": 0.985
  },
  "timestamp": "2026-10-28T14:34:56.582296+00:00"
}
```

---

## 14. Error Handling
When a request fails, the backend returns a standardized **Typed Error Envelope** accompanied by `X-Request-ID` and `X-Correlation-ID` response headers:

```json
{
  "error": {
    "code": "INVALID_STATE_TRANSITION",
    "message": "Cannot transition session from 'created' to 'completed'. Allowed transitions from 'created' are: ['active', 'failed', 'expired'].",
    "message_safe_for_user": "Cannot transition session from 'created' to 'completed'. Allowed transitions from 'created' are: ['active', 'failed', 'expired'].",
    "retryable": false,
    "correlation_id": "corr-client-001",
    "request_id": "req-a91283bc47de",
    "details_redacted": {
      "current_state": "created",
      "target_state": "completed"
    }
  }
}
```

Common error codes:
- `SESSION_NOT_FOUND` (404)
- `INVALID_STATE_TRANSITION` (409)
- `SESSION_ALREADY_EXISTS` (409)
- `VALIDATION_ERROR` (422)
- `INTERNAL_SERVER_ERROR` (500)

---

## 15. Local Setup
1. Clone or navigate to the project directory:
   ```bash
   cd "C:\Users\vaish\Desktop\AI voicebot"
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## 16. Running the Backend
Start the server in mock mode with one command:
```bash
python run_mock.py
```
*(On Windows, you can also use `.\scripts\run_mock.bat`)*

Verify vitality by checking the health endpoint:
```powershell
curl.exe http://127.0.0.1:8000/api/v1/health
```

---

## 17. Testing APIs using Swagger
FastAPI includes an interactive graphical testing interface:
1. Open **http://127.0.0.1:8000/docs** in your browser.
2. Select any endpoint (for example, `POST /api/v1/sessions`).
3. Click **"Try it out"**.
4. Click **"Execute"** to send the request and see the live response.

---

## 18. Integration Status

| Subsystem / Endpoint | Status | Description |
| :--- | :--- | :--- |
| **Health & Readiness** | ✅ **Implemented** | `/health`, `/ready`, `/api/v1/health`, `/api/v1/ready` |
| **Request & Correlation Tracing**| ✅ **Implemented** | Middleware automatically injects and propagates IDs |
| **Session State Engine** | ✅ **Implemented** | In-memory repository with 7 strictly enforced states |
| **Session Event Logging** | ✅ **Implemented** | Appends audit and mock event streams |
| **One-Command Mock Launcher**| ✅ **Implemented** | Starts backend in mock mode without external dependencies |
| **Voice Audio Transcription**| ⏳ **Planned** | `POST /api/v1/voice/transcribe` |
| **Context Submission** | ⏳ **Planned** | `POST /api/v1/context` |
| **Multimodal AI Chat** | ⏳ **Planned** | `POST /api/v1/ai/chat` |
| **Agent Action Planning** | ⏳ **Planned** | `POST /api/v1/agent/plan` |
| **Controlled Tool Execution**| ⏳ **Planned** | `POST /api/v1/tools/execute` |
| **Human Approval Gate** | ⏳ **Planned** | `POST /api/v1/approvals` |

---

## 19. Pending Integration Work
The following tasks are scheduled for upcoming sprints:
1. **Week 2 (Speech Pipeline):** Implement `POST /api/v1/voice/transcribe` integrating local Whisper STT.
2. **Week 2 (Context Engine):** Implement `POST /api/v1/context` to receive active window titles, OCR text, and screen snippets.
3. **Week 2 (Multimodal AI):** Implement `POST /api/v1/ai/chat` connecting to OpenAI-compatible LLM endpoints.
4. **Week 3 (Agentic Integration):** Implement `POST /api/v1/agent/plan` and `POST /api/v1/tools/execute` with sandbox security boundaries.
5. **Week 3 (Safety Gate):** Implement `POST /api/v1/approvals` to process user approval cards from the frontend.
6. **Week 4 (Persistent Storage):** Connect PostgreSQL and Redis to replace the in-memory repository for multi-instance deployments.


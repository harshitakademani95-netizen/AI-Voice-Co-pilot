# Week 3 Demo Guide: Speech-to-Text, Audio Pipeline & Backend Integration

**Project:** AI Voice Co-Pilot  
**Workstream:** SDE 3 — Speech-to-Text Subsystem  
**Target Branch:** `feature/w2-speech-to-text-1`  
**Execution Environment:** Windows 11 (PowerShell / Command Prompt)

This guide provides step-by-step instructions for evaluating the Week 3 speech-to-text features entirely in **mock mode**. No physical microphone, external cloud network access, or paid API credentials are required.

---

## 1. Project Setup & Prerequisites

Ensure you are located in the project root directory and your Python virtual environment is activated:

```powershell
# Navigate to repository root
cd "C:\Users\Disha D K\OneDrive\Desktop\AI Voice Co-Pilot"

# Verify active branch
git branch --show-current
# Expected output: feature/w2-speech-to-text-1

# Verify virtual environment Python
.\.venv\Scripts\python.exe --version
# Expected: Python 3.10+ (tested on Python 3.14)
```

---

## 2. Interactive Mock Demonstration Script

We provide an interactive demo walkthrough script using Python's interactive session or standalone script to showcase all 9 core capabilities.

### Run the Interactive Python Demonstration:
Execute this self-contained demonstration command in PowerShell:

```powershell
.\.venv\Scripts\python.exe -c "
import time
from src.audio.pipeline import AudioPipeline, create_deterministic_chunk
from src.repositories.session_repository import InMemorySessionRepository
from src.models.session import SessionState
from voice_stt.orchestrator import TranscriptionOrchestrator, RetryConfig
from voice_stt.integration import AudioSTTBridge, BackendEventStreamBridge

print('=== 1. INITIALIZING MOCK BACKEND & AUDIO PIPELINE ===')
repo = InMemorySessionRepository()
session_id = 'demo-session-week3'
repo.create(session_id=session_id, metadata={'environment': 'mock_demo'})
repo.transition(session_id=session_id, to_state=SessionState.ACTIVE, reason='User started speech demo')
print(f'Session created and active: {session_id}')

print('\n=== 2. CONNECTING BRIDGES ===')
backend_bridge = BackendEventStreamBridge(repository=repo, session_id=session_id)
orchestrator = TranscriptionOrchestrator(session_id=session_id, min_confidence_threshold=0.50)
audio_bridge = AudioSTTBridge(orchestrator=orchestrator, session_id=session_id, backend_bridge=backend_bridge)
audio_bridge.start()

print('\n=== 3. STREAMING AUDIO CHUNKS (INTERIM -> REVISION -> FINALIZATION) ===')
for i in range(5):
    chunk = create_deterministic_chunk(sequence_id=i, timestamp=i * 0.02, amplitude=0.5)
    is_last = (i == 4)
    events = audio_bridge.process_chunk(chunk, is_last=is_last)
    for evt in events:
        print(f'  [Event {evt.sequence_number}] Type: {evt.event_type.value.upper():12} | Text: \"{evt.segment.text if evt.segment else \"\"}\" (Conf: {evt.segment.confidence if evt.segment else 0:.2f})')

print('\n=== 4. VERIFYING BACKEND EVENT STREAM IN REPOSITORY ===')
session = repo.get(session_id)
print(f'Total session events logged in backend: {len(session.events)}')
for s_evt in session.events:
    if s_evt.event_type.startswith('voice_stt.'):
        print(f'  -> Backend Event: {s_evt.event_type:24} | Transcript: \"{s_evt.payload.get(\"transcript\")}\"')

print('\n=== 5. FINAL COMMITTED TRANSCRIPT ===')
print(f'Accumulated Transcript: \"{audio_bridge.get_transcript()}\"')
"
```

---

## 3. Step-by-Step Feature Walkthrough

### Feature A: Interim & Revision Hypothesis Progression
To demonstrate how interim speech hypotheses are updated dynamically without duplicating words:

```powershell
.\.venv\Scripts\python.exe -c "
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.schemas import TranscriptEvent, TranscriptEventType, TranscriptSegment

accum = OrderedSegmentAccumulator(session_id='rev-demo')

# 1. Interim hypothesis arrives
e1 = TranscriptEvent(
    event_id='e1', event_type=TranscriptEventType.INTERIM, sequence_number=1, timestamp=1.0, session_id='rev-demo',
    segment=TranscriptSegment(segment_id='s1', start_time=0.0, end_time=0.5, text='explain', confidence=0.8, is_final=False)
)
accum.ingest_event(e1)
print('Interim 1:', accum.get_full_transcript(include_interim=True))

# 2. Revised hypothesis arrives (replaces previous interim)
e2 = TranscriptEvent(
    event_id='e2', event_type=TranscriptEventType.REVISION, sequence_number=2, timestamp=1.5, session_id='rev-demo',
    segment=TranscriptSegment(segment_id='s1', start_time=0.0, end_time=1.0, text='explain this error', confidence=0.85, is_final=False)
)
accum.ingest_event(e2)
print('Revision 2:', accum.get_full_transcript(include_interim=True))

# 3. Finalization event commits segment
e3 = TranscriptEvent(
    event_id='e3', event_type=TranscriptEventType.FINALIZATION, sequence_number=3, timestamp=2.0, session_id='rev-demo',
    segment=TranscriptSegment(segment_id='s1', start_time=0.0, end_time=1.2, text='explain this error in terminal.', confidence=0.98, is_final=True)
)
accum.ingest_event(e3)
print('Finalized:', accum.get_full_transcript(include_interim=False))
"
```

---

### Feature B: In-Flight Cancellation
To demonstrate that calling `cancel()` clears pending interim speech and halts further processing:

```powershell
.\.venv\Scripts\python.exe -c "
from src.audio.pipeline import create_deterministic_chunk
from voice_stt.orchestrator import TranscriptionOrchestrator
from voice_stt.integration import AudioSTTBridge

orch = TranscriptionOrchestrator(session_id='cancel-demo')
bridge = AudioSTTBridge(orchestrator=orch, session_id='cancel-demo')
bridge.start()

# Process initial chunk
chunk0 = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
bridge.process_chunk(chunk0)

print('Active interim before cancel:', orch.get_interim_segment() is not None)

# Trigger cancellation
bridge.cancel()
print('Is bridge cancelled:', bridge.is_cancelled)
print('Active interim after cancel:', orch.get_interim_segment() is None)

# Late chunk arrives
chunk1 = create_deterministic_chunk(sequence_id=1, timestamp=0.02, amplitude=0.5)
events_after_cancel = bridge.process_chunk(chunk1)
print('Events emitted for late chunk after cancellation:', len(events_after_cancel))
"
```

---

### Feature C: Simulated Quota Exceeded (HTTP 429) Automatic Fallback
To demonstrate that when the primary provider encounters a quota failure, the orchestrator automatically routes through `DeterministicFakeTranscriber`:

```powershell
.\.venv\Scripts\python.exe -c "
from src.audio.pipeline import create_deterministic_chunk
from voice_stt.adapter import BaseSTTAdapter, STTAdapterConfig, STTAdapterState
from voice_stt.orchestrator import TranscriptionOrchestrator

class FailingQuotaAdapter(BaseSTTAdapter):
    def __init__(self):
        super().__init__(STTAdapterConfig())
    def initialize(self, session_id=None):
        super().initialize(session_id=session_id)
        self._state = STTAdapterState.READY
    def transcribe_chunk(self, chunk, is_last=False):
        raise RuntimeError('429 Too Many Requests: Insufficient quota for key sk-123456789012345678901234')
    def cancel(self): pass
    def reset(self): pass
    def close(self): pass

primary_adapter = FailingQuotaAdapter()
orch = TranscriptionOrchestrator(
    adapter=primary_adapter,
    enable_fallback=True,
    session_id='fallback-quota-demo'
)

chunk = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
events = orch.process_chunk(chunk, is_last=True)

print('Fallback active:', orch.is_fallback_active)
print('Fallback reason:', orch.fallback_reason)
print('Sanitized fallback error:', orch.fallback_error.message)
print('Events produced by fallback transcriber:', len(events))
print('Final transcript obtained offline:', orch.get_full_transcript())
"
```

---

### Feature D: Backend Session Event Stream Verification
To inspect the chronological event stream stored in `InMemorySessionRepository`:

```powershell
.\.venv\Scripts\python.exe -c "
from src.repositories.session_repository import InMemorySessionRepository
from src.models.session import SessionState
from voice_stt.schemas import TranscriptEvent, TranscriptEventType, TranscriptSegment
from voice_stt.integration import BackendEventStreamBridge

repo = InMemorySessionRepository()
repo.create(session_id='audit-session-demo')
repo.transition(session_id='audit-session-demo', to_state=SessionState.ACTIVE)

bridge = BackendEventStreamBridge(repository=repo, session_id='audit-session-demo')

# Ingest sequence of events
for i, evt_type in enumerate([TranscriptEventType.INTERIM, TranscriptEventType.REVISION, TranscriptEventType.FINALIZATION]):
    evt = TranscriptEvent(
        event_id=f'evt-{i}', event_type=evt_type, sequence_number=i+1, timestamp=100.0+i,
        session_id='audit-session-demo',
        segment=TranscriptSegment(segment_id='s1', start_time=0.0, end_time=float(i+1), text=f'word_{i+1}', confidence=0.9, is_final=(i==2))
    )
    bridge.publish_event(evt)

session = repo.get('audit-session-demo')
print('=== SESSION AUDIT TRAIL ===')
for event in session.events:
    print(f'[{event.timestamp}] {event.event_type} | payload: {event.payload}')
"
```

---

## 4. Complete Test Suite Execution

Run all 169 unit and integration tests across the entire Speech-to-Text and pipeline system:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

Expected output:
```
============================= 169 passed in 0.51s =============================
```

---

## 5. Visual Evidence Capture Guide (For Demo Submissions)

If your assignment submission requires screenshots or terminal recordings, capture the following exact views:

1. **Screenshot 1 — Full Test Suite Pass:**
   - Command: `.\.venv\Scripts\python.exe -m pytest tests/ -v`
   - Scope: Terminal window showing 169/169 passed tests with 100% pass rate.
2. **Screenshot 2 — Interactive End-to-End Pipeline Demo:**
   - Command: Run Section 2 interactive script.
   - Scope: Terminal output showing audio capture $\rightarrow$ interim/revision/finalization events $\rightarrow$ backend session repository log.
3. **Screenshot 3 — Quota Fallback with Credentials Sanitization:**
   - Command: Run Section 3 Feature C script.
   - Scope: Output showing `Fallback active: True`, `reason: QUOTA_EXCEEDED`, and `[REDACTED_API_KEY]`.
4. **Screenshot 4 — Clean Working Tree & Git Safety Check:**
   - Command: `git status; git branch -v; git diff --check`
   - Scope: Terminal showing active branch `feature/w2-speech-to-text-1`, no staged commits, and clean whitespace.

*(Note: Do not fabricate synthetic image files; run the commands above in your live PowerShell console to capture authentic evidence).*

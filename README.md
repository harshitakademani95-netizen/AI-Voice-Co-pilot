# Academiaai AI Voicebot — Team SDE 3

**Assigned Project:** Academiaai AI Voicebot — SDE 3  
**Canonical Project Location:** [`projects/sde-3-voicebot/`](projects/sde-3-voicebot/)  
**Target Branch:** `team/sde-3-voicebot`  
**Architecture:** Multi-Workstream Voice Assistant System (Single Source of Truth)

---

## Canonical Project Location

Per the Controlling Plan and architectural standardization, all source code, test suites, API contracts, and documentation for the **Academiaai AI Voicebot** are maintained inside:

👉 **[`projects/sde-3-voicebot/`](projects/sde-3-voicebot/)**

### Workstream Overview

| Workstream | Subsystem / Focus | Lead Engineer | Location |
| :--- | :--- | :--- | :--- |
| **W1** | Audio & Voice Activity Detection | Harshita G Kademani (Team Lead) | `projects/sde-3-voicebot/src/audio/` |
| **W2** | Speech-to-Text Pipeline | Disha D K | `projects/sde-3-voicebot/src/voice_stt/` |
| **W3** | Context, Vision & Reasoning | Amruta A J | `projects/sde-3-voicebot/src/context/` |
| **W4** | Agentic Workflow Engine | Suhani A | `projects/sde-3-voicebot/agentic_workflow/` |
| **W5** | Backend, Sessions & Observability | Vaishnavi G | `projects/sde-3-voicebot/src/app.py` |
| **W6** | Frontend & User Experience | Varsha B S | `projects/sde-3-voicebot/src/App.tsx` |

---

## Quickstart & Verification Commands

To run tests and demonstrations from the repository root:

```powershell
# Run the complete test suite from repository root
pytest

# Or run tests directly from the canonical project folder
cd projects/sde-3-voicebot
pytest

# Run the complete Week 3 Audio & VAD demonstration
python -m src.audio.demo
```

For complete documentation, architecture diagrams, test matrices, and integration guides, please refer directly to:
📘 **[`projects/sde-3-voicebot/README.md`](projects/sde-3-voicebot/README.md)**

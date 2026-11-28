"""Tests package for AI Voice Co-Pilot.

Covers:
- W1: Audio Capture & VAD
- W2: Speech-to-Text Pipeline Foundation
- W3: Context & Reasoning Engine
- W4: Agentic Workflow Engine
- W5: Backend & Sessions Layer
"""

import sys
from pathlib import Path

# Ensure src/ and root are on sys.path for direct module discovery across all workstreams
_root = Path(__file__).resolve().parent.parent
_src = _root / "src"
for _p in [str(_root), str(_src)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

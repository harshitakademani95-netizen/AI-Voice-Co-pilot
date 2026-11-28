"""
Reasoning module providing the RealReasoningEngine and deterministic fallback engine.
"""

from src.reasoning.mock_engine import MockReasoningEngine
from src.reasoning.real_engine import RealReasoningEngine, get_reasoning_engine

__all__ = ["MockReasoningEngine", "RealReasoningEngine", "get_reasoning_engine"]

"""
Workstream W3: Context & Reasoning (Week 2 - Day 8 & Day 14)
Unit Tests for OptInCaptureAdapter and Full Pipeline Determinism

Author: Amruta A J (Team SDE 3)
Module: tests.test_capture_adapter
"""

import sys
import unittest
from datetime import datetime, timezone

from src.context.capture_adapter import (
    CaptureConfig,
    CapturePermissionError,
    OptInCaptureAdapter,
    ResolutionLimitError,
    SamplingLimitError,
    TextLimitError,
)
from src.context.schemas import DEFAULT_FRAME_TIMESTAMP, ContextType, ScreenContext
from src.context.vision_adapter import MockVisionAdapter
from src.context.bounded_builder import BoundedContextBuilder, BoundedContextConfig
from src.reasoning.llm_client import LLMClientAdapter, LLMClientConfig, MockLLMClient
from src.context.schemas import ReasoningRequest


class TestOptInCaptureAdapter(unittest.TestCase):
    """Test suite validating OptInCaptureAdapter safety invariants, gating, and boundaries."""

    def test_disabled_by_default(self):
        """Adapter must be disabled on initialization by default."""
        adapter = OptInCaptureAdapter()
        self.assertFalse(adapter.is_opted_in)
        self.assertEqual(adapter.capture_count, 0)

    def test_capture_without_opt_in_raises_permission_error(self):
        """Attempting to capture without calling opt_in() raises CapturePermissionError."""
        adapter = OptInCaptureAdapter()
        with self.assertRaises(CapturePermissionError) as ctx:
            adapter.capture_frame()
        self.assertIn("disabled by default", str(ctx.exception))

    def test_opt_in_enables_capture(self):
        """Calling opt_in() enables capture and produces a schema-valid synthetic frame."""
        adapter = OptInCaptureAdapter()
        adapter.opt_in()
        self.assertTrue(adapter.is_opted_in)

        frame = adapter.capture_frame(
            active_app="VS Code",
            window_title="editor.py - VS Code",
            visible_text="print('hello')",
        )
        self.assertIsInstance(frame, ScreenContext)
        self.assertEqual(frame.active_application, "VS Code")
        self.assertEqual(frame.active_window_title, "editor.py - VS Code")
        self.assertEqual(frame.visible_text, "print('hello')")
        self.assertTrue(frame.is_synthetic)
        self.assertFalse(frame.capture_enabled)
        self.assertEqual(adapter.capture_count, 1)

    def test_opt_out_revokes_consent(self):
        """Calling opt_out() immediately revokes consent and blocks subsequent captures."""
        adapter = OptInCaptureAdapter()
        adapter.opt_in()
        frame1 = adapter.capture_frame()
        self.assertIsNotNone(frame1)

        adapter.opt_out()
        self.assertFalse(adapter.is_opted_in)
        with self.assertRaises(CapturePermissionError):
            adapter.capture_frame()

    def test_sampling_rate_limit_with_fake_clock(self):
        """Enforces max_fps rate-limiting using an injectable fake clock without real sleep."""
        fake_time = 100.0

        def fake_clock():
            return fake_time

        # max_fps=2.0 -> min_interval = 0.5s
        adapter = OptInCaptureAdapter(CaptureConfig(max_fps=2.0), clock_fn=fake_clock)
        adapter.opt_in()

        # First capture at t=100.0 succeeds
        frame1 = adapter.capture_frame()
        self.assertIsNotNone(frame1)

        # Immediate second capture at t=100.1 (0.1s < 0.5s) must be rejected
        fake_time = 100.1
        with self.assertRaises(SamplingLimitError) as ctx:
            adapter.capture_frame()
        self.assertIn("Sampling rate limit exceeded", str(ctx.exception))

        # Capture after interval has elapsed (t=100.5, exactly 0.5s) must succeed
        fake_time = 100.5
        frame2 = adapter.capture_frame()
        self.assertIsNotNone(frame2)
        self.assertEqual(adapter.capture_count, 2)

    def test_reset_rate_limit(self):
        """reset_rate_limit() allows an immediate subsequent capture without waiting."""
        fake_time = 10.0
        adapter = OptInCaptureAdapter(CaptureConfig(max_fps=1.0), clock_fn=lambda: fake_time)
        adapter.opt_in()
        adapter.capture_frame()

        with self.assertRaises(SamplingLimitError):
            adapter.capture_frame()

        adapter.reset_rate_limit()
        frame = adapter.capture_frame()
        self.assertIsNotNone(frame)

    def test_resolution_limit_rejection(self):
        """Requested dimensions exceeding max_width or max_height raise ResolutionLimitError."""
        config = CaptureConfig(max_width=1920, max_height=1080, clamp_dimensions=False)
        adapter = OptInCaptureAdapter(config)
        adapter.opt_in()

        with self.assertRaises(ResolutionLimitError) as ctx:
            adapter.capture_frame(width=3840, height=2160)
        self.assertIn("exceed maximum allowed boundaries", str(ctx.exception))

    def test_resolution_clamping(self):
        """When clamp_dimensions=True, oversized dimensions are clamped to maximum bounds."""
        config = CaptureConfig(max_width=1920, max_height=1080, clamp_dimensions=True)
        adapter = OptInCaptureAdapter(config)
        adapter.opt_in()

        frame = adapter.capture_frame(width=4000, height=3000)
        self.assertEqual(frame.width, 1920)
        self.assertEqual(frame.height, 1080)

    def test_text_length_limit_rejection(self):
        """Requested visible_text exceeding max_text_length raises TextLimitError."""
        config = CaptureConfig(max_text_length=50)
        adapter = OptInCaptureAdapter(config)
        adapter.opt_in()

        oversized_text = "x" * 51
        with self.assertRaises(TextLimitError) as ctx:
            adapter.capture_frame(visible_text=oversized_text)
        self.assertIn("exceeds maximum allowed boundary", str(ctx.exception))

    def test_no_real_screen_api_imported(self):
        """Verify that no real screen-grabbing or GUI automation libraries are imported."""
        import src.context.capture_adapter as mod

        source_code = ""
        with open(mod.__file__, "r", encoding="utf-8") as f:
            source_code = f.read()

        forbidden_tokens = ["mss", "PIL.ImageGrab", "pyautogui", "pynput", "win32gui", "Xlib"]
        for token in forbidden_tokens:
            self.assertNotIn(f"import {token}", source_code, f"Forbidden import found: {token}")
            self.assertNotIn(f"from {token}", source_code, f"Forbidden import found: {token}")


class TestWeek2PipelineDeterminism(unittest.TestCase):
    """Test suite ensuring end-to-end Week 2 pipeline is 100% deterministic across multiple runs."""

    def test_two_pipeline_runs_produce_identical_model_dump(self):
        """Running the full Week 2 pipeline twice with identical inputs yields identical model_dump() results."""
        def run_full_pipeline():
            # 1. Opt-In Capture Adapter with fixed clock
            fixed_time = 1000.0
            capture_adapter = OptInCaptureAdapter(
                CaptureConfig(max_fps=5.0),
                clock_fn=lambda: fixed_time,
            )
            capture_adapter.opt_in()
            frame = capture_adapter.capture_frame(
                frame_id="frame-det-001",
                active_app="VS Code",
                window_title="calc.py - Visual Studio Code",
                visible_text="def divide(a, b): return a / b\nZeroDivisionError",
                captured_at=DEFAULT_FRAME_TIMESTAMP,
            )

            # 2. Mock Vision Adapter
            vision_adapter = MockVisionAdapter()
            context_item = vision_adapter.to_context_item(frame, item_id="ctx-vision-001")

            # 3. Bounded Context Builder with fixed clock
            builder = BoundedContextBuilder(
                BoundedContextConfig(max_items=5, token_budget=500),
                clock_fn=lambda: DEFAULT_FRAME_TIMESTAMP,
            )
            bounded_items = builder.build_context(
                user_query="How to fix ZeroDivisionError in calc.py?",
                context_items=[context_item],
                reference_time=DEFAULT_FRAME_TIMESTAMP,
            )

            # 4. LLM Client Adapter Reasoning
            client = LLMClientAdapter(config=LLMClientConfig(provider="mock"))
            req = ReasoningRequest(
                request_id="req-det-test-01",
                session_id="sess-det-1",
                user_query="How to fix ZeroDivisionError in calc.py?",
                context_items=bounded_items,
                prompt_version="v1.0.0",
                created_at=DEFAULT_FRAME_TIMESTAMP,
            )
            result = client.generate(req)
            return result.model_dump()

        dump1 = run_full_pipeline()
        dump2 = run_full_pipeline()

        self.assertEqual(dump1, dump2)
        self.assertEqual(dump1["status"], "success")
        self.assertEqual(dump1["request_id"], "req-det-test-01")
        self.assertGreater(len(dump1["response_text"]), 0)


class TestCaptureAdapterClarityInvariants(unittest.TestCase):
    """
    Task 3 clarity tests:
    1. Before opt_in -> CapturePermissionError.
    2. After opt_in -> frame returned with is_synthetic=True.
    3. capture_enabled is always False (safety schema marker; real hardware never engaged).
    4. opt_out() re-blocks capture immediately.
    """

    def test_before_opt_in_raises_permission_error(self):
        """Before opt_in(), capture_frame() must raise CapturePermissionError."""
        adapter = OptInCaptureAdapter()
        self.assertFalse(adapter.is_opted_in)
        with self.assertRaises(CapturePermissionError):
            adapter.capture_frame()

    def test_after_opt_in_frame_is_synthetic_true(self):
        """After opt_in(), capture_frame() returns a frame with is_synthetic=True."""
        adapter = OptInCaptureAdapter()
        adapter.opt_in()
        frame = adapter.capture_frame(visible_text="hello world")
        self.assertTrue(frame.is_synthetic,
                        "Returned frame must always have is_synthetic=True")

    def test_capture_enabled_always_false(self):
        """
        capture_enabled is always False on returned frames.
        This is a safety schema marker: real hardware capture is never engaged
        in this project regardless of adapter consent state.
        """
        adapter = OptInCaptureAdapter()
        adapter.opt_in()
        frame = adapter.capture_frame(visible_text="test content")
        self.assertFalse(frame.capture_enabled,
                         "capture_enabled must always be False — real hardware capture is never used")

    def test_opt_out_re_blocks_capture(self):
        """
        opt_out() revokes consent immediately.
        A capture_frame() call after opt_out() must raise CapturePermissionError.
        """
        adapter = OptInCaptureAdapter()
        adapter.opt_in()
        # Confirm capture works before opt_out
        frame = adapter.capture_frame(visible_text="before opt-out")
        self.assertTrue(frame.is_synthetic)

        # Revoke consent
        adapter.opt_out()
        self.assertFalse(adapter.is_opted_in)

        # Capture must now be blocked
        with self.assertRaises(CapturePermissionError):
            adapter.capture_frame(visible_text="after opt-out")


if __name__ == "__main__":
    unittest.main()


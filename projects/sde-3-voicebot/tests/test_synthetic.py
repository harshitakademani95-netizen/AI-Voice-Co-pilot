"""
Unit tests for synthetic context fixtures and screen capture safety.
"""

import unittest
from pydantic import ValidationError
from src.context.fixtures import (
    create_synthetic_screen_frame,
    get_synthetic_document_scenario,
    get_synthetic_error_scenario,
    get_synthetic_file_action_scenario,
)
from src.context.schemas import ContextType, DEFAULT_FRAME_TIMESTAMP, ScreenContext


class TestSyntheticFixtures(unittest.TestCase):

    def test_screen_capture_disabled_by_default(self):
        frame = create_synthetic_screen_frame()
        self.assertFalse(frame.capture_enabled, "Screen capture must be disabled by default")
        self.assertTrue(frame.is_synthetic, "Synthetic frame must have is_synthetic=True")
        self.assertIn("VS Code", frame.active_application)
        self.assertGreater(frame.width, 0)
        self.assertGreater(frame.height, 0)

    def test_synthetic_error_scenario_structure(self):
        items = get_synthetic_error_scenario()
        self.assertGreaterEqual(len(items), 2)

        types = [item.context_type for item in items]
        self.assertIn(ContextType.CODE, types)
        self.assertIn(ContextType.TERMINAL, types)
        self.assertIn(ContextType.SCREEN, types)

        # Check that screen item has capture disabled
        screen_item = next(it for it in items if it.context_type == ContextType.SCREEN)
        self.assertIsNotNone(screen_item.screen_context)
        self.assertFalse(screen_item.screen_context.capture_enabled)
        self.assertTrue(screen_item.screen_context.is_synthetic)

        # Ensure no real personal paths are used
        for item in items:
            self.assertNotIn("personal_path", item.content)
            self.assertNotIn("password", item.content.lower())

    def test_synthetic_document_scenario(self):
        items = get_synthetic_document_scenario()
        doc_item = next(it for it in items if it.context_type == ContextType.DOCUMENT)
        self.assertIn("nimbus_paper.pdf", doc_item.source)
        self.assertIn("Nimbus", doc_item.content)

    def test_synthetic_file_action_scenario(self):
        items = get_synthetic_file_action_scenario()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].context_type, ContextType.RETRIEVAL)
        self.assertIn("report", items[0].content)

    def test_synthetic_screen_frame_deterministic(self):
        """Verify calling create_synthetic_screen_frame twice with the same inputs produces identical frames."""
        frame1 = create_synthetic_screen_frame()
        frame2 = create_synthetic_screen_frame()

        self.assertEqual(frame1.model_dump(), frame2.model_dump())
        self.assertEqual(frame1, frame2)
        self.assertEqual(frame1.captured_at, frame2.captured_at)
        self.assertFalse(frame1.capture_enabled)
        self.assertTrue(frame1.is_synthetic)
        self.assertFalse(frame2.capture_enabled)
        self.assertTrue(frame2.is_synthetic)

    def test_synthetic_scenarios_deterministic(self):
        """Verify scenario fixtures return identical data across calls and use DEFAULT_FRAME_TIMESTAMP."""
        scenarios = [
            get_synthetic_error_scenario,
            get_synthetic_document_scenario,
            get_synthetic_file_action_scenario,
        ]

        for scenario_fn in scenarios:
            run1 = scenario_fn()
            run2 = scenario_fn()

            self.assertEqual(
                [i.model_dump() for i in run1],
                [i.model_dump() for i in run2],
            )

            for item in run1:
                self.assertEqual(item.timestamp, DEFAULT_FRAME_TIMESTAMP)
                if item.screen_context is not None:
                    self.assertFalse(item.screen_context.capture_enabled)
                    self.assertTrue(item.screen_context.is_synthetic)



    def test_screen_context_validation_errors(self):
        """ScreenContext(capture_enabled=True) and ScreenContext(is_synthetic=False) must raise ValidationError."""
        with self.assertRaises(ValidationError) as ctx1:
            ScreenContext(frame_id="frame-fail-1", capture_enabled=True)
        self.assertIn("only synthetic frames are allowed", str(ctx1.exception))

        with self.assertRaises(ValidationError) as ctx2:
            ScreenContext(frame_id="frame-fail-2", is_synthetic=False)
        self.assertIn("only synthetic frames are allowed", str(ctx2.exception))


if __name__ == "__main__":
    unittest.main()

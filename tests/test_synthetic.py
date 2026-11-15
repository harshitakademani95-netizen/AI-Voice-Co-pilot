"""
Unit tests for synthetic context fixtures and screen capture safety.
"""

import unittest
from src.context.fixtures import (
    create_synthetic_screen_frame,
    get_synthetic_document_scenario,
    get_synthetic_error_scenario,
    get_synthetic_file_action_scenario,
)
from src.context.schemas import ContextType


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


if __name__ == "__main__":
    unittest.main()

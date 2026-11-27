"""
Workstream W3: Context & Reasoning (Week 3 - Day 21)
Acceptance and Integrity Tests for demo_week3.py

Author: Amruta A J (Team SDE 3)
Module: tests.test_demo_week3
Description:
    Verifies that demo_week3.main():
    1. Executes cleanly with exit code 0.
    2. Exercises all eight pipeline phases.
    3. Successfully validates non-consequential and consequential execution.
    4. Proves human approval gate enforcement and prompt-injection neutralization.
"""

import contextlib
import io
import unittest

import demo_week3


class TestDemoWeek3(unittest.TestCase):
    """Integrity and acceptance test suite for demo_week3.py."""

    def test_demo_week3_executes_successfully_and_verifies_all_phases(self):
        """
        Run demo_week3.main() and verify exit code 0, all 8 steps, and safety invariants.
        """
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = demo_week3.main()
        output = buf.getvalue()

        # Exit code must be 0
        self.assertEqual(rc, 0, f"demo_week3.main() returned non-zero exit code: {rc}")

        # Verify all 8 pipeline phases are executed and verified
        self.assertIn("STEP 1: VOICE INPUT & SPEECH TRANSCRIPTION", output)
        self.assertIn("STEP 2: PRIVACY-HARDENED SCREEN CAPTURE", output)
        self.assertIn("STEP 3: SOURCE-LINKED OBSERVATION PIPELINE", output)
        self.assertIn("STEP 4: BOUNDED CONTEXT WINDOW PRIORITIZATION", output)
        self.assertIn("STEP 5: PROMPT-INJECTION DEFENSE", output)
        self.assertIn("STEP 6: EVIDENCE-BOUNDED GROUNDED ANSWERS", output)
        self.assertIn("STEP 7: WORKFLOWPROPOSAL HANDOFF", output)
        self.assertIn("STEP 8: WORKFLOW EXECUTION & HUMAN-IN-THE-LOOP GATING", output)
        self.assertIn("FINAL INTEGRATION VERIFIED: ALL 8 PIPELINE PHASES SUCCEEDED [OK]", output)

        # Verify core safety invariants in output
        self.assertIn("capture.is_opted_in: False", output)
        self.assertIn("Role marker entity-encoded: True ('&#91;SYSTEM&#93;')", output)
        self.assertIn("AWAITING_APPROVAL", output)
        self.assertIn("Decision Recorded:  status=APPROVED", output)
        self.assertIn("Final State:        SUCCEEDED", output)

    def test_demo_week3_strict_determinism_across_consecutive_runs(self):
        """
        Execute demo_week3.main() twice in memory and assert that stdout is
        strictly byte-for-byte identical across runs (zero non-determinism).
        """
        buf1 = io.StringIO()
        with contextlib.redirect_stdout(buf1):
            rc1 = demo_week3.main()
        out1 = buf1.getvalue()

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = demo_week3.main()
        out2 = buf2.getvalue()

        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        self.assertEqual(
            out1,
            out2,
            "demo_week3.main() output differed between consecutive runs; strict determinism violated.",
        )


if __name__ == "__main__":
    unittest.main()

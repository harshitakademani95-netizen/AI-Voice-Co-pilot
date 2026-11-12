"""
Workstream W3: Context & Reasoning (Week 2 - Day 14)
Acceptance and Integrity Tests for demo_week2.py

Author: Amruta A J (Team SDE 3)
Module: tests.test_demo_week2
Description:
    Verifies that demo_week2.main():
    1. Executes cleanly with returncode 0 across multiple runs.
    2. Produces 100% deterministic, byte-for-byte identical output.
    3. Validates staleness filtering by checking that the stale item is
       excluded under the default builder (Included=False) and included
       under the comparison builder (Included=True).
    4. Remains free of raw Pydantic documentation URLs (e.g., pydantic.dev).
"""

import contextlib
import io
import unittest

import demo_week2


class TestDemoWeek2(unittest.TestCase):
    """Integrity and determinism test suite for demo_week2.py."""

    def test_demo_week2_runs_deterministically_with_honest_evidence(self):
        """
        Run demo_week2.main() twice, verifying exit codes, byte-for-byte determinism,
        stale item comparison evidence, and zero pydantic.dev URL leakage.
        """
        buf1 = io.StringIO()
        with contextlib.redirect_stdout(buf1):
            rc1 = demo_week2.main()
        out1 = buf1.getvalue()

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = demo_week2.main()
        out2 = buf2.getvalue()

        # Both runs must succeed
        self.assertEqual(rc1, 0, f"First run returned non-zero exit code: {rc1}")
        self.assertEqual(rc2, 0, f"Second run returned non-zero exit code: {rc2}")

        # Determinism: outputs must be 100% identical
        self.assertEqual(out1, out2, "demo_week2.py stdout differs between runs!")

        # Honest comparison evidence for stale item
        self.assertIn(
            "Stale Item (ctx-stale-001):        Included=False",
            out1,
            "Demo output missing stale item default exclusion evidence",
        )
        self.assertIn(
            "included at max_age=86400s (Included=True)",
            out1,
            "Demo output missing stale item comparison inclusion evidence",
        )

        # Honest comparison evidence for oversized item
        self.assertIn(
            "Oversized Item (ctx-oversized-001): Included=False",
            out1,
            "Demo output missing oversized item budget exclusion evidence",
        )
        self.assertIn(
            "included at token_budget=5000 (Included=True)",
            out1,
            "Demo output missing oversized item comparison inclusion evidence",
        )

        # URL leakage protection: no raw pydantic.dev documentation URLs
        self.assertNotIn(
            "pydantic.dev",
            out1,
            "Found raw 'pydantic.dev' documentation URL in demo output",
        )


if __name__ == "__main__":
    unittest.main()


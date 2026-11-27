"""
Workstream W3: Context & Reasoning Engine
Consent Withdrawal, Privacy Boundary & Context Purge Unit Tests

Author: Amruta A J (Team SDE 3)
Module: tests.test_consent_withdrawal
Description:
    Validates the privacy and consent lifecycle:
    1. Capture is disabled by default and rejected without explicit opt-in.
    2. Withdrawing consent immediately disables capture and refuses further captures with CapturePermissionError.
    3. Withdrawing consent purges all buffered and pending context items.
    4. Duplicate state and rate limits reset cleanly so re-opting in succeeds without errors.
    5. Calling withdraw_consent repeatedly is idempotent and safe.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

# Ensure project root and src/ are in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
for p in (_SRC_DIR, _PROJECT_ROOT):
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

from src.context.capture_adapter import (
    CaptureConfig,
    CapturePermissionError,
    OptInCaptureAdapter,
)
from src.context.schemas import ContextItem, ContextType


class TestConsentWithdrawal(unittest.TestCase):
    """Tests dedicated to consent withdrawal, context buffer purge, and re-opt-in behavior."""

    def setUp(self) -> None:
        self.simulated_time = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.adapter = OptInCaptureAdapter(
            datetime_clock_fn=lambda: self.simulated_time,
            config=CaptureConfig(max_frame_age_seconds=600.0, reject_duplicates=True),
        )

    def test_default_state_refuses_capture(self) -> None:
        """Capture must be disabled by default and raise CapturePermissionError."""
        self.assertFalse(self.adapter.is_opted_in)
        with self.assertRaises(CapturePermissionError):
            self.adapter.capture_frame(
                active_app="Terminal",
                window_title="bash",
                visible_text="ls -la",
                captured_at=self.simulated_time,
            )

    def test_consent_withdrawal_clears_buffered_and_pending_context(self) -> None:
        """Withdrawing consent immediately purges buffered items and blocks further capture."""
        self.adapter.opt_in()
        self.assertTrue(self.adapter.is_opted_in)

        # Buffer some items
        self.adapter.add_buffered_context(
            ContextItem(item_id="buf-1", context_type=ContextType.SCREEN, source="screen", content="frame 1 data")
        )
        self.adapter.add_buffered_context(
            ContextItem(item_id="buf-2", context_type=ContextType.SCREEN, source="screen", content="frame 2 data")
        )
        self.assertEqual(len(self.adapter.buffered_context), 2)

        # Withdraw consent
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)
        self.assertEqual(len(self.adapter.buffered_context), 0, "Buffered context must be completely empty after withdrawal.")
        self.assertEqual(len(self.adapter.pending_frames), 0, "Pending frames must be empty after withdrawal.")
        self.assertEqual(len(self.adapter.pending_observations), 0, "Pending observations must be empty after withdrawal.")

        # Further capture attempts must raise CapturePermissionError
        with self.assertRaises(CapturePermissionError):
            self.adapter.capture_frame(
                active_app="Terminal",
                window_title="bash",
                visible_text="unauthorized capture",
                captured_at=self.simulated_time,
            )

    def test_duplicate_state_and_rate_limit_reset_on_re_opt_in(self) -> None:
        """
        After consent withdrawal, duplicate-detection hash/last-frame state,
        ObservationGenerator pending/cached state, and rate limits are cleared.
        Subsequent capture_frame raises CapturePermissionError while opted out.
        After re-opt-in, an identical earlier frame is NOT rejected as a DuplicateFrameError.
        """
        self.adapter.opt_in()
        frame1 = self.adapter.capture_frame(
            active_app="Editor",
            window_title="main.py",
            visible_text="print('audit')",
            captured_at=self.simulated_time,
        )
        self.assertIsNotNone(frame1)
        self.assertIsNotNone(self.adapter._last_frame_fingerprint)
        self.assertGreater(len(self.adapter._seen_frame_fingerprints), 0)

        # Generate observation to populate observation generator cache
        obs1 = self.adapter.create_observation(frame1)
        self.assertIsNotNone(obs1)
        self.assertIsNotNone(self.adapter._observation_generator._last_fingerprint)
        self.assertGreater(len(self.adapter._observation_generator._seen_fingerprints), 0)
        self.assertGreater(len(self.adapter._observation_generator.history), 0)

        # Withdraw consent: must purge all state immediately
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)

        # 1. Duplicate-detection hash & last-frame state cleared
        self.assertIsNone(self.adapter._last_frame_fingerprint, "Last frame fingerprint must be cleared.")
        self.assertEqual(len(self.adapter._seen_frame_fingerprints), 0, "Seen frame fingerprints must be empty.")

        # 2. ObservationGenerator pending/cached state cleared
        self.assertIsNone(self.adapter._observation_generator._last_fingerprint, "Obs generator last fingerprint must be cleared.")
        self.assertEqual(len(self.adapter._observation_generator._seen_fingerprints), 0, "Obs generator seen fingerprints must be empty.")
        self.assertEqual(len(self.adapter._observation_generator.history), 0, "Obs generator history must be cleared.")

        # 3. Rate-limit state is reset
        self.assertIsNone(self.adapter._last_capture_time, "Rate limit timer must be reset.")

        # 4. capture_frame after withdrawal raises CapturePermissionError
        with self.assertRaises(CapturePermissionError):
            self.adapter.capture_frame(
                active_app="Editor",
                window_title="main.py",
                visible_text="print('audit')",
                captured_at=self.simulated_time,
            )

        # 5. Re-opt-in: identical earlier frame is NOT a DuplicateFrameError and succeeds cleanly
        self.adapter.opt_in()
        self.assertTrue(self.adapter.is_opted_in)
        frame2 = self.adapter.capture_frame(
            active_app="Editor",
            window_title="main.py",
            visible_text="print('audit')",
            captured_at=self.simulated_time,
        )
        self.assertIsNotNone(frame2)
        self.assertEqual(frame2.visible_text, "print('audit')")

    def test_withdraw_consent_idempotency(self) -> None:
        """Calling withdraw_consent multiple times in succession must be safe and idempotent."""
        self.adapter.opt_in()
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)

        # Successive calls must not raise errors
        self.adapter.withdraw_consent()
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)
        self.assertEqual(len(self.adapter.buffered_context), 0)


if __name__ == "__main__":
    unittest.main()

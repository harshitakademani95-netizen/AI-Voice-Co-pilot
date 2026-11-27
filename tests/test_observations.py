"""
Workstream W3: Context & Reasoning (Week 3 - Day 15)
Unit Tests for Source-Linked Observations, Freshness, and Consent Withdrawal

Author: Amruta A J (Team SDE 3)
Module: tests.test_observations
Description:
    Validates Day 15 capabilities:
    1. Valid timestamped observation with strictly-typed schema.
    2. Mandatory, verified SourceReference enforcement (rejects None / invalid).
    3. Invalid / naive timestamp rejection.
    4. Stale frame rejection based on configurable max_frame_age_seconds.
    5. Future timestamp rejection preventing clock anomalies.
    6. Duplicate frame rejection via deterministic SHA-256 fingerprinting.
    7. Changed frame acceptance when visual/window state changes.
    8. Consent withdrawal immediately revoking capture permission.
    9. Capture blocked after withdrawal (raising CapturePermissionError).
    10. Pending frames, pending observations, and buffered context flushed on withdrawal.
    11. Explicit re-consent restoring permitted capture.
"""

from datetime import datetime, timedelta, timezone
import unittest
from pydantic import ValidationError

from src.context.capture_adapter import (
    CaptureConfig,
    CapturePermissionError,
    DuplicateFrameError,
    FutureTimestampError,
    OptInCaptureAdapter,
    StaleFrameError,
)
from src.context.fixtures import create_synthetic_screen_frame
from src.context.observation_generator import (
    DuplicateObservationError,
    ObservationGenerator,
    StaleObservationError,
    compute_frame_fingerprint,
)
from src.context.schemas import (
    ContextItem,
    ContextType,
    DEFAULT_FRAME_TIMESTAMP,
    Observation,
    ScreenContext,
    SourceReference,
    observation_to_context_item,
)
from src.context.bounded_builder import (
    BoundedContextBuilder,
    BoundedContextConfig,
)


class TestObservationSchema(unittest.TestCase):
    """Test suite for the Observation Pydantic model."""

    def setUp(self):
        self.ref_time = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        self.valid_source = SourceReference(
            source_id="frame-001",
            source_type="screen",
            reference_location="calculator.py - VS Code",
            excerpt="def divide(a, b): return a / b",
            confidence_score=0.95,
        )

    def test_valid_timestamped_observation(self):
        """Constructing a valid Observation with timezone-aware timestamp succeeds."""
        obs = Observation(
            observation_id="obs-001",
            timestamp=self.ref_time,
            source=self.valid_source,
            content="Observed zero division exception on line 14",
            metadata={"priority": "high"},
        )
        self.assertEqual(obs.observation_id, "obs-001")
        self.assertEqual(obs.timestamp, self.ref_time)
        self.assertEqual(obs.source.source_id, "frame-001")
        self.assertEqual(obs.content, "Observed zero division exception on line 14")
        self.assertEqual(obs.metadata["priority"], "high")

    def test_mandatory_source_reference(self):
        """Observation requires a valid SourceReference; None or missing raises ValidationError."""
        with self.assertRaises(ValidationError):
            Observation(
                observation_id="obs-no-src",
                timestamp=self.ref_time,
                # pyrefly: ignore[bad-argument-type]
                source=None,
                content="Some observation without source",
            )

        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            Observation(
                observation_id="obs-dict-src",
                timestamp=self.ref_time,
                source={"invalid": "dictionary"},
                content="Some observation with invalid source",
            )

    def test_naive_timestamp_rejected(self):
        """Observation rejects naive (timezone-unaware) timestamps."""
        naive_dt = datetime(2026, 3, 15, 10, 0, 0)  # No tzinfo
        with self.assertRaises(ValidationError) as ctx:
            Observation(
                observation_id="obs-naive-ts",
                timestamp=naive_dt,
                source=self.valid_source,
                content="Observation with naive timestamp",
            )
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_extra_fields_forbidden(self):
        """Extra unknown fields on Observation are forbidden."""
        with self.assertRaises(ValidationError):
            # pyrefly: ignore[bad-argument-type]
            Observation(
                observation_id="obs-extra",
                timestamp=self.ref_time,
                source=self.valid_source,
                content="Valid content",
                # pyrefly: ignore[unexpected-keyword]
                unknown_field="injected",
            )


class TestObservationGenerator(unittest.TestCase):
    """Test suite for the standalone ObservationGenerator module."""

    def setUp(self):
        self.ref_time = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.generator = ObservationGenerator(
            clock_fn=lambda: self.ref_time,
            max_age_seconds=60.0,
            reject_duplicates=True,
        )

    def test_generate_from_valid_screen_frame(self):
        """Generating an observation from a synthetic ScreenContext frame succeeds."""
        frame = create_synthetic_screen_frame(
            frame_id="frame-gen-001",
            active_app="Terminal",
            window_title="bash - git status",
            visible_text="On branch main\nnothing to commit",
            captured_at=self.ref_time - timedelta(seconds=5),
        )
        obs = self.generator.generate_from_screen_frame(frame)

        self.assertEqual(obs.observation_id, "obs-0001")
        self.assertEqual(obs.source.source_id, "frame-gen-001")
        self.assertEqual(obs.source.source_type, "screen")
        self.assertEqual(obs.source.reference_location, "bash - git status")
        self.assertIn("Visual state of Terminal", obs.content)
        self.assertEqual(obs.timestamp, frame.captured_at)
        self.assertEqual(self.generator.observation_count, 1)

    def test_generator_stale_frame_rejection(self):
        """Frames older than max_age_seconds raise StaleObservationError."""
        stale_frame = create_synthetic_screen_frame(
            frame_id="frame-stale-001",
            captured_at=self.ref_time - timedelta(seconds=120),  # Age 120s > max 60s
        )
        with self.assertRaises(StaleObservationError) as ctx:
            self.generator.generate_from_screen_frame(stale_frame)
        self.assertIn("exceeds maximum allowed age", str(ctx.exception))

    def test_generator_duplicate_frame_rejection(self):
        """Consecutive identical frames raise DuplicateObservationError when reject_duplicates=True."""
        frame1 = create_synthetic_screen_frame(
            frame_id="frame-dup-001",
            active_app="VS Code",
            window_title="app.py",
            visible_text="import os",
            captured_at=self.ref_time - timedelta(seconds=10),
        )
        frame2 = create_synthetic_screen_frame(
            frame_id="frame-dup-002",
            active_app="VS Code",
            window_title="app.py",
            visible_text="import os",  # Identical content & window & app
            captured_at=self.ref_time - timedelta(seconds=5),
        )

        obs1 = self.generator.generate_from_screen_frame(frame1)
        self.assertIsNotNone(obs1)

        with self.assertRaises(DuplicateObservationError) as ctx:
            self.generator.generate_from_screen_frame(frame2)
        self.assertIn("Duplicate screen state detected", str(ctx.exception))

    def test_generator_accepts_changed_frame(self):
        """Frames with changed text or window are accepted without error."""
        frame1 = create_synthetic_screen_frame(
            frame_id="frame-chg-001",
            active_app="VS Code",
            window_title="app.py",
            visible_text="x = 1",
            captured_at=self.ref_time - timedelta(seconds=10),
        )
        frame2 = create_synthetic_screen_frame(
            frame_id="frame-chg-002",
            active_app="VS Code",
            window_title="app.py",
            visible_text="x = 2",  # Changed content
            captured_at=self.ref_time - timedelta(seconds=5),
        )

        obs1 = self.generator.generate_from_screen_frame(frame1)
        obs2 = self.generator.generate_from_screen_frame(frame2)
        self.assertEqual(self.generator.observation_count, 2)
        self.assertNotEqual(obs1.observation_id, obs2.observation_id)


class TestCaptureAdapterDay15(unittest.TestCase):
    """Test suite validating Day 15 freshness, duplicate detection, and consent withdrawal on OptInCaptureAdapter."""

    def setUp(self):
        self.ref_time = datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc)
        self.simulated_clock = 5000.0
        self.config = CaptureConfig(
            max_fps=10.0,
            max_frame_age_seconds=30.0,
            reject_duplicates=True,
            future_tolerance_seconds=1.0,
        )
        self.adapter = OptInCaptureAdapter(
            config=self.config,
            clock_fn=lambda: self.simulated_clock,
            datetime_clock_fn=lambda: self.ref_time,
        )

    def test_stale_frame_rejection(self):
        """Capturing or submitting a frame older than max_frame_age_seconds raises StaleFrameError."""
        self.adapter.opt_in()
        stale_time = self.ref_time - timedelta(seconds=45)  # 45s > 30s threshold

        with self.assertRaises(StaleFrameError) as ctx:
            self.adapter.capture_frame(
                captured_at=stale_time,
                visible_text="Stale data content",
            )
        self.assertIn("exceeds maximum allowed freshness", str(ctx.exception))

    def test_future_timestamp_rejection(self):
        """Capturing a frame with a timestamp in the future raises FutureTimestampError."""
        self.adapter.opt_in()
        future_time = self.ref_time + timedelta(seconds=10)  # 10s ahead

        with self.assertRaises(FutureTimestampError) as ctx:
            self.adapter.capture_frame(
                captured_at=future_time,
                visible_text="Future frame",
            )
        self.assertIn("in the future", str(ctx.exception))

    def test_naive_timestamp_rejection(self):
        """Capturing a frame with an explicit naive timestamp raises ValueError."""
        self.adapter.opt_in()
        naive_time = datetime(2026, 3, 15, 14, 0, 0)  # No tzinfo

        with self.assertRaises(ValueError) as ctx:
            self.adapter.capture_frame(captured_at=naive_time)
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_duplicate_frame_rejection(self):
        """Consecutive captures with identical text, window title, and app raise DuplicateFrameError."""
        self.adapter.opt_in()
        # First capture
        frame1 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="main.py",
            visible_text="def compute(): return 42",
            captured_at=self.ref_time,
        )
        self.assertEqual(self.adapter.capture_count, 1)

        # Advance monotonic clock to satisfy max_fps
        self.simulated_clock += 0.5

        # Duplicate capture with same state
        with self.assertRaises(DuplicateFrameError) as ctx:
            self.adapter.capture_frame(
                active_app="VS Code",
                window_title="main.py",
                visible_text="def compute(): return 42",
                captured_at=self.ref_time,
            )
        self.assertIn("Duplicate frame rejected", str(ctx.exception))

    def test_changed_frame_acceptance(self):
        """Consecutive captures with different visible text or windows are accepted."""
        self.adapter.opt_in()
        frame1 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="main.py",
            visible_text="first line",
            captured_at=self.ref_time,
        )
        self.simulated_clock += 0.5
        frame2 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="main.py",
            visible_text="second line (changed)",
            captured_at=self.ref_time,
        )
        self.assertEqual(self.adapter.capture_count, 2)
        self.assertNotEqual(frame1.frame_id, frame2.frame_id)

    def test_consent_withdrawal_and_capture_blocking(self):
        """
        Calling withdraw_consent() revokes consent, blocks subsequent captures,
        and flushes all pending frames, observations, and context items.
        """
        self.adapter.opt_in()
        self.assertTrue(self.adapter.is_opted_in)

        # Capture a frame and generate an observation
        frame = self.adapter.capture_frame(
            visible_text="active workspace text",
            captured_at=self.ref_time,
        )
        obs = self.adapter.create_observation(frame)
        self.adapter.add_buffered_context(
            ContextItem(
                item_id="ctx-buf-1",
                context_type=ContextType.SCREEN,
                source="screen",
                content="buffered screen item",
                timestamp=self.ref_time,
            )
        )

        # Confirm buffers are populated
        self.assertEqual(len(self.adapter.pending_frames), 1)
        self.assertEqual(len(self.adapter.pending_observations), 1)
        self.assertEqual(len(self.adapter.buffered_context), 1)

        # Withdraw consent
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)

        # Buffers must be completely cleared
        self.assertEqual(len(self.adapter.pending_frames), 0)
        self.assertEqual(len(self.adapter.pending_observations), 0)
        self.assertEqual(len(self.adapter.buffered_context), 0)

        # Subsequent capture attempt must be blocked
        self.simulated_clock += 0.5
        with self.assertRaises(CapturePermissionError):
            self.adapter.capture_frame(visible_text="new text after opt out")

        # Subsequent observation creation attempt must be blocked
        with self.assertRaises(CapturePermissionError):
            self.adapter.create_observation(frame)

    def test_explicit_re_consent_restores_permitted_capture(self):
        """After consent withdrawal, calling opt_in() successfully re-enables capture."""
        self.adapter.opt_in()
        frame1 = self.adapter.capture_frame(visible_text="frame before withdrawal")
        self.assertEqual(self.adapter.capture_count, 1)

        # Withdraw consent
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)

        # Explicitly re-consent
        self.adapter.opt_in()
        self.assertTrue(self.adapter.is_opted_in)

        self.simulated_clock += 0.5
        frame2 = self.adapter.capture_frame(visible_text="frame after re-consent")
        self.assertEqual(self.adapter.capture_count, 2)
        self.assertEqual(len(self.adapter.pending_frames), 1)
        self.assertEqual(self.adapter.pending_frames[0].frame_id, frame2.frame_id)


class TestObservationPipelineDay16(unittest.TestCase):
    """
    Day 16: Comprehensive tests for freshness boundary conditions, duplicate detection
    across buffered frames, privacy consent hardening, and BoundedContextBuilder integration.
    """

    def setUp(self):
        self.ref_time = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        self.simulated_clock = 1000.0
        self.config = CaptureConfig(
            max_fps=10.0,
            max_frame_age_seconds=30.0,
            reject_duplicates=True,
            future_tolerance_seconds=1.0,
        )
        self.adapter = OptInCaptureAdapter(
            config=self.config,
            clock_fn=lambda: self.simulated_clock,
            datetime_clock_fn=lambda: self.ref_time,
        )

    # ------------------------------------------------------------------
    # 1. Freshness Boundary Conditions
    # ------------------------------------------------------------------

    def test_freshness_boundary_exact_threshold_accepted(self):
        """Frame with age exactly equal to max_frame_age_seconds (30.0s) is accepted."""
        self.adapter.opt_in()
        exact_time = self.ref_time - timedelta(seconds=30.0)
        frame = self.adapter.capture_frame(
            visible_text="Boundary exact age content",
            captured_at=exact_time,
        )
        self.assertEqual(frame.captured_at, exact_time)
        self.assertEqual(len(self.adapter.pending_frames), 1)

    def test_freshness_boundary_just_over_threshold_rejected(self):
        """Frame with age just over threshold (30.001s) is rejected as stale."""
        self.adapter.opt_in()
        just_over_time = self.ref_time - timedelta(seconds=30.001)
        with self.assertRaises(StaleFrameError):
            self.adapter.capture_frame(
                visible_text="Just stale content",
                captured_at=just_over_time,
            )

    def test_future_timestamp_within_tolerance_accepted(self):
        """Frame timestamp within future_tolerance_seconds (0.8s <= 1.0s) is accepted."""
        self.adapter.opt_in()
        tolerated_time = self.ref_time + timedelta(seconds=0.8)
        frame = self.adapter.capture_frame(
            visible_text="Slight future skew tolerated",
            captured_at=tolerated_time,
        )
        self.assertEqual(frame.captured_at, tolerated_time)

    def test_future_timestamp_beyond_tolerance_rejected(self):
        """Frame timestamp beyond future_tolerance_seconds (1.5s > 1.0s) is rejected."""
        self.adapter.opt_in()
        future_time = self.ref_time + timedelta(seconds=1.5)
        with self.assertRaises(FutureTimestampError):
            self.adapter.capture_frame(
                visible_text="Far future content",
                captured_at=future_time,
            )

    # ------------------------------------------------------------------
    # 2. Multiple Buffered Duplicate Frames
    # ------------------------------------------------------------------

    def test_duplicate_rejection_across_multiple_buffered_frames(self):
        """
        Frames that match ANY previously buffered frame in the active session
        are rejected as duplicates, not just the immediately preceding frame.
        """
        self.adapter.opt_in()

        # Capture Frame 1 (state A)
        frame1 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="file_a.py",
            visible_text="content A",
            captured_at=self.ref_time,
        )
        self.assertEqual(len(self.adapter.pending_frames), 1)

        # Advance clock to satisfy max_fps
        self.simulated_clock += 0.5

        # Capture Frame 2 (state B - changed)
        frame2 = self.adapter.capture_frame(
            active_app="Terminal",
            window_title="bash",
            visible_text="content B",
            captured_at=self.ref_time,
        )
        self.assertEqual(len(self.adapter.pending_frames), 2)

        # Advance clock again
        self.simulated_clock += 0.5

        # Attempt to capture state A again (matches Frame 1 already in buffer)
        with self.assertRaises(DuplicateFrameError) as ctx:
            self.adapter.capture_frame(
                active_app="VS Code",
                window_title="file_a.py",
                visible_text="content A",
                captured_at=self.ref_time,
            )
        self.assertIn("previously buffered frame", str(ctx.exception))

        # Attempt to capture state B again (matches Frame 2)
        with self.assertRaises(DuplicateFrameError):
            self.adapter.capture_frame(
                active_app="Terminal",
                window_title="bash",
                visible_text="content B",
                captured_at=self.ref_time,
            )

    # ------------------------------------------------------------------
    # 3. Changed Application / Window State Acceptance
    # ------------------------------------------------------------------

    def test_changed_window_title_with_same_text_accepted(self):
        """Same visible text in a different window title is treated as distinct visual state."""
        self.adapter.opt_in()
        f1 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="doc1.txt",
            visible_text="Shared boilerplate text",
            captured_at=self.ref_time,
        )
        self.simulated_clock += 0.5
        f2 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="doc2.txt",  # Changed window
            visible_text="Shared boilerplate text",
            captured_at=self.ref_time,
        )
        self.assertEqual(self.adapter.capture_count, 2)
        self.assertNotEqual(f1.frame_id, f2.frame_id)

    def test_changed_application_with_same_text_accepted(self):
        """Same visible text in a different application is treated as distinct visual state."""
        self.adapter.opt_in()
        f1 = self.adapter.capture_frame(
            active_app="TextEdit",
            window_title="notes.txt",
            visible_text="Meeting notes text",
            captured_at=self.ref_time,
        )
        self.simulated_clock += 0.5
        f2 = self.adapter.capture_frame(
            active_app="Slack",  # Changed app
            window_title="notes.txt",
            visible_text="Meeting notes text",
            captured_at=self.ref_time,
        )
        self.assertEqual(self.adapter.capture_count, 2)
        self.assertNotEqual(f1.frame_id, f2.frame_id)

    # ------------------------------------------------------------------
    # 4. Consent Withdrawal & Prevention of Alternate Bypass Paths
    # ------------------------------------------------------------------

    def test_consent_withdrawal_clears_multiple_pending_items(self):
        """Withdrawal clears populated frames, observations, and buffered context items."""
        self.adapter.opt_in()

        # Add 2 frames
        f1 = self.adapter.capture_frame(visible_text="frame one", captured_at=self.ref_time)
        self.simulated_clock += 0.5
        f2 = self.adapter.capture_frame(visible_text="frame two", captured_at=self.ref_time)

        # Add 2 observations
        obs1 = self.adapter.create_observation(f1)
        obs2 = self.adapter.create_observation(f2)

        # Add 2 buffered context items
        self.adapter.buffer_observation_as_context(obs1)
        self.adapter.buffer_observation_as_context(obs2)

        self.assertEqual(len(self.adapter.pending_frames), 2)
        self.assertEqual(len(self.adapter.pending_observations), 2)
        self.assertEqual(len(self.adapter.buffered_context), 2)

        # Withdraw consent
        self.adapter.withdraw_consent()
        self.assertFalse(self.adapter.is_opted_in)

        # All buffers must be flushed
        self.assertEqual(len(self.adapter.pending_frames), 0)
        self.assertEqual(len(self.adapter.pending_observations), 0)
        self.assertEqual(len(self.adapter.buffered_context), 0)

    def test_alternate_generator_path_cannot_bypass_withdrawn_consent(self):
        """Directly accessing adapter.observation_generator fails when consent is withdrawn."""
        self.adapter.opt_in()
        frame = self.adapter.capture_frame(visible_text="Test bypass content", captured_at=self.ref_time)

        # Withdraw consent
        self.adapter.withdraw_consent()

        # Direct generator call must still be blocked by consent verifier
        with self.assertRaises(CapturePermissionError) as ctx:
            self.adapter.observation_generator.generate_from_screen_frame(frame)
        self.assertIn("Consent has been withdrawn", str(ctx.exception))

    def test_re_consent_resets_duplicate_history_for_fresh_session(self):
        """Withdrawing consent resets duplicate tracking so clean session can re-capture."""
        self.adapter.opt_in()
        f1 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="main.py",
            visible_text="code snippet",
            captured_at=self.ref_time,
        )

        # Withdraw consent flushes state
        self.adapter.withdraw_consent()

        # Re-consent
        self.adapter.opt_in()
        self.simulated_clock += 0.5

        # Same frame content is now accepted in the fresh session because history was flushed
        f2 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="main.py",
            visible_text="code snippet",
            captured_at=self.ref_time,
        )
        self.assertEqual(f2.active_application, "VS Code")
        self.assertEqual(len(self.adapter.pending_frames), 1)

    # ------------------------------------------------------------------
    # 5. Observation Source Traceability
    # ------------------------------------------------------------------

    def test_observation_strict_source_traceability(self):
        """Generated observations faithfully retain source_id, type, location, and timestamps."""
        self.adapter.opt_in()
        frame = self.adapter.capture_frame(
            frame_id="frame-trace-999",
            active_app="Firefox",
            window_title="Bug Tracker - Issue #42",
            visible_text="Crash report traceback: division by zero in module math.py",
            captured_at=self.ref_time,
        )
        obs = self.adapter.create_observation(frame)

        self.assertEqual(obs.source.source_id, "frame-trace-999")
        self.assertEqual(obs.source.source_type, "screen")
        self.assertEqual(obs.source.reference_location, "Bug Tracker - Issue #42")
        # pyrefly: ignore[bad-argument-type]
        self.assertIn("Crash report traceback", obs.source.excerpt)
        self.assertEqual(obs.timestamp, self.ref_time)
        self.assertEqual(obs.metadata["frame_id"], "frame-trace-999")
        self.assertIn("fingerprint", obs.metadata)

    # ------------------------------------------------------------------
    # 6. Observation Integration with BoundedContextBuilder
    # ------------------------------------------------------------------

    def test_observation_integration_with_bounded_context_builder(self):
        """
        Observations converted to ContextItems feed BoundedContextBuilder cleanly,
        honoring token budgeting, freshness filtering, and keyword scoring.
        """
        self.adapter.opt_in()

        # Observation 1: highly relevant error frame
        f1 = self.adapter.capture_frame(
            active_app="VS Code",
            window_title="calculator.py",
            visible_text="ZeroDivisionError: division by zero on line 14",
            captured_at=self.ref_time - timedelta(seconds=5),
        )
        obs1 = self.adapter.create_observation(f1)

        self.simulated_clock += 0.5

        # Observation 2: less relevant frame
        f2 = self.adapter.capture_frame(
            active_app="Browser",
            window_title="Documentation",
            visible_text="Python tutorial on arithmetic operations and functions",
            captured_at=self.ref_time - timedelta(seconds=10),
        )
        obs2 = self.adapter.create_observation(f2)

        # Convert to ContextItems
        item1 = obs1.to_context_item()
        item2 = obs2.to_context_item()

        self.assertEqual(item1.context_type, ContextType.SCREEN)
        self.assertEqual(item1.source, "calculator.py")
        self.assertEqual(item1.timestamp, obs1.timestamp)
        self.assertEqual(item1.metadata["observation_id"], obs1.observation_id)

        # Ingest into BoundedContextBuilder
        config = BoundedContextConfig(
            max_items=5,
            token_budget=150,
            max_age_seconds=60.0,
            chars_per_token=4.0,
        )
        builder = BoundedContextBuilder(config=config)
        user_query = "Why did calculator.py raise ZeroDivisionError?"

        bounded_items, report = builder.build_context_with_report(
            user_query=user_query,
            context_items=[item1, item2],
            reference_time=self.ref_time,
        )

        # Both items are fresh and within budget
        self.assertEqual(len(bounded_items), 2)
        # item1 scored higher due to direct keyword matches ("calculator.py", "ZeroDivisionError")
        self.assertEqual(bounded_items[0].item_id, item1.item_id)
        self.assertEqual(bounded_items[1].item_id, item2.item_id)

        # Report has zero exclusions
        self.assertEqual(len(report), 0)


if __name__ == "__main__":
    unittest.main()


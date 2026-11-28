"""
Contract verification test suite for Workstream W2 (voice_stt) integration.

Asserts the exact API surface, class contracts, methods, and schemas
that the Week 3 Audio & VAD bridge (AudioTranscriptionBridge and
AudioBackendSessionManager) relies upon.

If a newer voice_stt module (with orchestrator, fallback, or cancellation)
is introduced, this contract test will verify compatibility.
"""

from __future__ import annotations

import inspect
import unittest
from typing import List, Optional

# Schemas and classes under test
from src.schemas.audio import AudioChunk, AudioFormat
from src.voice_stt.accumulator import OrderedSegmentAccumulator
from src.voice_stt.adapter import BaseSTTAdapter, STTAdapterState
from src.voice_stt.fake_transcriber import DeterministicFakeTranscriber
from src.voice_stt.schemas import (
    STTErrorDetail,
    STTValidationError,
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
    WordTiming,
)


class TestVoiceSTTContract(unittest.TestCase):
    """Formal interface contract suite between Audio (W1) and STT (W2)."""

    def test_ordered_segment_accumulator_contract(self) -> None:
        """Verify OrderedSegmentAccumulator exposes required accumulation methods."""
        accum = OrderedSegmentAccumulator()

        # Method existence and callable
        self.assertTrue(callable(getattr(accum, "ingest_event", None)))
        self.assertTrue(callable(getattr(accum, "get_full_transcript", None)))
        self.assertTrue(callable(getattr(accum, "get_final_segments", None)))
        self.assertTrue(callable(getattr(accum, "get_interim_segment", None)))
        self.assertTrue(callable(getattr(accum, "get_average_confidence", None)))
        self.assertTrue(callable(getattr(accum, "reset", None)))

        # Signature verification
        sig = inspect.signature(accum.ingest_event)
        self.assertIn("event", sig.parameters)

        # Basic functionality
        self.assertEqual(accum.get_full_transcript(), "")
        self.assertEqual(accum.get_final_segments(), [])
        self.assertIsNone(accum.get_interim_segment())

    def test_base_stt_adapter_contract(self) -> None:
        """Verify BaseSTTAdapter abstract contract and DeterministicFakeTranscriber implementation."""
        self.assertTrue(issubclass(DeterministicFakeTranscriber, BaseSTTAdapter))

        transcriber = DeterministicFakeTranscriber(seed=42)
        self.assertTrue(callable(getattr(transcriber, "initialize", None)))
        self.assertTrue(callable(getattr(transcriber, "transcribe_chunk", None)))
        self.assertTrue(callable(getattr(transcriber, "reset", None)))

        # Method signatures
        init_sig = inspect.signature(transcriber.initialize)
        self.assertIn("session_id", init_sig.parameters)

        trans_sig = inspect.signature(transcriber.transcribe_chunk)
        self.assertIn("chunk", trans_sig.parameters)
        self.assertIn("is_last", trans_sig.parameters)

    def test_transcript_schemas_contract(self) -> None:
        """Verify STT schema contracts used by downstream consumers."""
        # Event types
        self.assertTrue(hasattr(TranscriptEventType, "INTERIM"))
        self.assertTrue(hasattr(TranscriptEventType, "FINAL"))
        self.assertTrue(hasattr(TranscriptEventType, "ERROR"))

        # TranscriptSegment creation and fields
        segment = TranscriptSegment(
            segment_id="seg-contract-01",
            start_time=0.0,
            end_time=0.5,
            text="hello world",
            confidence=0.95,
            is_final=True,
        )
        self.assertEqual(segment.segment_id, "seg-contract-01")
        self.assertEqual(segment.text, "hello world")
        self.assertTrue(segment.is_final)

        # TranscriptEvent creation and fields
        event = TranscriptEvent(
            event_id="evt-contract-01",
            event_type=TranscriptEventType.FINAL,
            sequence_number=0,
            timestamp=0.5,
            session_id="sess-contract-01",
            segment=segment,
        )
        self.assertEqual(event.event_id, "evt-contract-01")
        self.assertEqual(event.event_type, TranscriptEventType.FINAL)
        self.assertEqual(event.session_id, "sess-contract-01")

    def test_adapter_state_enum(self) -> None:
        """Verify STTAdapterState lifecycle states."""
        self.assertTrue(hasattr(STTAdapterState, "UNINITIALIZED"))
        self.assertTrue(hasattr(STTAdapterState, "READY"))
        self.assertTrue(hasattr(STTAdapterState, "PROCESSING"))
        self.assertTrue(hasattr(STTAdapterState, "CLOSED"))
        self.assertTrue(hasattr(STTAdapterState, "ERROR"))


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for Week 3 Day 15: Audio & VAD Speech Start/End and Normalized Audio Events.

Student: Harshita G Kademani | SDE 3 | Workstream: Audio & VAD
Verifies:
1. Speech-start event emission upon speech detection.
2. Speech-end event emission upon speech offset after hangover debounce.
3. Correct event ordering (SPEECH_START -> AUDIO_CHUNK* -> SPEECH_END).
4. Prevention of duplicate speech-start events during continuous speech.
5. Multi-segment speech handling with unique segment IDs.
6. Session ID and Correlation ID preservation across all events.
7. Chunk sequence ID and timestamp preservation in normalized audio events.
8. Silence input does not emit speech events.
9. Transient noise burst rejection (false triggers below min_speech_duration_ms).
10. Open speech segment termination upon stream stop.
11. AudioEvent schema validation, error handling, and dictionary serialization round-trip.
12. Callback dispatch and polling mechanics.
"""

from __future__ import annotations

import unittest
from typing import List

from src.audio.pipeline import (
    AudioPipeline,
    create_deterministic_chunk,
    generate_noise_burst_fixture,
    generate_silence_fixture,
    generate_speech_fixture,
)
from src.audio.vad import VADConfig
from src.schemas.audio import AudioChunk, AudioError, AudioEvent, AudioEventType, AudioFormat


class TestAudioEventsDay15(unittest.TestCase):
    """Test suite for Day 15 Audio Events and Speech Start/End generation."""

    def setUp(self) -> None:
        self.session_id = "test-session-d15-001"
        self.correlation_id = "test-corr-d15-999"
        self.pipeline = AudioPipeline(
            buffer_capacity=20,
            vad_config=VADConfig(
                energy_threshold=0.01,
                speech_probability_threshold=0.4,
                min_speech_duration_ms=40.0,
                min_silence_duration_ms=60.0,
            ),
            session_id=self.session_id,
            correlation_id=self.correlation_id,
        )

    def test_audio_event_schema_validation_and_roundtrip(self) -> None:
        """Verify AudioEvent schema invariants, validation rules, and dict serialization."""
        chunk = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.5)
        evt = AudioEvent(
            event_id="evt-test-1",
            event_type=AudioEventType.SPEECH_START,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            sequence_number=0,
            timestamp=0.0,
            chunk=chunk,
            segment_id="seg-1",
            metadata={"energy": 0.25},
        )
        self.assertEqual(evt.event_type, AudioEventType.SPEECH_START)
        self.assertTrue(evt.is_speech)
        self.assertAlmostEqual(evt.duration_ms, 20.0)

        # Dict round-trip
        data = evt.to_dict(include_base64_data=True)
        self.assertEqual(data["event_id"], "evt-test-1")
        self.assertEqual(data["event_type"], "speech_start")
        self.assertEqual(data["session_id"], self.session_id)
        self.assertEqual(data["correlation_id"], self.correlation_id)
        self.assertIsNotNone(data["chunk"])

        rebuilt = AudioEvent.from_dict(data)
        self.assertEqual(rebuilt.event_id, evt.event_id)
        self.assertEqual(rebuilt.event_type, evt.event_type)
        self.assertEqual(rebuilt.session_id, evt.session_id)
        self.assertEqual(rebuilt.correlation_id, evt.correlation_id)
        self.assertEqual(rebuilt.chunk.sequence_id, chunk.sequence_id)

    def test_audio_event_schema_rejection_rules(self) -> None:
        """Verify AudioEvent rejects invalid IDs, numbers, and types."""
        # Invalid event_id
        with self.assertRaises(AudioError) as ctx:
            AudioEvent(
                event_id="",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                sequence_number=0,
                timestamp=0.0,
            )
        self.assertEqual(ctx.exception.code, "INVALID_PARAMETER")

        # Invalid session_id
        with self.assertRaises(AudioError):
            AudioEvent(
                event_id="evt-1",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id="",
                correlation_id=self.correlation_id,
                sequence_number=0,
                timestamp=0.0,
            )

        # Invalid correlation_id
        with self.assertRaises(AudioError):
            AudioEvent(
                event_id="evt-1",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id=self.session_id,
                correlation_id="   ",
                sequence_number=0,
                timestamp=0.0,
            )

        # Negative sequence_number
        with self.assertRaises(AudioError):
            AudioEvent(
                event_id="evt-1",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                sequence_number=-1,
                timestamp=0.0,
            )

        # Negative timestamp
        with self.assertRaises(AudioError):
            AudioEvent(
                event_id="evt-1",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                sequence_number=0,
                timestamp=-0.5,
            )

        # Non-finite timestamp
        with self.assertRaises(AudioError):
            AudioEvent(
                event_id="evt-1",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                sequence_number=0,
                timestamp=float("inf"),
            )

        # Invalid chunk type
        with self.assertRaises(AudioError):
            AudioEvent(
                event_id="evt-1",
                event_type=AudioEventType.AUDIO_CHUNK,
                session_id=self.session_id,
                correlation_id=self.correlation_id,
                sequence_number=0,
                timestamp=0.0,
                chunk="not-a-chunk",  # type: ignore
            )

    def test_speech_start_event_emitted_when_speech_begins(self) -> None:
        """Verify SPEECH_START is emitted when sustained speech exceeds min_speech_duration_ms."""
        # 3 speech chunks (60ms) -> exceeds 40ms min speech threshold
        chunks = generate_speech_fixture(num_chunks=3, amplitude=0.5)

        for c in chunks:
            self.pipeline.process_chunk_direct(c)

        events = self.pipeline.get_events()
        start_events = [e for e in events if e.event_type == AudioEventType.SPEECH_START]

        self.assertEqual(len(start_events), 1, "Exactly one SPEECH_START event must be emitted")
        start_evt = start_events[0]
        self.assertEqual(start_evt.session_id, self.session_id)
        self.assertEqual(start_evt.correlation_id, self.correlation_id)
        self.assertIsNotNone(start_evt.segment_id)
        self.assertIn("seg-", start_evt.segment_id)
        self.assertAlmostEqual(start_evt.timestamp, 0.0, places=3)
        self.assertIn("onset_sequence_id", start_evt.metadata)
        self.assertEqual(start_evt.metadata["onset_sequence_id"], 0)

    def test_no_duplicate_speech_start_during_continuous_speech(self) -> None:
        """Verify continuous speech chunks do not emit duplicate SPEECH_START events."""
        # 10 speech chunks (200ms of sustained voice)
        chunks = generate_speech_fixture(num_chunks=10, amplitude=0.6)

        for c in chunks:
            self.pipeline.process_chunk_direct(c)

        events = self.pipeline.get_events()
        start_events = [e for e in events if e.event_type == AudioEventType.SPEECH_START]
        chunk_events = [e for e in events if e.event_type == AudioEventType.AUDIO_CHUNK]

        self.assertEqual(len(start_events), 1, "Must never emit duplicate SPEECH_START for continuous speech")
        self.assertEqual(len(chunk_events), 10, "Every chunk must produce a normalized AUDIO_CHUNK event")

        # Invariant: monotonic sequence ordering
        for i in range(len(events) - 1):
            self.assertLess(events[i].sequence_number, events[i + 1].sequence_number)

    def test_speech_end_event_emitted_after_silence_debounce(self) -> None:
        """Verify SPEECH_END is emitted with duration and metadata after silence exceeds hangover."""
        # 4 speech chunks (80ms) followed by 4 silence chunks (80ms > 60ms debounce)
        speech_chunks = generate_speech_fixture(num_chunks=4, amplitude=0.5)
        silence_chunks = [
            create_deterministic_chunk(sequence_id=4 + i, timestamp=0.08 + i * 0.02, amplitude=0.0)
            for i in range(4)
        ]

        for c in speech_chunks + silence_chunks:
            self.pipeline.process_chunk_direct(c)

        events = self.pipeline.get_events()
        start_events = [e for e in events if e.event_type == AudioEventType.SPEECH_START]
        end_events = [e for e in events if e.event_type == AudioEventType.SPEECH_END]

        self.assertEqual(len(start_events), 1, "Expected 1 SPEECH_START event")
        self.assertEqual(len(end_events), 1, "Expected 1 SPEECH_END event")

        start_evt = start_events[0]
        end_evt = end_events[0]

        # Verify speech segment pairing
        self.assertEqual(start_evt.segment_id, end_evt.segment_id)
        self.assertEqual(end_evt.session_id, self.session_id)
        self.assertEqual(end_evt.correlation_id, self.correlation_id)
        self.assertGreater(end_evt.timestamp, start_evt.timestamp)
        self.assertGreaterEqual(end_evt.metadata["total_speech_chunks"], 4)
        self.assertGreater(end_evt.metadata["speech_duration_ms"], 0.0)

    def test_event_ordering_strictly_deterministic(self) -> None:
        """Verify that events are emitted in strict chronological and sequential order."""
        speech = generate_speech_fixture(num_chunks=3, amplitude=0.5)
        silence = [
            create_deterministic_chunk(sequence_id=3 + i, timestamp=0.06 + i * 0.02, amplitude=0.0)
            for i in range(4)
        ]

        for c in speech + silence:
            self.pipeline.process_chunk_direct(c)

        events = self.pipeline.get_events()
        event_types = [e.event_type for e in events]

        # Invariant: SPEECH_START must occur before SPEECH_END
        self.assertIn(AudioEventType.SPEECH_START, event_types)
        self.assertIn(AudioEventType.SPEECH_END, event_types)
        start_idx = event_types.index(AudioEventType.SPEECH_START)
        end_idx = event_types.index(AudioEventType.SPEECH_END)
        self.assertLess(start_idx, end_idx, "SPEECH_START must precede SPEECH_END")

        # Monotonically increasing sequence numbers
        seq_nums = [e.sequence_number for e in events]
        self.assertEqual(seq_nums, list(range(len(events))))

        # Monotonically non-decreasing timestamps for all events
        timestamps = [round(e.timestamp, 5) for e in events]
        for i in range(len(timestamps) - 1):
            # The only exception is SPEECH_START which back-propagates the true onset timestamp
            if events[i + 1].event_type != AudioEventType.SPEECH_START:
                self.assertLessEqual(timestamps[i], timestamps[i + 1])

    def test_multiple_speech_segments_isolated_with_distinct_segment_ids(self) -> None:
        """Verify multiple speech bursts receive distinct segment IDs and sequential pairs."""
        # Utterance 1: 3 speech chunks (60ms) + 4 silence chunks (80ms)
        u1_speech = generate_speech_fixture(num_chunks=3, amplitude=0.5)
        u1_silence = [
            create_deterministic_chunk(sequence_id=3 + i, timestamp=0.06 + i * 0.02, amplitude=0.0)
            for i in range(4)
        ]
        # Utterance 2: 3 speech chunks (60ms) + 4 silence chunks (80ms)
        u2_speech = [
            create_deterministic_chunk(sequence_id=7 + i, timestamp=0.14 + i * 0.02, amplitude=0.5)
            for i in range(3)
        ]
        u2_silence = [
            create_deterministic_chunk(sequence_id=10 + i, timestamp=0.20 + i * 0.02, amplitude=0.0)
            for i in range(4)
        ]

        all_chunks = u1_speech + u1_silence + u2_speech + u2_silence
        for c in all_chunks:
            self.pipeline.process_chunk_direct(c)

        start_events = self.pipeline.get_events_by_type(AudioEventType.SPEECH_START)
        end_events = self.pipeline.get_events_by_type(AudioEventType.SPEECH_END)

        self.assertEqual(len(start_events), 2, "Must detect exactly 2 distinct speech onsets")
        self.assertEqual(len(end_events), 2, "Must detect exactly 2 distinct speech offsets")

        # Different segment IDs for each utterance
        self.assertNotEqual(start_events[0].segment_id, start_events[1].segment_id)
        self.assertEqual(start_events[0].segment_id, end_events[0].segment_id)
        self.assertEqual(start_events[1].segment_id, end_events[1].segment_id)

    def test_pure_silence_emits_no_speech_events(self) -> None:
        """Verify pure ambient silence emits only AUDIO_CHUNK events with is_speech=False."""
        chunks = generate_silence_fixture(num_chunks=10)

        for c in chunks:
            self.pipeline.process_chunk_direct(c)

        events = self.pipeline.get_events()
        start_events = [e for e in events if e.event_type == AudioEventType.SPEECH_START]
        end_events = [e for e in events if e.event_type == AudioEventType.SPEECH_END]

        chunk_events = [e for e in events if e.event_type == AudioEventType.AUDIO_CHUNK]
        silence_events = [e for e in events if e.event_type == AudioEventType.SILENCE]

        self.assertEqual(len(start_events), 0, "Silence must never trigger SPEECH_START")
        self.assertEqual(len(end_events), 0, "Silence must never trigger SPEECH_END")
        self.assertEqual(len(chunk_events), 10, "Every silence chunk produces an AUDIO_CHUNK event")
        self.assertGreaterEqual(len(silence_events), 1, "Transition to silence produces SILENCE event")
        for e in chunk_events:
            self.assertFalse(e.is_speech)
            self.assertIsNone(e.segment_id)

    def test_transient_noise_burst_rejected_by_vad_threshold(self) -> None:
        """Verify short click/noise burst (below min_speech_duration_ms) is rejected."""
        # 1 burst chunk (20ms) < 40ms threshold, followed by silence
        noise_fixture = generate_noise_burst_fixture(burst_chunks=1, total_chunks=6, amplitude=0.6)

        for c in noise_fixture:
            self.pipeline.process_chunk_direct(c)

        events = self.pipeline.get_events()
        start_events = [e for e in events if e.event_type == AudioEventType.SPEECH_START]
        end_events = [e for e in events if e.event_type == AudioEventType.SPEECH_END]

        self.assertEqual(len(start_events), 0, "Transient noise burst must not emit SPEECH_START")
        self.assertEqual(len(end_events), 0, "Transient noise burst must not emit SPEECH_END")

    def test_open_speech_segment_closed_on_pipeline_stop(self) -> None:
        """Verify that stopping the pipeline while speech is active safely emits SPEECH_END."""
        self.pipeline.start()
        # Feed speech chunks to trigger SPEECH_START
        speech = generate_speech_fixture(num_chunks=4, amplitude=0.5)
        for c in speech:
            self.pipeline.process_chunk_direct(c)

        self.assertIsNotNone(self.pipeline.active_segment_id)
        start_events = self.pipeline.get_events_by_type(AudioEventType.SPEECH_START)
        self.assertEqual(len(start_events), 1)

        # Stop while speech is still active
        self.pipeline.stop()

        self.assertIsNone(self.pipeline.active_segment_id)
        end_events = self.pipeline.get_events_by_type(AudioEventType.SPEECH_END)
        self.assertEqual(len(end_events), 1, "Stopping pipeline must complete open speech segment")
        self.assertEqual(end_events[0].segment_id, start_events[0].segment_id)
        self.assertEqual(end_events[0].metadata.get("reason"), "stream_stopped")

    def test_callback_and_polling_mechanisms(self) -> None:
        """Verify event callback dispatch and poll_events() queue draining."""
        dispatched: List[AudioEvent] = []
        p = AudioPipeline(
            session_id="callback-sess",
            correlation_id="callback-corr",
            on_event_callback=lambda evt: dispatched.append(evt),
        )
        c1 = create_deterministic_chunk(sequence_id=0, timestamp=0.0, amplitude=0.0)
        p.process_chunk_direct(c1)

        self.assertGreaterEqual(len(dispatched), 1)
        event_types = [e.event_type for e in dispatched]
        self.assertIn(AudioEventType.AUDIO_CHUNK, event_types)

        # poll_events drains the queue
        polled = p.poll_events()
        self.assertEqual(len(polled), len(dispatched))
        self.assertEqual(len(p.poll_events()), 0, "Second poll must be empty")


if __name__ == "__main__":
    unittest.main()

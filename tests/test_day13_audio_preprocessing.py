"""Tests for Week 2 – Day 13: Audio Preprocessing.

Covers all 13 test categories:
1. Valid audio input processing.
2. Empty audio input handling.
3. Invalid audio metadata / corrupt frame handling.
4. Audio already at target sample rate (fast-path passthrough).
5. Resampling between supported rates (44.1kHz, 48kHz, 8kHz -> 16kHz).
6. Duration preservation after resampling (within ±1%).
7. Mono and stereo handling (downmixing and preservation).
8. Audio normalization (scaling low amplitude).
9. Silent audio handling (no division by zero).
10. Prevention of clipping (strict [-32768, 32767] clamping).
11. Correct output metadata (format, timestamp, sequence_id).
12. Compatibility with existing STT pipeline (orchestrator integration).
13. Regression tests for AudioChunker and MockMicrophone compatibility.
"""

from __future__ import annotations

import math
import struct
import pytest

from src.audio.chunker import AudioChunker
from src.audio.mock_source import MockMicrophone
from src.audio.preprocessing import (
    AudioPreprocessor,
    convert_stereo_to_mono_pcm16,
    normalize_pcm16,
    resample_pcm16,
)
from src.schemas.audio import AudioChunk, AudioError, AudioFormat
from voice_stt.accumulator import OrderedSegmentAccumulator
from voice_stt.fake_transcriber import DeterministicFakeTranscriber
from voice_stt.orchestrator import TranscriptionOrchestrator


def _synthesize_pcm16_mono(num_samples: int, frequency: float = 440.0, sample_rate: int = 16000, peak: int = 16000) -> bytes:
    """Helper to synthesize a pure tone mono PCM16 byte string."""
    samples = []
    for i in range(num_samples):
        t = float(i) / float(sample_rate)
        val = int(round(peak * math.sin(2.0 * math.pi * frequency * t)))
        clamped = max(-32768, min(32767, val))
        samples.append(clamped)
    return struct.pack(f"<{num_samples}h", *samples)


def _synthesize_pcm16_stereo(num_frames: int, left_peak: int = 10000, right_peak: int = 20000) -> bytes:
    """Helper to synthesize interleaved stereo PCM16 byte string."""
    samples = []
    for i in range(num_frames):
        left_val = int(round(left_peak * math.sin(2.0 * math.pi * 440.0 * (i / 16000.0))))
        right_val = int(round(right_peak * math.sin(2.0 * math.pi * 880.0 * (i / 16000.0))))
        samples.append(max(-32768, min(32767, left_val)))
        samples.append(max(-32768, min(32767, right_val)))
    return struct.pack(f"<{num_frames * 2}h", *samples)


class TestDay13AudioPreprocessing:
    """Comprehensive test suite for Audio Preprocessing layer."""

    # Category 1: Valid audio input processing
    def test_01_valid_audio_input_processing(self) -> None:
        """A valid AudioChunk is preprocessed successfully and yields valid target attributes."""
        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
            normalize=True,
            target_peak=0.90,
        )
        raw_pcm = _synthesize_pcm16_mono(num_samples=320, sample_rate=16000, peak=10000)
        chunk = AudioChunk(
            sequence_id=1,
            timestamp=0.02,
            data=raw_pcm,
            format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
            metadata={"source": "test_mic"},
        )

        result = preprocessor.process_chunk(chunk)
        assert isinstance(result, AudioChunk)
        assert result.sequence_id == 1
        assert result.timestamp == 0.02
        assert result.format.sample_rate == 16000
        assert result.format.channels == 1
        assert result.metadata["preprocessed"] is True
        assert result.metadata["source"] == "test_mic"
        assert len(result.data) == len(raw_pcm)

    # Category 2: Empty audio input handling
    def test_02_empty_audio_input_handling(self) -> None:
        """Empty audio chunk or empty raw bytes raise AudioError with code EMPTY_CHUNK_DATA."""
        preprocessor = AudioPreprocessor()

        # Direct process_bytes with empty byte string
        with pytest.raises(AudioError) as exc_info:
            preprocessor.process_bytes(b"", AudioFormat(sample_rate=16000, channels=1))
        assert exc_info.value.code == "EMPTY_CHUNK_DATA"

        # Attempting to construct empty AudioChunk itself raises AudioError
        with pytest.raises(AudioError) as chunk_exc:
            AudioChunk(
                sequence_id=0,
                timestamp=0.0,
                data=b"",
                format=AudioFormat(sample_rate=16000, channels=1),
            )
        assert chunk_exc.value.code == "EMPTY_CHUNK_DATA"

    # Category 3: Invalid audio metadata / corrupt frame handling
    def test_03_invalid_audio_metadata_and_corrupt_frame(self) -> None:
        """Unaligned byte buffer or invalid target_peak raises appropriate AudioError."""
        preprocessor = AudioPreprocessor()

        # Unaligned data length for 16-bit mono (odd byte length: 3 bytes)
        with pytest.raises(AudioError) as exc_info:
            convert_stereo_to_mono_pcm16(b"\x01\x02\x03")
        assert exc_info.value.code == "CORRUPT_CHUNK_DATA"

        with pytest.raises(AudioError) as resample_exc:
            resample_pcm16(b"\x01\x02\x03", in_rate=44100, out_rate=16000, channels=1)
        assert resample_exc.value.code == "CORRUPT_CHUNK_DATA"

        # Invalid target_peak
        with pytest.raises(AudioError) as peak_exc:
            AudioPreprocessor(target_peak=0.0)
        assert peak_exc.value.code == "INVALID_TARGET_PEAK"

        with pytest.raises(AudioError) as peak_exc2:
            AudioPreprocessor(target_peak=1.5)
        assert peak_exc2.value.code == "INVALID_TARGET_PEAK"

        # Invalid sample rate in resample
        with pytest.raises(AudioError) as rate_exc:
            resample_pcm16(b"\x00\x00", in_rate=0, out_rate=16000)
        assert rate_exc.value.code == "INVALID_SAMPLE_RATE"

    # Category 4: Audio already at target sample rate (fast-path verification)
    def test_04_audio_already_at_target_sample_rate(self) -> None:
        """When input audio already matches target format and normalization is disabled, fast-path is used."""
        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
            normalize=False,
        )
        raw_pcm = _synthesize_pcm16_mono(num_samples=320, sample_rate=16000, peak=15000)
        chunk = AudioChunk(
            sequence_id=5,
            timestamp=0.1,
            data=raw_pcm,
            format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
        )

        result = preprocessor.process_chunk(chunk)
        # Fast path returns original chunk object directly
        assert result is chunk
        assert result.data == raw_pcm

        # resample_pcm16 fast path directly returns same bytes
        direct_resample = resample_pcm16(raw_pcm, in_rate=16000, out_rate=16000, channels=1)
        assert direct_resample == raw_pcm

    # Category 5: Resampling between supported rates
    @pytest.mark.parametrize("in_rate", [8000, 22050, 44100, 48000])
    def test_05_resampling_between_supported_rates(self, in_rate: int) -> None:
        """Audio at various source rates is accurately resampled to standard 16kHz."""
        out_rate = 16000
        # 0.1 seconds of audio at in_rate
        num_in_samples = int(in_rate * 0.1)
        raw_in = _synthesize_pcm16_mono(num_samples=num_in_samples, sample_rate=in_rate, peak=20000)

        chunk_in = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=raw_in,
            format=AudioFormat(sample_rate=in_rate, channels=1, sample_width=2),
        )

        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=out_rate, channels=1, sample_width=2),
            normalize=False,
        )
        chunk_out = preprocessor.process_chunk(chunk_in)

        assert chunk_out.format.sample_rate == 16000
        expected_out_samples = int(round(num_in_samples * (out_rate / in_rate)))
        actual_out_samples = len(chunk_out.data) // 2
        assert abs(actual_out_samples - expected_out_samples) <= 1

    # Category 6: Duration preservation after resampling
    def test_06_duration_preservation_after_resampling(self) -> None:
        """Signal duration is preserved within ±1% across resampling conversions."""
        rates_to_test = [(48000, 16000), (44100, 16000), (8000, 16000), (16000, 24000)]

        for in_rate, out_rate in rates_to_test:
            # 0.5 seconds duration
            target_duration = 0.5
            num_in_frames = int(in_rate * target_duration)
            raw_pcm = _synthesize_pcm16_mono(num_samples=num_in_frames, sample_rate=in_rate)

            resampled = resample_pcm16(raw_pcm, in_rate=in_rate, out_rate=out_rate, channels=1)
            num_out_frames = len(resampled) // 2

            in_duration = num_in_frames / float(in_rate)
            out_duration = num_out_frames / float(out_rate)

            # Within ±1% duration tolerance
            relative_diff = abs(out_duration - in_duration) / in_duration
            assert relative_diff < 0.01, f"Failed rate conversion {in_rate}->{out_rate}: diff {relative_diff:.4f}"

    # Category 7: Mono and stereo handling
    def test_07_mono_and_stereo_handling(self) -> None:
        """Stereo 2-channel audio is downmixed to mono; single channel mono is preserved."""
        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1, sample_width=2),
            normalize=False,
        )

        num_frames = 100
        left_samples = [1000 * (i % 10) for i in range(num_frames)]
        right_samples = [2000 * (i % 10) for i in range(num_frames)]
        interleaved = []
        for l, r in zip(left_samples, right_samples):
            interleaved.extend([l, r])

        stereo_bytes = struct.pack(f"<{num_frames * 2}h", *interleaved)
        stereo_chunk = AudioChunk(
            sequence_id=1,
            timestamp=0.0,
            data=stereo_bytes,
            format=AudioFormat(sample_rate=16000, channels=2, sample_width=2),
        )

        mono_chunk = preprocessor.process_chunk(stereo_chunk)
        assert mono_chunk.format.channels == 1
        assert len(mono_chunk.data) == num_frames * 2  # exactly half bytes of stereo

        # Verify averaged values: (1000*x + 2000*x) // 2 = 1500*x
        unpacked_mono = struct.unpack(f"<{num_frames}h", mono_chunk.data)
        for i, val in enumerate(unpacked_mono):
            expected_avg = (left_samples[i] + right_samples[i]) // 2
            assert val == expected_avg

    # Category 8: Audio normalization
    def test_08_audio_normalization(self) -> None:
        """Low-amplitude signal is properly amplified to match target peak."""
        num_samples = 200
        # Low amplitude peak of 2000 (out of 32767)
        raw_pcm = _synthesize_pcm16_mono(num_samples=num_samples, peak=2000)

        normalized = normalize_pcm16(raw_pcm, target_peak=0.95, sample_width=2)
        samples = struct.unpack(f"<{num_samples}h", normalized)
        max_peak = max(abs(s) for s in samples)

        expected_target = int(round(0.95 * 32767))
        # Within ±2 samples of the target integer peak
        assert abs(max_peak - expected_target) <= 2

    # Category 9: Silent audio handling
    def test_09_silent_audio_handling(self) -> None:
        """Completely silent audio does not crash, does not raise ZeroDivisionError, and remains silent."""
        silent_pcm = b"\x00\x00" * 320
        normalized = normalize_pcm16(silent_pcm, target_peak=0.95, sample_width=2)
        assert normalized == silent_pcm

        preprocessor = AudioPreprocessor(normalize=True, target_peak=0.95)
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=silent_pcm,
            format=AudioFormat(sample_rate=16000, channels=1),
        )
        result = preprocessor.process_chunk(chunk)
        assert result.data == silent_pcm

    # Category 10: Prevention of clipping
    def test_10_prevention_of_clipping(self) -> None:
        """High amplitude and edge samples are strictly clamped within [-32768, 32767]."""
        extreme_samples = [-32768, 32767, -25000, 25000, -100, 100]
        raw_pcm = struct.pack(f"<{len(extreme_samples)}h", *extreme_samples)

        # Target peak 1.0
        normalized = normalize_pcm16(raw_pcm, target_peak=1.0)
        unpacked = struct.unpack(f"<{len(extreme_samples)}h", normalized)

        for s in unpacked:
            assert -32768 <= s <= 32767

        # Stereo averaging with maximum positive and minimum negative values
        stereo_extremes = struct.pack("<4h", 32767, 32767, -32768, -32768)
        mono_extremes = convert_stereo_to_mono_pcm16(stereo_extremes)
        unpacked_stereo = struct.unpack("<2h", mono_extremes)
        assert unpacked_stereo[0] == 32767
        assert unpacked_stereo[1] == -32768

    # Category 11: Correct output metadata
    def test_11_correct_output_metadata(self) -> None:
        """Output chunk retains sequence ID and timestamp while carrying preprocessing metadata."""
        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1),
            normalize=True,
        )
        raw_pcm = _synthesize_pcm16_stereo(num_frames=480)  # 480 frames stereo
        in_chunk = AudioChunk(
            sequence_id=42,
            timestamp=1.25,
            data=raw_pcm,
            format=AudioFormat(sample_rate=48000, channels=2),
            metadata={"session_tag": "stream-99"},
        )

        out_chunk = preprocessor.process_chunk(in_chunk)
        assert out_chunk.sequence_id == 42
        assert out_chunk.timestamp == 1.25
        assert out_chunk.format.sample_rate == 16000
        assert out_chunk.format.channels == 1
        assert out_chunk.metadata["session_tag"] == "stream-99"
        assert out_chunk.metadata["preprocessed"] is True
        assert out_chunk.metadata["original_format"]["sample_rate"] == 48000
        assert out_chunk.metadata["original_format"]["channels"] == 2
        assert out_chunk.metadata["original_byte_length"] == len(raw_pcm)

    # Category 12: Compatibility with existing STT pipeline
    def test_12_compatibility_with_existing_stt_pipeline(self) -> None:
        """Preprocessed chunk seamlessly flows through TranscriptionOrchestrator and OrderedSegmentAccumulator."""
        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1),
            normalize=True,
        )
        fake_transcriber = DeterministicFakeTranscriber()
        accumulator = OrderedSegmentAccumulator()
        orchestrator = TranscriptionOrchestrator(
            adapter=fake_transcriber,
            accumulator=accumulator,
            preprocessor=preprocessor,
        )
        orchestrator.initialize()

        # Input 44.1kHz stereo audio
        num_frames = 882  # ~20ms at 44.1kHz
        raw_stereo = _synthesize_pcm16_stereo(num_frames=num_frames, left_peak=12000, right_peak=14000)
        chunk = AudioChunk(
            sequence_id=0,
            timestamp=0.0,
            data=raw_stereo,
            format=AudioFormat(sample_rate=44100, channels=2),
        )

        events = orchestrator.process_chunk(chunk, is_last=True)
        assert len(events) > 0
        final_events = [e for e in events if e.event_type.value == "final"]
        assert len(final_events) >= 1
        assert len(orchestrator.get_full_transcript()) > 0
        assert orchestrator.get_status().chunks_processed == 1

    # Category 13: Regression tests for AudioChunker and MockMicrophone compatibility
    def test_13_regression_cases_audio_chunker_and_mock_microphone(self) -> None:
        """Audio chunks generated by Week 1 MockMicrophone and AudioChunker process cleanly."""
        # 1. MockMicrophone with 48kHz stereo configuration
        mic = MockMicrophone(
            audio_format=AudioFormat(sample_rate=48000, channels=2),
            chunk_duration_ms=20.0,
            frequency_hz=440.0,
            total_duration_sec=0.1,  # 5 chunks
        )
        chunks = list(mic.stream())
        assert len(chunks) == 5

        preprocessor = AudioPreprocessor(
            target_format=AudioFormat(sample_rate=16000, channels=1),
            normalize=True,
        )

        # Stream preprocessing
        preprocessed_chunks = list(preprocessor.process_stream(chunks))
        assert len(preprocessed_chunks) == 5

        for orig, prep in zip(chunks, preprocessed_chunks):
            assert prep.sequence_id == orig.sequence_id
            assert prep.timestamp == orig.timestamp
            assert prep.format.sample_rate == 16000
            assert prep.format.channels == 1
            # 20ms at 16kHz mono = 320 frames * 2 bytes = 640 bytes
            assert len(prep.data) == 640

        # 2. AudioChunker slicing and feeding into preprocessor
        chunker = AudioChunker(
            audio_format=AudioFormat(sample_rate=8000, channels=1),
            chunk_duration_ms=25.0,
        )
        raw_pcm_8k = _synthesize_pcm16_mono(num_samples=800, sample_rate=8000)  # 100ms
        chunker_output = list(chunker.chunk_stream(raw_pcm_8k))
        assert len(chunker_output) == 4

        preprocessed_chunker_output = list(preprocessor.process_stream(chunker_output))
        assert len(preprocessed_chunker_output) == 4
        for chunk in preprocessed_chunker_output:
            assert chunk.format.sample_rate == 16000
            assert chunk.format.channels == 1

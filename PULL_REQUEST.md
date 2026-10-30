# Pull Request: W1 Foundation — Typed Audio Schemas, Deterministic Mock Microphone, and CLI Demo

**Branch:** `feature/w1-audio-foundation` -> `main`  
**Workstream:** W1 – Audio and VAD  
**Author:** Harshita G Kademani (SDE 3)  
**Project:** AI Voice Copilot  
**Status:** Ready for Review  

---

## 1. Description & Context

This PR delivers the foundational vertical slice of the AI Voice Copilot audio pipeline for **Week 1 (Day 1–Day 7)**.

All subsequent pipeline modules (Voice Activity Detection / VAD, audio buffering, Speech-to-Text / Whisper, and Agent Orchestrator integration) depend on these contracts. The schemas are defined once in the team project folder to ensure zero duplication and strict consistency.

> [!NOTE]
> **Primary Demonstration vs. Optional Feature:**
> - **Primary Week 1 Deliverable & Demonstration:** The **single-command CLI demo (`python -m src.cli`)** is the primary, required demonstration for Week 1. It requires **zero third-party dependencies** and runs directly using Python's standard library.
> - **Optional Showcase Feature:** The local FastAPI web dashboard & live waveform visualizer (`src/server.py` & `src/static/index.html`) is provided as an **optional supplemental showcase tool** for interactive developer exploration. It is **not** part of the mandatory Week 1 acceptance criteria, and installing `requirements.txt` is only required if running this visualizer.

### Key Deliverables Included:
1. **Typed Audio Schemas (`src/schemas/audio.py`)**:
   - `AudioFormat`: Validates sample rate (Hertz), channels (mono/stereo), sample width (1, 2, 4 bytes), and codec encoding matching sample width (`pcm_u8`, `pcm_s8`, `pcm_s16le`, `pcm_s16be`, `pcm_s32le`, `pcm_s32be`, `pcm_f32le`, `pcm_f32be`).
   - `AudioChunk`: Slices of raw PCM data with strictly increasing sequence IDs, finite timing offsets in seconds (rejects NaN/inf), byte size, duration in ms, defensive copying of `bytearray` inputs for immutability, and base64 serialization.
   - `AudioError`: Standardized error exception adhering to the SDD API specification format (Doc 04 section 5) including `code`, `message`, optional `request_id`, and `details`.
   - Robust `from_dict()` validation: strictly validates required fields (`sample_rate`, `channels`), preventing silent default assignments, and wraps missing keys, non-dict payloads, and corrupted base64 in `AudioError`.
2. **Deterministic Audio Chunker (`src/audio/chunker.py`)**:
   - Chunks continuous raw PCM streams into fixed-duration `AudioChunk`s.
   - Guaranteed determinism: identical input always yields identical chunk objects across runs.
   - Stream-level ordering validator (`AudioChunker.validate_sequence`) enforcing strictly increasing sequence IDs and advancing timestamps.
3. **Deterministic Mock Microphone Source (`src/audio/mock_source.py`)**:
   - Emits synthetic linear PCM `AudioChunk`s supporting 1-byte, 2-byte, and 4-byte sample widths with accurate byte lengths and zero timestamp drift.
   - Safe finite default duration (1.0 s) preventing runaway loops while permitting explicit unbounded streaming (`total_duration_sec=None`).
   - Monotonically increasing sequence IDs and timestamps with rounding overshoot protection.
   - Supports both offline batch generation and simulated real-time hardware mic pacing.
   - Fully reproducible stream replay via `.reset()`.
4. **Single-Command CLI Demo (`src/cli.py`)**:
   - Primary Week 1 demonstration tool: `python -m src.cli` streams and inspects chunk metadata in a clean tabular view.
5. **Comprehensive Unit Test Suite (`tests/`)**:
   - 45 tests covering happy path, invalid inputs, finite timestamp checks (NaN / inf), encoding validation, defensive copies, empty chunks (`EMPTY_CHUNK_DATA`), corrupt chunks (`CORRUPT_CHUNK_DATA`), stream sequence ordering, determinism, and streaming.
   - **Zero-Dependency Execution:** Core pipeline and all 45 tests run entirely on Python's built-in standard library with no external package installations required.
6. **Optional Local Visualizer Dashboard & API (`src/server.py`, `src/static/index.html`)**:
   - FastAPI-powered real-time SSE stream, waveform canvas visualizer, and live test runner (optional supplement).
7. **Project Hygiene (`.gitignore`, `requirements.txt`)**:
   - Excludes Python caches, virtual environments, build artifacts, and guarantees no secrets, personal recordings, or private data are committed.

---

## 2. Files Changed

- `.gitignore`: Standard Python and security ignore rules.
- `requirements.txt`: Optional web visualizer dependencies (`fastapi`, `uvicorn`).
- `README.md`: Architecture overview, schema contracts, CLI instructions, and test guide.
- `DAILY_PROGRESS_REPORT.md`: Daily progress logs for Day 1 through Day 7.
- `PULL_REQUEST.md`: Pull request documentation with test output.
- `src/__init__.py`: Package initialization.
- `src/schemas/__init__.py`: Re-exports canonical contracts.
- `src/schemas/audio.py`: Single canonical definition of `AudioFormat`, `AudioChunk`, and `AudioError`.
- `src/audio/__init__.py`: Exports `AudioChunker` and `MockMicrophone`.
- `src/audio/chunker.py`: Deterministic audio chunker implementation.
- `src/audio/mock_source.py`: Mock microphone source with continuous PCM synthesis.
- `src/cli.py`: Single documented CLI demo runner.
- `src/server.py`: FastAPI server for real-time visualization and on-demand test runner.
- `src/static/index.html`: Interactive glassmorphic visualizer dashboard with HTML5 canvas.
- `tests/__init__.py`: Test suite initialization.
- `tests/test_schemas.py`: Schema happy path, serialization, and properties tests.
- `tests/test_audio_errors.py`: Negative testing (invalid rates, channels, empty data, corrupt chunks, NaN/inf, encodings, bytearray defensive copies, from_dict).
- `tests/test_chunker.py`: Chunker determinism and timing tests.
- `tests/test_mock_source.py`: Mock microphone streaming, replay, multi-byte widths (1, 2, 4), and overshoot protection tests.

---

## 3. Test Output & Verification

> **Zero Extra Installation Note:** All 45 tests execute using Python's standard library `unittest` module without installing any external packages (`pip install` is only needed for the optional FastAPI web server).

### Unit Test Execution:
```powershell
python -m unittest discover tests -v
```

```
test_audio_error_serialization (test_audio_errors.TestAudioErrors.test_audio_error_serialization)
AudioError.to_dict() must conform to the system design error payload. ... ok
test_audio_error_with_request_id (test_audio_errors.TestAudioErrors.test_audio_error_with_request_id)
AudioError supports request_id in initialization and to_dict per Doc 04 section 5. ... ok
test_chunk_bytearray_defensive_copy (test_audio_errors.TestAudioErrors.test_chunk_bytearray_defensive_copy)
AudioChunk must defensively copy bytearray data to maintain immutability. ... ok
test_chunk_from_dict_error_handling (test_audio_errors.TestAudioErrors.test_chunk_from_dict_error_handling)
AudioChunk.from_dict wraps missing keys, non-dict payloads, and bad base64 in AudioError. ... ok
test_corrupt_chunk_data_unaligned_frame_size (test_audio_errors.TestAudioErrors.test_corrupt_chunk_data_unaligned_frame_size)
Audio chunk data not aligned to frame size must raise AudioError with CORRUPT_CHUNK_DATA. ... ok
test_empty_chunk_data (test_audio_errors.TestAudioErrors.test_empty_chunk_data)
Empty audio bytes (b'') must raise AudioError with code EMPTY_CHUNK_DATA. ... ok
test_encoding_incompatible_with_sample_width (test_audio_errors.TestAudioErrors.test_encoding_incompatible_with_sample_width)
Encoding must be compatible with sample_width (e.g. 16-bit encoding with 4-byte width fails). ... ok
test_invalid_channels_count (test_audio_errors.TestAudioErrors.test_invalid_channels_count)
Channels count outside {1, 2} must raise AudioError. ... ok
test_invalid_channels_type (test_audio_errors.TestAudioErrors.test_invalid_channels_type)
Non-integer channels type must raise AudioError. ... ok
test_invalid_chunk_data_type (test_audio_errors.TestAudioErrors.test_invalid_chunk_data_type)
Chunk data that is not bytes or bytearray must raise AudioError. ... ok
test_invalid_chunk_sequence_id (test_audio_errors.TestAudioErrors.test_invalid_chunk_sequence_id)
Negative or non-integer sequence IDs must raise AudioError. ... ok
test_invalid_chunk_timestamp (test_audio_errors.TestAudioErrors.test_invalid_chunk_timestamp)
Negative or non-numeric timestamps must raise AudioError. ... ok
test_invalid_chunk_timestamp_nan_and_infinity (test_audio_errors.TestAudioErrors.test_invalid_chunk_timestamp_nan_and_infinity)
NaN, +inf, and -inf timestamps must be rejected with AudioError. ... ok
test_invalid_encoding_names (test_audio_errors.TestAudioErrors.test_invalid_encoding_names)
Arbitrary / unsupported encoding names like 'banana' must raise AudioError. ... ok
test_invalid_sample_rate_negative_or_zero (test_audio_errors.TestAudioErrors.test_invalid_sample_rate_negative_or_zero)
Negative and zero sample rates must raise AudioError. ... ok
test_invalid_sample_rate_type (test_audio_errors.TestAudioErrors.test_invalid_sample_rate_type)
Non-integer sample rate types (strings, floats, bools) must raise AudioError. ... ok
test_invalid_sample_width_and_encoding (test_audio_errors.TestAudioErrors.test_invalid_sample_width_and_encoding)
Invalid sample width or empty encoding must raise AudioError. ... ok
test_unsupported_sample_rate (test_audio_errors.TestAudioErrors.test_unsupported_sample_rate)
Unsupported sample rates (e.g. 12345 Hz) must raise AudioError. ... ok
test_chunker_corrupt_input_raises_error (test_chunker.TestAudioChunker.test_chunker_corrupt_input_raises_error)
Corrupt audio data with unaligned byte length must raise AudioError. ... ok
test_chunker_custom_start_offset (test_chunker.TestAudioChunker.test_chunker_custom_start_offset)
Chunker respects start_sequence_id and start_timestamp offsets. ... ok
test_chunker_deterministic_output (test_chunker.TestAudioChunker.test_chunker_deterministic_output)
Same input data must produce byte-for-byte identical AudioChunks on repeated runs. ... ok
test_chunker_empty_input_raises_error (test_chunker.TestAudioChunker.test_chunker_empty_input_raises_error)
Empty raw audio input must raise AudioError with EMPTY_CHUNK_DATA. ... ok
test_chunker_invalid_start_offsets (test_chunker.TestAudioChunker.test_chunker_invalid_start_offsets)
Chunker rejects negative or non-finite start sequence IDs and timestamps. ... ok
test_chunker_monotonic_sequence_and_timestamps (test_chunker.TestAudioChunker.test_chunker_monotonic_sequence_and_timestamps)
Chunker must output strictly monotonically increasing sequence IDs and timestamps. ... ok
test_chunker_properties (test_chunker.TestAudioChunker.test_chunker_properties)
AudioChunker computes correct frame and byte counts. ... ok
test_validate_sequence_rejects_out_of_order_sequences (test_chunker.TestAudioChunker.test_validate_sequence_rejects_out_of_order_sequences)
AudioChunker.validate_sequence rejects non-increasing sequence IDs and non-advancing timestamps. ... ok
test_validate_sequence_valid_stream (test_chunker.TestAudioChunker.test_validate_sequence_valid_stream)
AudioChunker.validate_sequence passes on valid strictly monotonically increasing streams. ... ok
test_mock_microphone_chunk_emission (test_mock_source.TestMockMicrophone.test_mock_microphone_chunk_emission)
MockMicrophone emits valid chunks with increasing sequence IDs and timestamps. ... ok
test_mock_microphone_defaults (test_mock_source.TestMockMicrophone.test_mock_microphone_defaults)
MockMicrophone default initialization has a safe finite 1.0s duration limit. ... ok
test_mock_microphone_determinism (test_mock_source.TestMockMicrophone.test_mock_microphone_determinism)
Two separate MockMicrophone instances with identical parameters produce 100% identical streams. ... ok
test_mock_microphone_duration_overshoot_protection (test_mock_source.TestMockMicrophone.test_mock_microphone_duration_overshoot_protection)
MockMicrophone does not overshoot requested total duration due to sample rounding. ... ok
test_mock_microphone_explicit_unbounded_streaming (test_mock_source.TestMockMicrophone.test_mock_microphone_explicit_unbounded_streaming)
MockMicrophone with total_duration_sec=None allows continuous unbounded streaming. ... ok
test_mock_microphone_invalid_parameters (test_mock_source.TestMockMicrophone.test_mock_microphone_invalid_parameters)
Invalid microphone parameters raise AudioError. ... ok
test_mock_microphone_reset (test_mock_source.TestMockMicrophone.test_mock_microphone_reset)
Resetting a MockMicrophone produces the exact same stream again. ... ok
test_mock_microphone_sample_width_1_synthesis (test_mock_source.TestMockMicrophone.test_mock_microphone_sample_width_1_synthesis)
MockMicrophone synthesizes 8-bit (1-byte) samples with correct byte sizes. ... ok
test_mock_microphone_sample_width_4_synthesis (test_mock_source.TestMockMicrophone.test_mock_microphone_sample_width_4_synthesis)
MockMicrophone synthesizes 32-bit (4-byte) samples with correct byte sizes and zero timestamp drift. ... ok
test_mock_microphone_stereo_and_high_sample_rate (test_mock_source.TestMockMicrophone.test_mock_microphone_stereo_and_high_sample_rate)
MockMicrophone supports stereo channels and 48kHz digital rate. ... ok
test_audio_chunk_from_dict_with_incomplete_format (test_schemas.TestAudioSchemas.test_audio_chunk_from_dict_with_incomplete_format)
AudioChunk.from_dict rejects malformed or incomplete nested format dictionaries. ... ok
test_audio_chunk_serialization (test_schemas.TestAudioSchemas.test_audio_chunk_serialization)
AudioChunk should serialize to dict with base64 and deserialize cleanly. ... ok
test_audio_chunk_valid_happy_path (test_schemas.TestAudioSchemas.test_audio_chunk_valid_happy_path)
AudioChunk should instantiate with valid parameters and compute metrics. ... ok
test_audio_format_defaults (test_schemas.TestAudioSchemas.test_audio_format_defaults)
AudioFormat should default to 16kHz mono 16-bit PCM. ... ok
test_audio_format_from_dict_validation (test_schemas.TestAudioSchemas.test_audio_format_from_dict_validation)
AudioFormat.from_dict validates required fields and does not silently default missing keys. ... ok
test_audio_format_serialization (test_schemas.TestAudioSchemas.test_audio_format_serialization)
AudioFormat should serialize to dict and deserialize back losslessly. ... ok
test_audio_format_stereo (test_schemas.TestAudioSchemas.test_audio_format_stereo)
AudioFormat should calculate stereo frame size and throughput correctly. ... ok
test_schema_documentation (test_schemas.TestAudioSchemas.test_schema_documentation)
Ensure schemas have non-empty docstrings explaining fields and constraints. ... ok

----------------------------------------------------------------------
Ran 45 tests in 0.067s

OK
```

### CLI Demo Execution:
```powershell
python -m src.cli --duration 0.1 --chunk-ms 20
```

```
======================================================================================
AI Voice Copilot - Audio Pipeline Demonstration (W1)
Workstream: W1 - Audio and VAD | Student: Harshita G Kademani (SDE 3)
(Simulated mock microphone source; no physical microphone hardware required)
======================================================================================

[Configuration]
  * Sample Rate    : 16000 Hz
  * Channels       : 1 (Mono)
  * Bit Depth      : 16-bit PCM (pcm_s16le)
  * Frame Size     : 2 bytes
  * Chunk Duration : 20.0 ms
  * Stream Duration: 0.1 s 
  * Tone Frequency : 440.0 Hz
  * Mode           : Fast deterministic batch

[Streaming AudioChunks]
-------------------------------------------------------------------------------
  Seq ID |   Timestamp |   Chunk Size |   Sample Rate |   Channels |   Duration
-------------------------------------------------------------------------------
       0 |      0.000s |        640 B |      16000 Hz |   1 (Mono) |    20.0 ms
       1 |      0.020s |        640 B |      16000 Hz |   1 (Mono) |    20.0 ms
       2 |      0.040s |        640 B |      16000 Hz |   1 (Mono) |    20.0 ms
       3 |      0.060s |        640 B |      16000 Hz |   1 (Mono) |    20.0 ms
       4 |      0.080s |        640 B |      16000 Hz |   1 (Mono) |    20.0 ms
-------------------------------------------------------------------------------

[Stream Summary]
  * Total Chunks Emitted: 5
  * Total Audio Duration: 0.100 s (100.0 ms)
  * Total Bytes Streamed: 3200 bytes
  * Stream Status       : COMPLETED SUCCESSFUL (Deterministic & Validated)
======================================================================================
```

---

## 4. Acceptance Criteria Checklist

- [x] **All three schemas exist, are defined once, and are documented**
- [x] **Invalid sample rate / channel count is rejected with AudioError**
- [x] **Mock source output is deterministic (two runs on same input give identical chunks)**
- [x] **Every chunk has a timestamp and a strictly increasing sequence ID**
- [x] **CLI runs with a single documented command and shows the stream**
- [x] **Tests cover invalid, empty, and corrupt chunks; all 45 tests pass**
- [x] **Mock microphone respects sample_width (1, 2, 4 bytes) without byte size or timestamp drift**
- [x] **Mock microphone provides safe finite default duration (1.0s) and supports unbounded streaming**
- [x] **Timestamp validation strictly rejects NaN, +inf, and -inf**
- [x] **Stream-level validation enforces monotonic sequence IDs and timestamps**
- [x] **AudioError conforms to Doc 04, section 5 with optional request_id**
- [x] **AudioChunk performs defensive copy of bytearray inputs to preserve immutability**
- [x] **from_dict strictly validates required fields and wraps all errors in AudioError**
- [x] **Encoding validated against sample_width and rejects arbitrary identifiers (including pcm_f32be)**
- [x] **Stream duration overshoot protection at non-round sample rates (e.g. 22050 Hz)**
- [x] **All files staged and committed (including server.py, static dashboard, requirements.txt)**
- [x] **Work is on a feature branch (`feature/w1-audio-foundation`); no direct pushes to main**
- [x] **PR description includes full test output; no secrets/recordings/personal data are committed**
- [x] **Day 7 demo completed (CLI demonstration verified; optional web visualizer available)**

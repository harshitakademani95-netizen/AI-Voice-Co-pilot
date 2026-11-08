# Pull Request: [W2] Speech-to-Text Pipeline Foundation & Mock Vertical Slice

**PR Branch:** `feature/w2-speech-to-text-foundation` &rarr; **Target Branch:** `main`  
**Author:** Disha D K (SDE 3)  
**Workstream:** W2 – Speech-to-text  
**Duration:** Day 1 – Day 7 (Week 1 – Foundation and first vertical slice)  
**Related Documents:** `01. PRD`, `02. SDD`, `03. Technical Architecture & Design`, `04. API Specifications & Interface Contracts`

---

## 1. Description & Purpose

This PR delivers the complete Week 1 foundation for the **Speech-to-Text (STT)** pipeline (Workstream W2) of the **AI Voice Co-Pilot** platform.

Subsequent milestones (orchestration in Week 2, de-duplication, agentic context linking, and multi-team integration) depend strictly on these contracts. All components are self-contained, fully documented, and runnable in **deterministic mock mode with zero paid API keys or external network dependencies**.

An interactive web dashboard is included as **optional extra scope** for live visual demonstration and manual audit, strictly decoupled from core pipeline contracts.

---

## 2. Changes Since First Draft

1. **Error Schema Contract (Doc 04, Section 5):**
   - Added optional field `request_id: Optional[str] = None` to `STTErrorDetail`.
   - Added `.to_api_error() -> Dict[str, Any]` returning `{"error": {"code", "message", "request_id", "retryable", "details"}}` conforming to API Specifications & Interface Contracts (doc 04), Section 5.
   - Updated documentation and citations from "SDD Section 5" to "API Specifications & Interface Contracts (doc 04), Section 5".
   - Verified that sensitive credentials (`sk-...`, `Bearer ...`, `password`) in error messages are rejected.

2. **Honest Timestamp Semantics:**
   - Explicitly documented that real adapters emit wall-clock POSIX epoch time, whereas `DeterministicFakeTranscriber` uses a simulated audio clock (`seconds since stream start`) so mock runs remain 100% reproducible and bit-for-bit deterministic.

3. **Adapter & Fake Transcriber Enhancements:**
   - Fixed `_coerce_audio_chunk` to honor `is_last=True` when receiving already-instantiated `AudioChunk` objects (`chunk.model_copy(update={"is_last": True})`).
   - Implemented one-item lookahead in `transcribe_stream` so streams ending without explicit `is_last=True` flags flush all pending words. Empty streams return cleanly without raising.
   - Emitted `TranscriptEventType.STREAM_COMPLETED` (with `segment=None`, `error=None`, deterministic UUID5, and monotonic sequence counter) at stream termination in script and hash modes.
   - Documented `speech_started` and `speech_ended` as reserved for real-provider VAD adapters.

4. **Accumulator Telemetry Accuracy:**
   - Removed misleading `_chunks_processed` and `chunks_processed` from `OrderedSegmentAccumulator` summary and reset methods, clarifying that the accumulator ingests events rather than chunks.
   - Verified that lifecycle events like `STREAM_COMPLETED` are ingested cleanly without mutating committed final segments.

5. **Demo Endpoint Isolation:**
   - Renamed demo server routes from `/api/v1/...` to `/demo/health`, `/demo/stream`, `/demo/audit`, `/demo/reset` to prevent collision with Backend team endpoints.
   - Restricted server binding to localhost `127.0.0.1`.

6. **Documentation & Repo Hygiene:**
   - Updated `README.md` with repo-relative paths, cross-platform run commands, error envelope specification, event lifecycle details, and exact test suite metrics (81 tests passed).
   - Added sentence timestamp regression tests (`TestSentenceTimestampSpanRegression`) ensuring multi-chunk sentences correctly use the first chunk's start time across scripted and hash modes.

---

## 3. Acceptance Criteria Verification

| Acceptance Criterion | Status | Evidence / Verification Test |
| :--- | :---: | :--- |
| **TranscriptSegment and TranscriptEvent schemas exist, defined once, documented** | **PASS** | `src/voice_stt/schemas.py`, `tests/test_schemas.py::TestTranscriptSegmentSchema`, `TestTranscriptEventSchema` |
| **Invalid payloads are rejected with clear errors** | **PASS** | `tests/test_twenty_requirements.py::test_03_missing_required_fields` through `test_08_malformed_error_events`, Fixture E |
| **Fake transcriber is deterministic** | **PASS** | `tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_determinism_scripted_mode`, `test_determinism_hash_mode`, `tests/test_twenty_requirements.py::test_16_deterministic_repeated_mock_runs` |
| **Adapter is provider-neutral; no paid API keys needed** | **PASS** | `src/voice_stt/adapter.py`, `tests/test_adapter_and_fake.py::TestAdapterInterfaceContract::test_abstract_class_cannot_be_instantiated` |
| **Accumulator returns segments in order** | **PASS** | `tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_out_of_order_arrival_reordered_chronologically`, `tests/test_twenty_requirements.py::test_10_out_of_order_event_arrival`, Fixture C |
| **Tests pass and cover boundary & failure behaviour** | **PASS** | **81 passed in 0.22s** across 5 test suites covering normal, edge case, and fault scenarios |
| **Work is on a feature branch; no direct pushes to main** | **PASS** | Active working branch: `feature/w2-speech-to-text-foundation` |
| **No secrets, recordings, or machine-specific paths committed** | **PASS** | Grep audit confirmed zero absolute user paths, zero credentials; `.gitignore` covers caches and audio files |
| **Day 7 demo completed in mock mode** | **PASS** | `demo/live_demo.py --all` executes cleanly for Fixtures A–F; interactive server verified at `http://127.0.0.1:8000` |

---

## 4. Test Suite Execution Output (Verbatim)

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0 -- C:\Users\Disha D K\OneDrive\Desktop\AI Voice Co-Pilot\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\Disha D K\OneDrive\Desktop\AI Voice Co-Pilot
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collecting ... collected 81 items

tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_in_order_accumulation PASSED [  1%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_out_of_order_arrival_reordered_chronologically PASSED [  2%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_interim_lifecycle_replacement_and_finalization PASSED [  3%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_duplicate_segment_rejection PASSED [  4%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_error_event_does_not_corrupt_final_segments PASSED [  6%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_metrics_and_summary PASSED [  7%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_reset_clears_all_state PASSED [  8%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_summary_has_no_stale_chunks_processed_counter PASSED [  9%]
tests/test_accumulator.py::TestOrderedSegmentAccumulator::test_stream_completed_event_ingestion_preserves_final_segments PASSED [ 11%]
tests/test_adapter_and_fake.py::TestAdapterInterfaceContract::test_abstract_class_cannot_be_instantiated PASSED [ 12%]
tests/test_adapter_and_fake.py::TestAdapterInterfaceContract::test_context_manager_lifecycle PASSED [ 13%]
tests/test_adapter_and_fake.py::TestAdapterInterfaceContract::test_transcribe_on_closed_adapter_fails PASSED [ 14%]
tests/test_adapter_and_fake.py::TestAdapterInterfaceContract::test_status_telemetry_reporting PASSED [ 16%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_determinism_scripted_mode PASSED [ 17%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_determinism_hash_mode PASSED [ 18%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_reset_yields_identical_subsequent_sequence PASSED [ 19%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_simulated_error_injection PASSED [ 20%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_interim_flag_configuration_disabled PASSED [ 22%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_is_last_argument_honoured_for_audio_chunk PASSED [ 23%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_stream_without_is_last_flushes PASSED [ 24%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_empty_stream_yields_nothing_and_does_not_raise PASSED [ 25%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_stream_completed_emitted_exactly_once_and_last PASSED [ 27%]
tests/test_adapter_and_fake.py::TestDeterministicFakeTranscriber::test_stream_completed_not_emitted_after_injected_error PASSED [ 28%]
tests/test_adapter_and_fake.py::TestSentenceTimestampSpanRegression::test_scripted_multi_chunk_sentence_uses_first_chunk_start_time PASSED [ 29%]
tests/test_adapter_and_fake.py::TestSentenceTimestampSpanRegression::test_scripted_multi_sentence_fresh_start_timestamp PASSED [ 30%]
tests/test_adapter_and_fake.py::TestSentenceTimestampSpanRegression::test_hash_mode_multi_chunk_sentence_and_word_timings PASSED [ 32%]
tests/test_adapter_and_fake.py::TestSentenceTimestampSpanRegression::test_reset_and_flush_do_not_retain_stale_timestamps PASSED [ 33%]
tests/test_adapter_and_fake.py::TestSentenceTimestampSpanRegression::test_interim_hypotheses_track_sentence_start_timestamp PASSED [ 34%]
tests/test_end_to_end_flow.py::TestEndToEndPipeline::test_mock_chunk_to_transcript_flow PASSED [ 35%]
tests/test_schemas.py::TestWordTimingSchema::test_valid_word_timing PASSED [ 37%]
tests/test_schemas.py::TestWordTimingSchema::test_zero_duration_word_boundary_allowed PASSED [ 38%]
tests/test_schemas.py::TestWordTimingSchema::test_reject_inverted_word_timestamps PASSED [ 39%]
tests/test_schemas.py::TestWordTimingSchema::test_reject_negative_word_timestamp PASSED [ 40%]
tests/test_schemas.py::TestWordTimingSchema::test_reject_out_of_range_confidence PASSED [ 41%]
tests/test_schemas.py::TestWordTimingSchema::test_reject_empty_word PASSED [ 43%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_valid_segment_creation PASSED [ 44%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_inverted_segment_timestamps PASSED [ 45%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_negative_segment_start_time PASSED [ 46%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_confidence_exceeding_unity PASSED [ 48%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_invalid_language_tag PASSED [ 49%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_empty_language_tag PASSED [ 50%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_word_timing_exceeding_segment_boundary PASSED [ 51%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_reject_extra_unexpected_field PASSED [ 53%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_json_roundtrip_serialization PASSED [ 54%]
tests/test_schemas.py::TestTranscriptSegmentSchema::test_transcript_segment_immutability PASSED [ 55%]
tests/test_schemas.py::TestTranscriptEventSchema::test_valid_interim_event PASSED [ 56%]
tests/test_schemas.py::TestTranscriptEventSchema::test_valid_final_event PASSED [ 58%]
tests/test_schemas.py::TestTranscriptEventSchema::test_reject_interim_event_without_segment PASSED [ 59%]
tests/test_schemas.py::TestTranscriptEventSchema::test_reject_final_event_without_segment PASSED [ 60%]
tests/test_schemas.py::TestTranscriptEventSchema::test_reject_mismatched_interim_event_with_final_segment PASSED [ 61%]
tests/test_schemas.py::TestTranscriptEventSchema::test_reject_mismatched_final_event_with_interim_segment PASSED [ 62%]
tests/test_schemas.py::TestTranscriptEventSchema::test_valid_error_event PASSED [ 64%]
tests/test_schemas.py::TestTranscriptEventSchema::test_reject_error_event_without_error_detail PASSED [ 65%]
tests/test_schemas.py::TestSTTErrorDetailSchema::test_error_detail_without_request_id PASSED [ 66%]
tests/test_schemas.py::TestSTTErrorDetailSchema::test_error_detail_with_request_id PASSED [ 67%]
tests/test_schemas.py::TestSTTErrorDetailSchema::test_to_api_error_shape PASSED [ 69%]
tests/test_schemas.py::TestSTTErrorDetailSchema::test_to_api_error_without_request_id_keeps_key PASSED [ 70%]
tests/test_schemas.py::TestSTTErrorDetailSchema::test_reject_secrets_in_error_message PASSED [ 71%]
tests/test_schemas.py::TestAudioChunkSchema::test_valid_audio_chunk PASSED [ 72%]
tests/test_schemas.py::TestAudioChunkSchema::test_reject_non_bytes_audio_data PASSED [ 74%]
tests/test_schemas.py::TestAudioChunkSchema::test_reject_negative_sequence_number PASSED [ 75%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_01_valid_final_segment PASSED [ 76%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_02_valid_interim_segment PASSED [ 77%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_03_missing_required_fields PASSED [ 79%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_04_incorrect_field_types PASSED [ 80%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_05_negative_nonfinite_or_reversed_timestamps PASSED [ 81%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_06_invalid_confidence_values PASSED [ 82%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_07_unsupported_event_types PASSED [ 83%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_08_malformed_error_events PASSED [ 85%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_09_chronological_ordering_of_multiple_final_segments PASSED [ 86%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_10_out_of_order_event_arrival PASSED [ 87%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_11_repeated_delivery_of_the_same_event PASSED [ 88%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_12_interim_updates_followed_by_a_final_segment PASSED [ 90%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_13_late_interim_updates_after_finalization PASSED [ 91%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_14_equal_timestamps_and_overlapping_segments PASSED [ 92%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_15_empty_transcript_and_reset_behavior PASSED [ 93%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_16_deterministic_repeated_mock_runs PASSED [ 95%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_17_simulated_adapter_failure PASSED [ 96%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_18_recovery_after_failed_run PASSED [ 97%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_19_consistency_between_final_transcript_and_committed_segments PASSED [ 98%]
tests/test_twenty_requirements.py::TestTwentyWeek1Requirements::test_20_correct_telemetry_calculations PASSED [100%]

============================= 81 passed in 0.23s ==============================
```

---

## 5. Reviewer Reproduction Steps

1. **Verify Test Suite (81 passed):**
   ```bash
   python -m pytest -v
   ```
2. **Execute Full Fixture Demonstrations (Fixtures A through F):**
   ```bash
   python demo/live_demo.py --all
   ```
3. **Verify Bit-for-Bit Determinism:**
   ```bash
   python demo/live_demo.py --fixture A
   ```
   Confirm that the `DETERMINISM AUDIT (Pass 1 vs Pass 2 bit-for-bit check)` displays `PASSED (100% Deterministic)`.
4. **Inspect Optional Localhost Dashboard:**
   ```bash
   python demo/server.py
   ```
   Open `http://localhost:8000` in a browser. Select different personas, test replay, and click **Repeatability Audit**.

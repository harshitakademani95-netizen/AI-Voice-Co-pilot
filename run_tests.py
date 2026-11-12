"""
Standalone Test Runner for Workstream W3: Context & Reasoning
Student: Amruta A J | Team: SDE 3

Runs unit tests with clean sys.path resolution and optional --w3-only isolation.
"""

from pathlib import Path
import sys
import time
import unittest

# Setup sys.path with project root and src/ without duplicates
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

for path_entry in (SRC_DIR, PROJECT_ROOT):
    p_str = str(path_entry)
    if p_str in sys.path:
        sys.path.remove(p_str)
    sys.path.insert(0, p_str)

W3_TEST_FILES = [
    "test_context_schemas.py",
    "test_synthetic.py",
    "test_mock_reasoning.py",
    "test_prompts.py",
    "test_capture_adapter.py",
    "test_bounded_builder.py",
    "test_llm_client.py",
    "test_llm_malformed_output.py",
    "test_demo_week2.py",
]


def run_tests():
    w3_only = "--w3-only" in sys.argv

    print("=" * 70)
    if w3_only:
        print("WORKSTREAM W3: CONTEXT & REASONING - DEDICATED ACCEPTANCE RUNNER")
    else:
        print("WORKSTREAM W3: CONTEXT & REASONING - FULL PROJECT TEST RUNNER (includes other workstreams' tests)")
    print("Student: Amruta A J | Team: SDE 3")
    print("=" * 70)

    loader = unittest.TestLoader()
    tests_dir = str(PROJECT_ROOT / "tests")

    if w3_only:
        tests_path = Path(tests_dir)
        missing_files = [f for f in W3_TEST_FILES if not (tests_path / f).is_file()]
        if missing_files:
            print("ERROR: Missing required W3 test file(s) in tests/:")
            for mf in missing_files:
                print(f"  - {mf}")
            return 1

        suite = unittest.TestSuite()
        for test_file in W3_TEST_FILES:
            mod_suite = loader.discover(start_dir=tests_dir, pattern=test_file)
            suite.addTests(mod_suite)
    else:
        suite = loader.discover(start_dir=tests_dir, pattern="test_*.py")

    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("\n" + "=" * 70)
    print(f"SUMMARY: Ran {result.testsRun} tests in {elapsed:.3f}s")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("Status: " + ("ALL TESTS PASSED [OK]" if result.wasSuccessful() else "TESTS FAILED [FAILED]"))
    print("=" * 70)

    if not w3_only:
        print("Note: Errors from non-W3 modules are not W3 failures; use --w3-only for W3 evidence.")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())

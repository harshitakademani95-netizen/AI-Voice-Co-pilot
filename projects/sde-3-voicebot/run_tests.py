"""
Standalone Test Runner for Workstream W3: Context & Reasoning
Student: Amruta A J | Team: SDE 3

Runs all unit tests in the tests/ directory and prints a clear, structured report.
"""

import sys
import time
import unittest


def run_all_tests():
    print("=" * 70)
    print("WORKSTREAM W3: CONTEXT & REASONING - UNIT TEST RUNNER")
    print("Student: Amruta A J | Team: SDE 3")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir="tests", pattern="test_*.py")

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

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())

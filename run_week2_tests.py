"""Test runner for Week 2 Backend Session Service tests."""
import os
import sys
import pytest

if __name__ == "__main__":
    # Ensure current directory is in PYTHONPATH
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    
    args = [
        "-v",
        "tests/test_health.py",
        "tests/test_middleware.py",
        "tests/test_errors.py",
        "tests/test_sessions.py",
        "tests/test_sessions_week2.py",
    ]
    sys.exit(pytest.main(args))


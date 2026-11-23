"""One-command mock-mode launcher entrypoint for AI Voice Co-Pilot Backend.

Usage:
    python run_mock.py
"""
import os
import sys

# Ensure src directory is in sys.path for direct module discovery across all workstreams
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from src.launcher import main

if __name__ == "__main__":
    main()

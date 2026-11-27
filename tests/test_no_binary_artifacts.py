"""
Workstream W3: Context & Reasoning — Repo Hygiene
Binary Artifact Guard

Author: Amruta A J (Team SDE 3)
Module: tests.test_no_binary_artifacts
Description:
    Walks the project tree and fails if any binary image, audio, or video file
    exists outside the explicit allowlist. Prevents accidental commits of
    screenshots, recordings, or personal media.
"""

import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Binary extensions to flag
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tiff",
    ".mp4", ".mov", ".webm", ".avi", ".mkv",
    ".mp3", ".wav", ".m4a", ".ogg", ".flac",
    ".pdf",
}

# Directories to skip entirely (virtual envs, caches, IDE dirs)
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "ENV", "node_modules",
    "__pycache__", ".tox", ".nox", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".pyrefly", "dist", "build", ".idea", ".vscode",
    "htmlcov",
}

# Explicit allowlist: paths (relative to PROJECT_ROOT) where binary files are permitted.
# Add entries here for intentional assets (e.g., src/assets/logo.png).
ALLOWLIST: set = set()


class TestNoBinaryArtifacts(unittest.TestCase):
    """Fail if binary image/audio/video files are found outside the allowlist."""

    def test_no_binary_artifacts_in_repo(self):
        """
        Walk the project tree; collect any binary artifact files outside the allowlist.
        Fail with a list of offending paths if any are found.
        """
        offenders = []

        for path in PROJECT_ROOT.rglob("*"):
            # Skip directories
            if not path.is_file():
                continue

            # Skip if any parent directory is in SKIP_DIRS
            if any(part in SKIP_DIRS for part in path.parts):
                continue

            if path.suffix.lower() not in BINARY_EXTENSIONS:
                continue

            # Check allowlist (relative to project root)
            try:
                rel = path.relative_to(PROJECT_ROOT)
            except ValueError:
                continue

            if str(rel) in ALLOWLIST or rel in ALLOWLIST:
                continue

            offenders.append(str(rel))

        if offenders:
            self.fail(
                f"Binary artifact(s) found in repo (outside allowlist):\n"
                + "\n".join(f"  {p}" for p in sorted(offenders))
                + "\n\nAdd intentional assets to the ALLOWLIST in tests/test_no_binary_artifacts.py."
            )


if __name__ == "__main__":
    unittest.main()


"""Smoke test for scripts/check_docs.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_check_docs_passes_clean_against_seed():
    """The framework's own CLAUDE.md files must pass the health check."""
    result = subprocess.run(
        [sys.executable, "scripts/check_docs.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_docs.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout

"""Smoke tests for the packaged CLI entry point (no agent execution)."""

import subprocess
import sys


def test_bytebuddhi_help_version_and_run_help() -> None:
    for args in (["--help"], ["--version"], ["run", "--help"]):
        completed = subprocess.run(
            [sys.executable, "-m", "app.interfaces.cli.main", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout or completed.stderr

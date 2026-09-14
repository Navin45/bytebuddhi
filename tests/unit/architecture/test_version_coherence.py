"""Released components share one version string."""

import json
import re
from pathlib import Path

from app import __version__


def test_python_api_cli_and_extension_versions_match() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert match is not None
    package = json.loads(Path("vscode-extension/package.json").read_text(encoding="utf-8"))
    assert match.group(1) == __version__ == package["version"]

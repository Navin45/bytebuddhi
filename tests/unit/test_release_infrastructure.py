"""Unit tests for release scripts: sync_version, release_manifest, checksums, and SBOM."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app._version import APP_VERSION, PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parent.parent.parent


def test_sync_version_verify_current():
    """Verify that current repository files are in sync with APP_VERSION."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--verify-only"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"sync_version --verify-only failed: {res.stderr}"
    assert "All version fields match" in res.stdout


def test_sync_version_check_tag_matching():
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check-tag", f"v{APP_VERSION}"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"check-tag failed: {res.stderr}"
    assert "All version fields match" in res.stdout


def test_sync_version_check_tag_mismatch():
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py"), "--check-tag", "v99.99.99"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "MISMATCH" in res.stderr or "RELEASE BLOCKED" in res.stderr


def test_generate_checksums(tmp_path: Path):
    d = tmp_path / "artifacts"
    d.mkdir()
    f1 = d / "artifact1.txt"
    f1.write_bytes(b"hello world")
    f2 = d / "artifact2.whl"
    f2.write_bytes(b"package content")

    out_file = tmp_path / "SHA256SUMS"
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_checksums.py"), str(d), "--output", str(out_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) == 2
    assert "artifact1.txt" in content
    assert "artifact2.whl" in content


def test_release_manifest_generation(tmp_path: Path):
    out_file = tmp_path / "release.json"
    res = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "release_manifest.py"),
            "--version",
            APP_VERSION,
            "--commit",
            "abc1234567890",
            "--protocol-version",
            str(PROTOCOL_VERSION),
            "--artifact",
            f"python_wheel:bytebuddhi-{APP_VERSION}-py3-none-any.whl:0123456789abcdef:https://github.com/Navin45/bytebuddhi/releases/download/v{APP_VERSION}/bytebuddhi-{APP_VERSION}-py3-none-any.whl",
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["version"] == APP_VERSION
    assert data["git_commit"] == "abc1234567890"
    assert data["protocol_version"] == PROTOCOL_VERSION
    assert len(data["artifacts"]) == 1
    art = data["artifacts"][0]
    assert art["type"] == "python_wheel"
    assert art["sha256"] == "0123456789abcdef"


def test_generate_sbom(tmp_path: Path):
    out_file = tmp_path / "sbom.cdx.json"
    res = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_sbom.py"),
            "--version",
            APP_VERSION,
            "--output",
            str(out_file),
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["bomFormat"] == "CycloneDX"
    assert data["specVersion"] == "1.5"
    assert data["metadata"]["component"]["version"] == APP_VERSION
    assert len(data["components"]) > 0
    groups = {c.get("group") for c in data["components"]}
    assert "pypi" in groups

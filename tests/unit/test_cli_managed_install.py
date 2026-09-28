"""Unit tests for managed CLI installation layout, verification, and rollback."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.interfaces.cli.managed_install import (
    ManagedLayout,
    compare_versions,
    download_and_verify,
    fetch_release_info,
    release_info_from_manifest,
    rollback,
    smoke_test,
    uninstall,
    write_launcher,
)


@pytest.fixture
def layout(tmp_path: Path) -> ManagedLayout:
    layout_obj = ManagedLayout(root=tmp_path / ".bytebuddhi")
    layout_obj.ensure_dirs()
    return layout_obj


def test_layout_directory_structure(layout: ManagedLayout) -> None:
    assert layout.installs_dir.is_dir()
    assert layout.bin_dir.is_dir()
    assert layout.state_dir.is_dir()
    assert layout.logs_dir.is_dir()
    assert layout.cache_dir.is_dir()
    assert layout.active_version() is None


def test_version_activation_and_installed_versions(layout: ManagedLayout) -> None:
    (layout.installs_dir / "0.1.2").mkdir()
    (layout.installs_dir / "0.1.3").mkdir()
    (layout.installs_dir / "0.1.4").mkdir()

    assert layout.installed_versions() == ["0.1.2", "0.1.3", "0.1.4"]

    layout.activate("0.1.3")
    assert layout.active_version() == "0.1.3"
    assert layout.previous_version() == "0.1.2"

    layout.activate("0.1.4")
    assert layout.active_version() == "0.1.4"
    assert layout.previous_version() == "0.1.3"


def test_compare_versions() -> None:
    assert compare_versions("0.1.3", "0.1.4") == -1
    assert compare_versions("0.1.4", "0.1.3") == 1
    assert compare_versions("0.1.3", "0.1.3") == 0
    assert compare_versions("0.2.0", "0.1.99") == 1
    assert compare_versions("1.0.0", "0.9.9") == 1
    assert compare_versions("0.1.4-rc.1", "0.1.4") == -1
    assert compare_versions("0.1.3", "0.1.4-rc.1") == -1
    assert compare_versions("0.1.4-rc.2", "0.1.4-rc.10") == -1


def test_download_and_verify_success(tmp_path: Path) -> None:
    content = b"fake-wheel-payload"
    expected_sha = hashlib.sha256(content).hexdigest()
    dest = tmp_path / "test.whl"

    mock_resp = MagicMock()
    mock_resp.read.side_effect = [content, b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch("app.interfaces.cli.managed_install.urlopen", return_value=mock_resp):
        download_and_verify("https://example.com/test.whl", expected_sha, dest)

    assert dest.exists()
    assert dest.read_bytes() == content


def test_download_and_verify_checksum_mismatch(tmp_path: Path) -> None:
    content = b"fake-wheel-payload"
    dest = tmp_path / "test.whl"

    mock_resp = MagicMock()
    mock_resp.read.side_effect = [content, b""]
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch("app.interfaces.cli.managed_install.urlopen", return_value=mock_resp),
        pytest.raises(RuntimeError, match="SHA-256 mismatch"),
    ):
        download_and_verify(
            "https://example.com/test.whl",
            "badhash0000000000000000000000000000000000000000000000000000000000",
            dest,
        )

    # Partial file should be cleaned up and dest should not exist
    assert not dest.exists()
    assert not dest.with_suffix(".partial").exists()


def test_smoke_test_missing_executable(layout: ManagedLayout) -> None:
    (layout.installs_dir / "0.1.4").mkdir()
    assert smoke_test(layout, "0.1.4") is False


def test_smoke_test_successful(layout: ManagedLayout) -> None:
    v_dir = layout.installs_dir / "0.1.4"
    if sys.platform == "win32":
        scripts = v_dir / "Scripts"
        scripts.mkdir(parents=True)
        exe = scripts / "bytebuddhi.exe"
    else:
        bin_d = v_dir / "bin"
        bin_d.mkdir(parents=True)
        exe = bin_d / "bytebuddhi"
    exe.write_text("stub", encoding="utf-8")

    mock_run = MagicMock(returncode=0, stdout="bytebuddhi 0.1.4\n")
    with patch("subprocess.run", return_value=mock_run):
        assert smoke_test(layout, "0.1.4") is True


def test_rollback_to_previous_version(layout: ManagedLayout) -> None:
    (layout.installs_dir / "0.1.3").mkdir()
    (layout.installs_dir / "0.1.4").mkdir()

    layout.activate("0.1.4")
    assert layout.active_version() == "0.1.4"

    prev = rollback(layout)
    assert prev == "0.1.3"
    assert layout.active_version() == "0.1.3"

    # Rolling back again when there is no prior version returns None
    prev2 = rollback(layout)
    assert prev2 is None
    assert layout.active_version() == "0.1.3"


def test_uninstall_keeps_state_unless_purged(layout: ManagedLayout) -> None:
    (layout.installs_dir / "0.1.4").mkdir()
    layout.activate("0.1.4")
    write_launcher(layout)
    (layout.state_dir / "auth.json").write_text("secret", encoding="utf-8")

    # Regular uninstall
    removed = uninstall(layout, purge=False)
    assert not layout.installs_dir.exists()
    assert not layout.bin_dir.exists()
    assert not layout.current_file.exists()
    # State preserved
    assert (layout.state_dir / "auth.json").exists()
    assert str(layout.state_dir) not in removed

    # Purge uninstall
    removed_purged = uninstall(layout, purge=True)
    assert not layout.state_dir.exists()
    assert not layout.root.exists()
    assert any("state" in p for p in removed_purged)


def test_write_launcher(layout: ManagedLayout) -> None:
    launcher = write_launcher(layout)
    assert launcher.exists()
    if sys.platform == "win32":
        assert launcher.name == "bytebuddhi.cmd"
    else:
        assert launcher.name == "bytebuddhi"
        assert launcher.stat().st_mode & 0o111


_WHEEL_SHA = "ab" * 32


def _manifest(version: str, channel: str) -> dict[str, object]:
    return {
        "version": version,
        "channel": channel,
        "protocol_version": 1,
        "release_date": "2026-09-28",
        "artifacts": [
            {
                "type": "python_wheel",
                "url": f"https://example.com/bytebuddhi-{version}.whl",
                "sha256": _WHEEL_SHA,
            }
        ],
    }


def test_release_manifest_rejects_malformed_documents() -> None:
    with pytest.raises(RuntimeError, match="missing version"):
        release_info_from_manifest({"channel": "stable"}, channel="stable")
    with pytest.raises(RuntimeError, match="checksum"):
        release_info_from_manifest(
            {
                "version": "0.1.4",
                "channel": "stable",
                "artifacts": [{"type": "python_wheel", "url": "https://example.com/a.whl", "sha256": "abc"}],
            },
            channel="stable",
        )


def test_stable_channel_rejects_prerelease_manifest() -> None:
    with pytest.raises(RuntimeError, match="prerelease"):
        release_info_from_manifest(_manifest("0.1.4-rc.1", "beta"), channel="stable")


def test_beta_channel_accepts_release_candidate() -> None:
    info = release_info_from_manifest(_manifest("0.1.4-rc.1", "beta"), channel="beta")
    assert info.version == "0.1.4-rc.1"
    assert info.channel == "beta"


def test_fetch_stable_reads_latest_release_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_read(url: str) -> object:
        calls.append(url)
        return _manifest("0.1.4", "stable")

    monkeypatch.setattr("app.interfaces.cli.managed_install._read_json", fake_read)
    info = fetch_release_info("stable")
    assert info.version == "0.1.4"
    assert calls == ["https://github.com/Navin45/bytebuddhi/releases/latest/download/release.json"]


def test_fetch_beta_reads_newest_published_release(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_read(url: str) -> object:
        calls.append(url)
        if "api.github.com" in url:
            return [
                {
                    "draft": False,
                    "assets": [
                        {
                            "name": "release.json",
                            "browser_download_url": "https://example.com/release.json",
                        }
                    ],
                }
            ]
        return _manifest("0.1.4-rc.1", "beta")

    monkeypatch.setattr("app.interfaces.cli.managed_install._read_json", fake_read)
    info = fetch_release_info("beta")
    assert info.version == "0.1.4-rc.1"
    assert "api.github.com" in calls[0]
    assert calls[1] == "https://example.com/release.json"

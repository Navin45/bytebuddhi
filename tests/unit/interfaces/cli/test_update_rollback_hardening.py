"""Comprehensive hardening tests for CLI update, failure containment, and rollback."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.interfaces.cli.credentials import CredentialStore, StoredCredentials
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.managed_install import (
    ManagedLayout,
    ReleaseInfo,
    download_and_verify,
)
from app.interfaces.cli.update import handle_update


@pytest.fixture
def managed_env(tmp_path: Path):
    root = tmp_path / "bytebuddhi_home"
    layout = ManagedLayout(root=root)
    layout.ensure_dirs()
    (layout.installs_dir / "0.1.3").mkdir(parents=True)
    layout.activate("0.1.3")

    with patch("app.interfaces.cli.managed_install.default_layout", return_value=layout):
        yield layout


def test_installed_upgrade_preserves_state_and_config(managed_env: ManagedLayout):
    """An upgrade from 0.1.3 to 0.1.4-rc.1 preserves config, credentials, and logs."""
    # 1. Populate state (config and credentials) in shared state directory
    cfg_file = managed_env.state_dir / "config.json"
    cfg_file.write_text(
        json.dumps({"gateway_url": "http://127.0.0.1:8765", "theme": "dark", "channel": "beta"}),
        encoding="utf-8",
    )

    store = CredentialStore(managed_env.state_dir)
    from uuid import uuid4

    uid = uuid4()
    store.save(StoredCredentials(user_id=uid, access_token="access-123", refresh_token="refresh-123"))

    # Log in logs directory
    managed_env.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = managed_env.logs_dir / "gateway.log"
    log_file.write_text("existing log line\n", encoding="utf-8")

    # 2. Perform upgrade to 0.1.4-rc.1
    fake_release = ReleaseInfo(
        version="0.1.4-rc.1",
        python_wheel_url="https://example.com/bytebuddhi-0.1.4rc1-py3-none-any.whl",
        python_wheel_sha256="fake_sha256",
        release_date="2026-09-28",
        channel="beta",
    )

    stdout = io.StringIO()
    stderr = io.StringIO()

    with (
        patch("app.interfaces.cli.update.APP_VERSION", "0.1.3"),
        patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release),
        patch("app.interfaces.cli.managed_install.download_and_verify"),
        patch("app.interfaces.cli.managed_install.install_wheel"),
        patch("app.interfaces.cli.managed_install.smoke_test", return_value=True),
        patch("app.interfaces.cli.managed_install.write_launcher"),
    ):
        code = handle_update(stdout=stdout, stderr=stderr, channel="beta")

    assert code == int(ExitCode.SUCCESS)
    assert managed_env.active_version() == "0.1.4-rc.1"
    assert managed_env.previous_version() == "0.1.3"

    # 3. Assert config, credentials, and logs are 100% preserved
    cfg_after = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert cfg_after["gateway_url"] == "http://127.0.0.1:8765"
    assert cfg_after["theme"] == "dark"

    creds_after = store.load()
    assert creds_after is not None
    assert creds_after.user_id == uid
    assert creds_after.access_token == "access-123"

    assert "existing log line" in log_file.read_text(encoding="utf-8")


def test_corrupted_checksum_fails_closed_and_keeps_previous_version(managed_env: ManagedLayout):
    """If downloaded artifact checksum mismatches, update fails and previous version remains active."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    fake_release = ReleaseInfo(
        version="0.1.4-rc.1",
        python_wheel_url="https://example.com/bytebuddhi-0.1.4rc1-py3-none-any.whl",
        python_wheel_sha256="expected_sha256_hash",
        release_date="2026-09-28",
        channel="beta",
    )

    def failing_download(url: str, expected_sha: str, dest: Path):
        raise RuntimeError("SHA-256 mismatch: expected expected_sha256_hash, got corrupted_hash")

    with (
        patch("app.interfaces.cli.update.APP_VERSION", "0.1.3"),
        patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release),
        patch("app.interfaces.cli.managed_install.download_and_verify", side_effect=failing_download),
    ):
        code = handle_update(stdout=stdout, stderr=stderr, channel="beta")

    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert "Download failed" in stderr.getvalue()
    # Invariant: Previous known-good version remains active and untouched
    assert managed_env.active_version() == "0.1.3"


def test_startup_smoke_test_failure_triggers_automatic_rollback(managed_env: ManagedLayout):
    """When smoke test fails after installing a release, update aborts and rolls back to known-good version."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    fake_release = ReleaseInfo(
        version="0.1.4-rc.1",
        python_wheel_url="https://example.com/bytebuddhi-0.1.4rc1-py3-none-any.whl",
        python_wheel_sha256="fakehash",
        release_date="2026-09-28",
        channel="beta",
    )

    with (
        patch("app.interfaces.cli.update.APP_VERSION", "0.1.3"),
        patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release),
        patch("app.interfaces.cli.managed_install.download_and_verify"),
        patch("app.interfaces.cli.managed_install.install_wheel"),
        patch("app.interfaces.cli.managed_install.smoke_test", return_value=False),  # Startup failure
    ):
        code = handle_update(stdout=stdout, stderr=stderr, channel="beta")

    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert "Smoke test failed — rolling back" in stderr.getvalue()
    # Active version is restored to known-good version
    assert managed_env.active_version() == "0.1.3"


def test_manual_rollback_to_known_good_preserves_state(managed_env: ManagedLayout):
    """Manual bytebuddhi update --rollback activates previous version and preserves state."""
    # Setup 0.1.4-rc.1 as active, with 0.1.3 as previous
    (managed_env.installs_dir / "0.1.4-rc.1").mkdir(parents=True)
    managed_env.activate("0.1.4-rc.1")

    assert managed_env.active_version() == "0.1.4-rc.1"
    assert managed_env.previous_version() == "0.1.3"

    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_update(do_rollback=True, stdout=stdout, stderr=stderr)
    assert code == int(ExitCode.SUCCESS)
    assert "Rolled back to ByteBuddhi 0.1.3" in stdout.getvalue()
    assert managed_env.active_version() == "0.1.3"


def test_download_and_verify_atomic_on_failure(tmp_path: Path):
    """download_and_verify removes temporary partial file and never creates dest on hash mismatch."""

    dest = tmp_path / "target.whl"
    fake_content = b"corrupted file content"

    class FakeResponse:
        def __init__(self, data: bytes):
            self._data = data
            self._read = False

        def read(self, _size=65536):
            if self._read:
                return b""
            self._read = True
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with (
        patch("app.interfaces.cli.managed_install.urlopen", return_value=FakeResponse(fake_content)),
        pytest.raises(RuntimeError, match="SHA-256 mismatch"),
    ):
        download_and_verify("https://example.com/file.whl", "expected_correct_hash", dest)

    assert not dest.exists()
    assert not dest.with_suffix(".partial").exists()

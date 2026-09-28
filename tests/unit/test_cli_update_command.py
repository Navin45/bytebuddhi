"""Unit tests for bytebuddhi update and uninstall CLI commands."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app._version import APP_VERSION
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.managed_install import ManagedLayout, ReleaseInfo
from app.interfaces.cli.uninstall import handle_uninstall
from app.interfaces.cli.update import handle_update


@pytest.fixture
def managed_env(tmp_path: Path):
    root = tmp_path / "bytebuddhi_home"
    layout = ManagedLayout(root=root)
    layout.ensure_dirs()
    (layout.installs_dir / "0.1.3").mkdir()
    layout.activate("0.1.3")

    with patch("app.interfaces.cli.managed_install.default_layout", return_value=layout):
        yield layout


def test_update_check_up_to_date(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    fake_release = ReleaseInfo(
        version=APP_VERSION,
        python_wheel_url="https://example.com/wheel.whl",
        python_wheel_sha256="abc",
        release_date="2026-09-28",
    )

    with patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release):
        code = handle_update(check_only=True, stdout=stdout, stderr=stderr)

    assert code == int(ExitCode.SUCCESS)
    assert "up to date" in stdout.getvalue()


def test_update_check_available_json(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    fake_release = ReleaseInfo(
        version="9.9.9",
        python_wheel_url="https://example.com/wheel.whl",
        python_wheel_sha256="abc",
        release_date="2026-09-28",
    )

    with patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release):
        code = handle_update(check_only=True, json_mode=True, stdout=stdout, stderr=stderr)

    assert code == int(ExitCode.SUCCESS)
    data = json.loads(stdout.getvalue())
    assert data["update_available"] is True
    assert data["latest_version"] == "9.9.9"
    assert data["current_version"] == APP_VERSION


def test_update_rollback_success(managed_env: ManagedLayout) -> None:
    (managed_env.installs_dir / "0.1.2").mkdir()
    managed_env.activate("0.1.3")

    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_update(do_rollback=True, stdout=stdout, stderr=stderr)
    assert code == int(ExitCode.SUCCESS)
    assert "Rolled back to ByteBuddhi 0.1.2" in stdout.getvalue()
    assert managed_env.active_version() == "0.1.2"


def test_update_rollback_no_previous_version(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_update(do_rollback=True, stdout=stdout, stderr=stderr)
    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert "No previous version available" in stderr.getvalue()
    assert managed_env.active_version() == "0.1.3"


def test_full_update_success(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    fake_release = ReleaseInfo(
        version="0.2.0",
        python_wheel_url="https://example.com/bytebuddhi-0.2.0-py3-none-any.whl",
        python_wheel_sha256="fakehash",
        release_date="2026-09-28",
    )

    with (
        patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release),
        patch("app.interfaces.cli.managed_install.download_and_verify") as mock_dl,
        patch("app.interfaces.cli.managed_install.install_wheel") as mock_inst,
        patch("app.interfaces.cli.managed_install.smoke_test", return_value=True),
        patch("app.interfaces.cli.managed_install.write_launcher"),
    ):
        code = handle_update(stdout=stdout, stderr=stderr)

    assert code == int(ExitCode.SUCCESS)
    mock_dl.assert_called_once()
    mock_inst.assert_called_once()
    assert managed_env.active_version() == "0.2.0"
    assert "ByteBuddhi 0.2.0 is ready" in stderr.getvalue()


def test_update_fails_smoke_test_and_rolls_back(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    fake_release = ReleaseInfo(
        version="0.2.0",
        python_wheel_url="https://example.com/bytebuddhi-0.2.0-py3-none-any.whl",
        python_wheel_sha256="fakehash",
        release_date="2026-09-28",
    )

    with (
        patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release),
        patch("app.interfaces.cli.managed_install.download_and_verify"),
        patch("app.interfaces.cli.managed_install.install_wheel"),
        patch("app.interfaces.cli.managed_install.smoke_test", return_value=False),
        patch("app.interfaces.cli.managed_install.rollback") as mock_rb,
    ):
        code = handle_update(stdout=stdout, stderr=stderr)

    assert code == int(ExitCode.EXECUTION_FAILURE)
    assert "Smoke test failed — rolling back" in stderr.getvalue()
    mock_rb.assert_called_once()
    # Active version should not be the broken one
    assert managed_env.active_version() == "0.1.3"


def test_stable_channel_does_not_install_release_candidate(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    fake_release = ReleaseInfo(
        version="0.1.4-rc.1",
        python_wheel_url="https://example.com/bytebuddhi-0.1.4-rc.1.whl",
        python_wheel_sha256="ab" * 32,
        release_date="2026-09-28",
        channel="beta",
    )

    with (
        patch("app.interfaces.cli.update.APP_VERSION", "0.1.3"),
        patch("app.interfaces.cli.managed_install.fetch_release_info", return_value=fake_release),
        patch("app.interfaces.cli.managed_install.download_and_verify") as mock_dl,
    ):
        code = handle_update(stdout=stdout, stderr=stderr, channel="stable")

    assert code == int(ExitCode.SUCCESS)
    mock_dl.assert_not_called()
    assert managed_env.active_version() == "0.1.3"
    assert "up to date" in stdout.getvalue()


def test_uninstall_command(managed_env: ManagedLayout) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = handle_uninstall(purge=False, json_mode=True, stdout=stdout, stderr=stderr)
    assert code == int(ExitCode.SUCCESS)
    data = json.loads(stdout.getvalue())
    assert data["status"] == "removed"
    assert data["purge"] is False

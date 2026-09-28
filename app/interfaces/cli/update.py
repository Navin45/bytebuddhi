"""``bytebuddhi update`` — self-update and rollback for managed CLI installs."""

from __future__ import annotations

import sys
from typing import TextIO

from app._version import APP_VERSION
from app.interfaces.cli.exit_codes import ExitCode


def handle_update(
    *,
    check_only: bool = False,
    do_rollback: bool = False,
    channel: str = "stable",
    json_mode: bool = False,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Execute the update / --check / --rollback command."""
    from app.interfaces.cli.managed_install import (
        compare_versions,
        default_layout,
        download_and_verify,
        fetch_release_info,
        install_wheel,
        release_is_eligible,
        rollback,
        smoke_test,
        write_launcher,
    )
    from app.interfaces.cli.render import write_json

    layout = default_layout()
    layout.ensure_dirs()

    # ── Rollback ──────────────────────────────────────────────────
    if do_rollback:
        prev = rollback(layout)
        if prev is None:
            stderr.write("No previous version available for rollback.\n")
            return int(ExitCode.EXECUTION_FAILURE)
        if json_mode:
            write_json({"action": "rollback", "version": prev}, stream=stdout)
        else:
            stdout.write(f"Rolled back to ByteBuddhi {prev}.\n")
        return int(ExitCode.SUCCESS)

    # ── Fetch latest release info ─────────────────────────────────
    try:
        release = fetch_release_info(channel=channel)
    except Exception as exc:
        stderr.write(f"Failed to check for updates: {exc}\n")
        return int(ExitCode.EXECUTION_FAILURE)

    current = APP_VERSION
    if not release_is_eligible(channel, release):
        if json_mode:
            write_json(
                {
                    "current_version": current,
                    "latest_version": current,
                    "update_available": False,
                    "channel": channel,
                },
                stream=stdout,
            )
        else:
            stdout.write(f"ByteBuddhi {current} is up to date.\n")
        return int(ExitCode.SUCCESS)

    cmp = compare_versions(current, release.version)

    if check_only:
        info = {
            "current_version": current,
            "latest_version": release.version,
            "update_available": cmp < 0,
            "channel": release.channel,
            "release_date": release.release_date,
        }
        if json_mode:
            write_json(info, stream=stdout)
        else:
            if cmp < 0:
                stdout.write(f"Update available: {current} → {release.version}  (released {release.release_date})\n")
            else:
                stdout.write(f"ByteBuddhi {current} is up to date.\n")
        return int(ExitCode.SUCCESS)

    if cmp >= 0:
        if json_mode:
            write_json({"action": "update", "status": "up_to_date", "version": current}, stream=stdout)
        else:
            stdout.write(f"ByteBuddhi {current} is up to date.\n")
        return int(ExitCode.SUCCESS)

    # ── Download ──────────────────────────────────────────────────
    stderr.write(f"Updating ByteBuddhi {current} → {release.version} …\n")

    wheel_name = release.python_wheel_url.rsplit("/", 1)[-1]
    wheel_path = layout.cache_dir / wheel_name
    try:
        stderr.write("  ↓ Downloading release …\n")
        download_and_verify(
            release.python_wheel_url,
            release.python_wheel_sha256,
            wheel_path,
        )
        stderr.write("  ✓ Verified SHA-256\n")
    except Exception as exc:
        stderr.write(f"  ✗ Download failed: {exc}\n")
        return int(ExitCode.EXECUTION_FAILURE)

    # ── Install into versioned directory ──────────────────────────
    try:
        stderr.write("  ↓ Installing …\n")
        install_wheel(layout, release.version, wheel_path)
        stderr.write("  ✓ Installed\n")
    except Exception as exc:
        stderr.write(f"  ✗ Installation failed: {exc}\n")
        return int(ExitCode.EXECUTION_FAILURE)

    # ── Smoke test ────────────────────────────────────────────────
    if not smoke_test(layout, release.version):
        stderr.write("  ✗ Smoke test failed — rolling back.\n")
        rollback(layout)
        return int(ExitCode.EXECUTION_FAILURE)
    stderr.write("  ✓ Smoke test passed\n")

    # ── Activate ──────────────────────────────────────────────────
    layout.activate(release.version)
    write_launcher(layout)
    stderr.write(f"  ✓ Activated {release.version}\n")

    stderr.write(f"\nByteBuddhi {release.version} is ready.\n")
    if json_mode:
        write_json(
            {"action": "update", "status": "updated", "from": current, "to": release.version},
            stream=stdout,
        )
    return int(ExitCode.SUCCESS)

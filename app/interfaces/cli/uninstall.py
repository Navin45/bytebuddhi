"""``bytebuddhi uninstall`` — remove managed CLI installation."""

from __future__ import annotations

import sys
from typing import TextIO

from app.interfaces.cli.exit_codes import ExitCode


def handle_uninstall(
    *,
    purge: bool = False,
    json_mode: bool = False,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Remove managed CLI installation.

    Without ``--purge``, keeps user config and credentials.
    With ``--purge``, removes everything.
    """
    from app.interfaces.cli.managed_install import default_layout, uninstall
    from app.interfaces.cli.render import write_json

    layout = default_layout()

    if not layout.root.exists():
        if json_mode:
            write_json({"action": "uninstall", "status": "not_installed"}, stream=stdout)
        else:
            stderr.write("ByteBuddhi is not installed in a managed directory.\n")
        return int(ExitCode.SUCCESS)

    removed = uninstall(layout, purge=purge)

    bin_dir = layout.bin_dir
    if json_mode:
        write_json(
            {
                "action": "uninstall",
                "status": "removed",
                "purge": purge,
                "removed_paths": removed,
                "manual_cleanup": f"Remove {bin_dir} from your PATH if it was added.",
            },
            stream=stdout,
        )
    else:
        stdout.write("ByteBuddhi has been uninstalled.\n")
        if not purge:
            stdout.write(f"  Config/credentials kept in {layout.state_dir}\n")
            stdout.write("  Use --purge to remove everything.\n")
        stdout.write(f"\n  You may need to remove {bin_dir} from your PATH.\n")

    return int(ExitCode.SUCCESS)

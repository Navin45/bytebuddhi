"""CLI commands for profile selection and standalone data maintenance."""

from __future__ import annotations

import asyncio
import os
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from app.infrastructure.config.local_config import load_local_config, save_local_config
from app.infrastructure.config.profile import apply_process_profile, describe_profile, sqlite_database_path
from app.infrastructure.persistence.sqlite.database import integrity_report
from app.infrastructure.persistence.sqlite.maintenance import (
    StandaloneDataError,
    export_backup,
    migrate_postgres_to_sqlite,
)
from app.interfaces.cli.exit_codes import ExitCode
from app.interfaces.cli.render import write_json
from app.interfaces.gateway.config import config_dir


def handle_profile(args: Namespace, *, json_mode: bool, stdout: TextIO) -> int:
    action = getattr(args, "profile_action", None) or "show"
    if action == "set":
        config = load_local_config()
        config.profile = args.name
        save_local_config(config)
        os.environ["BYTEBUDDHI_PROFILE"] = args.name
    selected = apply_process_profile(getattr(args, "profile", None))
    payload = describe_profile()
    payload["active"] = selected
    payload["persisted"] = load_local_config().profile or ""
    payload["integrity"] = integrity_report(sqlite_database_path()) if selected == "standalone" else ""
    if json_mode:
        write_json(payload, stream=stdout)
    else:
        stdout.write(f"Profile: {payload['active']}\n")
        stdout.write(f"Storage: {payload['storage']}\n")
        if payload["database_path"]:
            stdout.write(f"Database: {payload['database_path']}\n")
        stdout.write(f"Redis: {payload['redis']}\n")
        stdout.write(f"Execution: {payload['execution_mode']}\n")
        if payload["integrity"]:
            stdout.write(f"Integrity: {payload['integrity']}\n")
            if payload["integrity"] not in {"ok", "not_initialized"}:
                stdout.write("The SQLite database failed integrity_check. It was not deleted.\n")
                stdout.write("Restore from a backup created with `bytebuddhi data backup`.\n")
                return int(ExitCode.EXECUTION_FAILURE)
    return int(ExitCode.SUCCESS)


def handle_data(args: Namespace, *, json_mode: bool, stdout: TextIO, stderr: TextIO) -> int:
    action = getattr(args, "data_action", None)
    try:
        if action == "backup":
            destination = args.path or str(
                config_dir() / "backups" / f"bytebuddhi-{datetime.now(UTC):%Y%m%d%H%M%S}.zip"
            )
            path = export_backup(Path(destination), include_artifacts=bool(args.include_artifacts))
            payload: dict[str, object] = {"action": "backup", "path": str(path)}
        elif action == "migrate":
            if not args.to_standalone:
                stderr.write("Refusing to migrate without --to-standalone.\n")
                return int(ExitCode.USAGE_ERROR)
            source = args.source or os.environ.get("DATABASE_URL")
            if not source:
                stderr.write("Pass --source or set DATABASE_URL. Startup will not migrate automatically.\n")
                return int(ExitCode.USAGE_ERROR)
            counts = asyncio.run(migrate_postgres_to_sqlite(source, sqlite_database_path(), overwrite=bool(args.yes)))
            payload = {"action": "migrate", "counts": counts, "database": str(sqlite_database_path())}
        else:
            stderr.write("Use `bytebuddhi data backup` or `bytebuddhi data migrate --to-standalone`.\n")
            return int(ExitCode.USAGE_ERROR)
    except StandaloneDataError as exc:
        stderr.write(f"{exc}\n")
        return int(ExitCode.EXECUTION_FAILURE)
    if json_mode:
        write_json(payload, stream=stdout)
    else:
        stdout.write(f"{payload}\n")
    return int(ExitCode.SUCCESS)

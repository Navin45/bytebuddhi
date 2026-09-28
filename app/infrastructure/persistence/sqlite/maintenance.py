"""Backup, integrity, and explicit PostgreSQL-to-SQLite copy.

Startup never calls these functions.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from app.infrastructure.config.profile import sqlite_database_path
from app.infrastructure.persistence.sqlite.database import initialize, integrity_report


class StandaloneDataError(RuntimeError):
    """A backup or migration request cannot be completed safely."""


def export_backup(destination: Path, *, include_artifacts: bool = False) -> Path:
    """Zip the SQLite database and non-secret config metadata.

    Credentials are not included. The database is copied before it is archived.
    """
    import zipfile

    from app.infrastructure.config.profile import artifact_directory
    from app.interfaces.gateway.config import config_dir

    database = sqlite_database_path()
    if not database.is_file():
        raise StandaloneDataError(f"No standalone database at {database}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshot = destination.parent / f".{destination.stem}.sqlite"
    source = sqlite3.connect(database)
    target = sqlite3.connect(snapshot)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    config_path = config_dir() / "config.json"
    metadata: dict[str, object] = {}
    if config_path.is_file():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            metadata = {
                key: value
                for key, value in raw.items()
                if "token" not in key.lower() and "password" not in key.lower() and "secret" not in key.lower()
            }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot, arcname="bytebuddhi.db")
        archive.writestr("config_metadata.json", json.dumps(metadata, indent=2))
        archive.writestr(
            "README.txt",
            "Restore by stopping ByteBuddhi and replacing the standalone database with bytebuddhi.db.\n"
            "Credentials are not in this archive.\n",
        )
        if include_artifacts:
            root = artifact_directory()
            if root.is_dir():
                for path in root.rglob("*"):
                    if path.is_file():
                        archive.write(path, arcname=str(Path("artifacts") / path.relative_to(root)))
    snapshot.unlink(missing_ok=True)
    return destination


def copy_sqlite_database(source: Path, destination: Path, *, overwrite: bool) -> dict[str, int]:
    """Copy an existing standalone database. Refuses to replace a database unless confirmed."""
    if not source.is_file():
        raise StandaloneDataError(f"Source database does not exist: {source}")
    if destination.exists() and not overwrite:
        raise StandaloneDataError("Standalone database already exists. Pass --yes to replace it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.resolve() != source.resolve():
        backup = destination.with_suffix(destination.suffix + ".bak")
        shutil.copy2(destination, backup)
    if destination.resolve() != source.resolve():
        src = sqlite3.connect(source)
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    counts = _table_counts(destination)
    report = integrity_report(destination)
    if report != "ok":
        raise StandaloneDataError(f"Copied database failed integrity check: {report}")
    return counts


async def migrate_postgres_to_sqlite(source_url: str, destination: Path, *, overwrite: bool) -> dict[str, int]:
    """Copy relational rows from PostgreSQL. Vector columns are not copied.

    The caller must pass --yes when the destination already exists.
    """
    if destination.exists() and not overwrite:
        raise StandaloneDataError("Standalone database already exists. Pass --yes to replace it.")
    if destination.exists():
        destination.unlink()
    initialize(destination)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(source_url)
    tables = (
        "users",
        "external_identities",
        "projects",
        "conversations",
        "messages",
        "files",
        "code_chunks",
        "agent_runs",
        "agent_run_events",
    )
    counts: dict[str, int] = {}
    try:
        async with engine.connect() as connection:
            for table in tables:
                rows = (await connection.execute(text(f"SELECT * FROM {table}"))).mappings().all()
                _insert_rows(destination, table, rows)
                counts[table] = len(rows)
            counts["code_embeddings"] = 0
    finally:
        await engine.dispose()
    report = integrity_report(destination)
    if report != "ok":
        raise StandaloneDataError(f"Migrated database failed integrity check: {report}")
    return counts


def _insert_rows(destination: Path, table: str, rows: Sequence[Any]) -> None:
    if not rows:
        return
    columns = [key for key in rows[0] if key != "embedding"]
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    connection = sqlite3.connect(destination)
    try:
        connection.executemany(sql, [tuple(_adapt(row[column]) for column in columns) for row in rows])
        connection.commit()
    finally:
        connection.close()


def _adapt(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _table_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    connection = sqlite3.connect(path)
    try:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (name,) in tables:
            counts[name] = int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
    finally:
        connection.close()
    return counts

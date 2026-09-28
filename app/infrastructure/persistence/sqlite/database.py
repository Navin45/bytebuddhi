"""SQLite application database for the standalone profile.

Schema version is independent of the PostgreSQL Alembic history.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    api_key TEXT UNIQUE,
    usage_quota INTEGER NOT NULL DEFAULT 1000
);

CREATE TABLE IF NOT EXISTS external_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    email_snapshot TEXT,
    display_name_snapshot TEXT,
    avatar_url_snapshot TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (provider, provider_subject)
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    repository_url TEXT,
    local_path TEXT,
    language TEXT,
    framework TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_indexed_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    extra_metadata TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    extra_metadata TEXT,
    parent_message_id TEXT,
    feedback INTEGER
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    last_modified TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, file_path)
);

CREATE TABLE IF NOT EXISTS code_chunks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    extra_metadata TEXT
);

CREATE TABLE IF NOT EXISTS code_embeddings (
    id TEXT PRIMARY KEY,
    code_chunk_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    embedding TEXT NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    extra_metadata TEXT
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT,
    conversation_id TEXT,
    status TEXT NOT NULL,
    prompt TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    last_heartbeat_at TEXT,
    error_code TEXT,
    error_message TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0,
    event_sequence INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    worker_id TEXT,
    execution_attempt INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_acquired_at TEXT,
    lease_expires_at TEXT,
    UNIQUE (user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS agent_run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, sequence)
);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint_data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_created ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_agent_runs_status_created ON agent_runs(status, created_at);
CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_sequence ON agent_run_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS ix_agent_checkpoints_thread ON agent_checkpoints(thread_id, created_at);
"""


@dataclass
class SqliteSession:
    """Path handle passed through the composition root. Repositories open transactions."""

    path: Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict(path.parent)
    connection = sqlite3.connect(str(path), timeout=10.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")
    _restrict(path)
    return connection


def initialize(path: Path) -> None:
    """Create the standalone schema if this version has not been applied."""
    connection = connect(path)
    try:
        connection.executescript(_SCHEMA)
        row = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (SCHEMA_VERSION,),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )
        connection.commit()
    finally:
        connection.close()
    _restrict(path)


def integrity_report(path: Path) -> str:
    """Return SQLite's integrity result. Does not delete or repair the file."""
    if not path.is_file():
        return "not_initialized"
    connection = connect(path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if row is None:
        return "unavailable"
    return str(row[0])


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    initialize(path)
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def open_session(path: Path | None = None) -> SqliteSession:
    from app.infrastructure.config.profile import sqlite_database_path

    selected = path or sqlite_database_path()
    initialize(selected)
    return SqliteSession(path=selected)


def _restrict(path: Path) -> None:
    try:
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            os.chmod(path, 0o600)
    except OSError:
        return

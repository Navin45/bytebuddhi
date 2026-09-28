"""Standalone SQLite profile tests. They do not require PostgreSQL or Redis."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.runs.records import RunRecord
from app.application.runs.status import RunStatus
from app.domain.models.conversation import Conversation
from app.domain.models.project import Project
from app.domain.models.user import User
from app.infrastructure.config.profile import SERVER, STANDALONE, resolve_profile, sqlite_database_path
from app.infrastructure.persistence.sqlite.database import SqliteSession, integrity_report, open_session
from app.infrastructure.persistence.sqlite.maintenance import StandaloneDataError, copy_sqlite_database, export_backup
from app.infrastructure.persistence.sqlite.repositories import (
    SqliteConversationRepository,
    SqliteProjectRepository,
    SqliteUserRepository,
)
from app.infrastructure.persistence.sqlite.run_store import SqliteRunStore, recover_standalone_runs


def test_profile_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYTEBUDDHI_PROFILE", raising=False)
    assert resolve_profile() == SERVER
    assert resolve_profile(persisted="standalone") == STANDALONE
    assert resolve_profile(cli="server", persisted="standalone") == SERVER
    monkeypatch.setenv("BYTEBUDDHI_PROFILE", "standalone")
    assert resolve_profile(persisted="server") == STANDALONE
    with pytest.raises(ValueError):
        resolve_profile(cli="sqlite")


def test_sqlite_path_uses_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BYTEBUDDHI_SQLITE_PATH", raising=False)
    assert sqlite_database_path() == tmp_path / "data" / "bytebuddhi.db"


def test_conversation_survives_reopen(tmp_path) -> None:
    path = tmp_path / "data" / "bytebuddhi.db"
    session = open_session(path)
    now = datetime.now(UTC).replace(tzinfo=None)
    user = User(uuid4(), "a@example.com", "ada", None, now, now)
    project = Project(uuid4(), user.id, "demo", None, None, None, None, None, now, now, None)
    conversation = Conversation.create(user.id, project.id, "first")
    repo_user = SqliteUserRepository(session)
    repo_project = SqliteProjectRepository(session)
    repo_conversation = SqliteConversationRepository(session)

    async def _write() -> None:
        await repo_user.create(user)
        await repo_project.create(project)
        await repo_conversation.create(conversation)

    import asyncio

    asyncio.run(_write())
    reopened = SqliteConversationRepository(SqliteSession(path))
    loaded = asyncio.run(reopened.get_by_id(conversation.id))
    assert loaded is not None
    assert loaded.title == "first"
    assert integrity_report(path) == "ok"


def test_run_events_replay_after_restart(tmp_path) -> None:
    path = tmp_path / "runs.db"
    store = SqliteRunStore(path)
    user_id = uuid4()
    started = time.perf_counter()
    run = RunRecord(
        id=str(uuid4()),
        user_id=user_id,
        project_id=None,
        conversation_id=None,
        status=RunStatus.QUEUED,
        prompt="hello",
        prompt_sha256="abc",
    )

    async def _scenario() -> None:
        await store.insert(run)
        claimed = await store.claim_run(run.id, worker_id="local", lease_seconds=30)
        assert claimed is not None and claimed.lease_token
        active = await store.activate(run.id, claimed.lease_token, lease_seconds=30)
        assert active is not None
        await store.append_event(
            run.id,
            "run_completed",
            {"output": "done"},
            lease_token=active.lease_token,
        )
        restarted = SqliteRunStore(path)
        page = await restarted.list_events(run.id, after_sequence=0)
        assert [event.event_type for event in page.events] == ["run_completed"]
        loaded = await restarted.get(run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.COMPLETED

    import asyncio

    asyncio.run(_scenario())
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0


def test_restart_interrupts_unfinished_run_instead_of_approving_it(tmp_path) -> None:
    path = tmp_path / "approval.db"
    store = SqliteRunStore(path)
    run = RunRecord(
        id=str(uuid4()),
        user_id=uuid4(),
        project_id=None,
        conversation_id=None,
        status=RunStatus.QUEUED,
        prompt="risky",
        prompt_sha256="def",
    )

    async def _scenario() -> None:
        await store.insert(run)
        claimed = await store.claim_run(run.id, worker_id="local", lease_seconds=30)
        assert claimed is not None and claimed.lease_token
        active = await store.activate(run.id, claimed.lease_token, lease_seconds=30)
        assert active is not None and active.lease_token
        await store.append_event(
            run.id,
            "tool_approval_required",
            {"action": "shell"},
            lease_token=active.lease_token,
        )
        interrupted = await recover_standalone_runs(SqliteRunStore(path))
        assert interrupted[0].event_type == "run_interrupted"
        loaded = await store.get(run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.INTERRUPTED

    import asyncio

    asyncio.run(_scenario())


def test_cancel_requested_is_distinct_from_cancelled(tmp_path) -> None:
    path = tmp_path / "cancel.db"
    store = SqliteRunStore(path)
    run = RunRecord(
        id=str(uuid4()),
        user_id=uuid4(),
        project_id=None,
        conversation_id=None,
        status=RunStatus.QUEUED,
        prompt="stop",
        prompt_sha256="ghi",
    )

    async def _scenario() -> None:
        await store.insert(run)
        claimed = await store.claim_run(run.id, worker_id="local", lease_seconds=30)
        assert claimed is not None and claimed.lease_token
        active = await store.activate(run.id, claimed.lease_token, lease_seconds=30)
        assert active is not None and active.lease_token
        requested = await store.append_event(run.id, "run_cancel_requested", {}, lease_token=active.lease_token)
        mid = await store.get(run.id)
        assert requested.event_type == "run_cancel_requested"
        assert mid is not None and mid.status == RunStatus.CANCELLING and mid.cancellation_requested
        await store.append_event(run.id, "run_cancelled", {}, lease_token=active.lease_token)
        done = await store.get(run.id)
        assert done is not None and done.status == RunStatus.CANCELLED

    import asyncio

    asyncio.run(_scenario())


def test_migrate_refuses_to_replace_an_existing_database(tmp_path) -> None:
    destination = tmp_path / "bytebuddhi.db"
    open_session(destination)

    async def _migrate() -> None:
        from app.infrastructure.persistence.sqlite.maintenance import migrate_postgres_to_sqlite

        await migrate_postgres_to_sqlite("postgresql+asyncpg://unused", destination, overwrite=False)

    import asyncio

    with pytest.raises(StandaloneDataError):
        asyncio.run(_migrate())


def test_standalone_imports_do_not_load_postgres(tmp_path) -> None:
    import subprocess
    import sys

    script = """
import os, sys
os.environ["BYTEBUDDHI_PROFILE"] = "standalone"
os.environ["BYTEBUDDHI_SQLITE_PATH"] = sys.argv[1]
import app.infrastructure.persistence.sqlite.run_store
import app.infrastructure.persistence.sessions
import app.interfaces.api.run_runtime
assert "app.infrastructure.persistence.postgres.database" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "bytebuddhi.db")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_backup_excludes_credentials_and_refuses_overwrite(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYTEBUDDHI_SQLITE_PATH", str(tmp_path / "bytebuddhi.db"))
    monkeypatch.setenv("BYTEBUDDHI_CONFIG_DIR", str(tmp_path))
    open_session(tmp_path / "bytebuddhi.db")
    (tmp_path / "config.json").write_text('{"profile": "standalone", "token": "secret-value"}', encoding="utf-8")
    archive = export_backup(tmp_path / "backup.zip")
    import zipfile

    with zipfile.ZipFile(archive) as zipped:
        names = set(zipped.namelist())
        metadata = zipped.read("config_metadata.json").decode("utf-8")
    assert "bytebuddhi.db" in names
    assert "credentials" not in names
    assert "secret-value" not in metadata
    with pytest.raises(StandaloneDataError):
        copy_sqlite_database(tmp_path / "bytebuddhi.db", tmp_path / "bytebuddhi.db", overwrite=False)

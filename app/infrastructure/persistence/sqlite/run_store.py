"""SQLite run store for the standalone profile.

Coordination is a local transaction. There is no SELECT FOR UPDATE or SKIP LOCKED.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from uuid import UUID, uuid4

from app.application.runs.records import EVENT_PAGE_LIMIT, SCHEMA_VERSION, EventPage, RunEventRecord, RunRecord
from app.application.runs.status import RunStatus, is_terminal
from app.application.runs.store import (
    _activate,
    _apply_event,
    _clear_lease,
    _idempotent_terminal,
    _is_stale,
    _renew,
    _require_lease,
    _reserve,
    utc_now,
)
from app.infrastructure.persistence.sqlite.database import transaction


class SqliteRunStore:
    def __init__(self, path) -> None:
        self.path = path

    async def insert(self, run: RunRecord) -> RunRecord:
        return await asyncio.to_thread(self._insert, run)

    async def get(self, run_id: str) -> RunRecord | None:
        return await asyncio.to_thread(self._get, run_id)

    async def get_for_user(self, run_id: str, user_id: UUID) -> RunRecord | None:
        run = await self.get(run_id)
        if run is None or run.user_id != user_id:
            return None
        return run

    async def find_idempotent(self, user_id: UUID, idempotency_key: str) -> RunRecord | None:
        return await asyncio.to_thread(self._find_idempotent, user_id, idempotency_key)

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        schema_version: int = SCHEMA_VERSION,
        lease_token: str | None = None,
    ) -> RunEventRecord:
        return await asyncio.to_thread(self._append_event, run_id, event_type, payload, schema_version, lease_token)

    async def list_events(self, run_id: str, *, after_sequence: int, limit: int = EVENT_PAGE_LIMIT) -> EventPage:
        if after_sequence < 0 or limit < 1:
            raise ValueError("invalid cursor")
        return await asyncio.to_thread(self._list_events, run_id, after_sequence, limit)

    async def touch_heartbeat(self, run_id: str, when: datetime | None = None) -> None:
        await asyncio.to_thread(self._touch_heartbeat, run_id, when)

    async def update_conversation(
        self, run_id: str, conversation_id: UUID | None, *, lease_token: str | None = None
    ) -> None:
        await asyncio.to_thread(self._update_conversation, run_id, conversation_id, lease_token)

    async def claim_run(self, run_id: str, *, worker_id: str, lease_seconds: float) -> RunRecord | None:
        return await asyncio.to_thread(self._claim_run, run_id, worker_id, lease_seconds)

    async def claim_next(self, *, worker_id: str, lease_seconds: float) -> RunRecord | None:
        return await asyncio.to_thread(self._claim_next, worker_id, lease_seconds)

    async def activate(self, run_id: str, lease_token: str, *, lease_seconds: float) -> RunRecord | None:
        return await asyncio.to_thread(self._activate, run_id, lease_token, lease_seconds)

    async def release_reservation(self, run_id: str, lease_token: str) -> bool:
        return await asyncio.to_thread(self._release_reservation, run_id, lease_token)

    async def renew_lease(self, run_id: str, lease_token: str, *, lease_seconds: float) -> bool:
        return await asyncio.to_thread(self._renew_lease, run_id, lease_token, lease_seconds)

    async def abandon_lease(self, run_id: str, lease_token: str) -> bool:
        return await asyncio.to_thread(self._abandon_lease, run_id, lease_token)

    async def interrupt_stale(self, *, limit: int) -> list[RunEventRecord]:
        return await asyncio.to_thread(self._interrupt_stale, limit)

    async def list_by_status(self, statuses: set[RunStatus]) -> list[RunRecord]:
        return await asyncio.to_thread(self._list_by_status, statuses)

    def _insert(self, run: RunRecord) -> RunRecord:
        try:
            with transaction(self.path) as connection:
                if run.idempotency_key:
                    existing = self._idempotent_row(connection, run.user_id, run.idempotency_key)
                    if existing is not None:
                        return _row_to_run(existing)
                stored = run.copy()
                if stored.created_at is None:
                    stored.created_at = utc_now()
                _save_run(connection, stored)
                return stored.copy()
        except sqlite3.IntegrityError:
            if not run.idempotency_key:
                raise
            found = self._find_idempotent(run.user_id, run.idempotency_key)
            if found is None:
                raise
            return found

    def _get(self, run_id: str) -> RunRecord | None:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            return _row_to_run(row) if row is not None else None

    def _find_idempotent(self, user_id: UUID, idempotency_key: str) -> RunRecord | None:
        with transaction(self.path) as connection:
            row = self._idempotent_row(connection, user_id, idempotency_key)
            return _row_to_run(row) if row is not None else None

    def _append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        schema_version: int,
        lease_token: str | None,
    ) -> RunEventRecord:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = _row_to_run(row)
            events = _load_events(connection, run_id)
            existing = _idempotent_terminal(run, event_type, events)
            if existing is not None:
                return existing
            _require_lease(run, lease_token)
            _apply_event(run, event_type, payload, utc_now)
            run.event_sequence += 1
            record = RunEventRecord(
                event_id=str(uuid4()),
                run_id=run_id,
                sequence=run.event_sequence,
                event_type=event_type,
                schema_version=schema_version,
                payload=dict(payload),
                created_at=utc_now(),
            )
            _save_run(connection, run)
            _insert_event(connection, record)
            return record

    def _list_events(self, run_id: str, after_sequence: int, limit: int) -> EventPage:
        with transaction(self.path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (run_id, after_sequence, limit + 1),
            ).fetchall()
        page_rows = rows[:limit]
        page = tuple(_row_to_event(row) for row in page_rows)
        has_more = len(rows) > limit
        next_sequence = page[-1].sequence if page else after_sequence
        return EventPage(events=page, next_sequence=next_sequence, has_more=has_more)

    def _touch_heartbeat(self, run_id: str, when: datetime | None) -> None:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return
            run = _row_to_run(row)
            if is_terminal(run.status):
                return
            run.last_heartbeat_at = when or utc_now()
            _save_run(connection, run)

    def _update_conversation(self, run_id: str, conversation_id: UUID | None, lease_token: str | None) -> None:
        if conversation_id is None:
            return
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return
            run = _row_to_run(row)
            if run.lease_token is not None:
                _require_lease(run, lease_token)
            run.conversation_id = conversation_id
            _save_run(connection, run)

    def _claim_run(self, run_id: str, worker_id: str, lease_seconds: float) -> RunRecord | None:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            run = _row_to_run(row)
            if not _reserve(run, worker_id, lease_seconds, utc_now):
                return None
            _save_run(connection, run)
            return run.copy()

    def _claim_next(self, worker_id: str, lease_seconds: float) -> RunRecord | None:
        with transaction(self.path) as connection:
            rows = connection.execute(
                "SELECT id FROM agent_runs WHERE status = ? ORDER BY created_at",
                (RunStatus.QUEUED.value,),
            ).fetchall()
            for row in rows:
                claimed = self._claim_loaded(connection, row["id"], worker_id, lease_seconds)
                if claimed is not None:
                    return claimed
        return None

    def _claim_loaded(self, connection, run_id: str, worker_id: str, lease_seconds: float) -> RunRecord | None:
        row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        run = _row_to_run(row)
        if not _reserve(run, worker_id, lease_seconds, utc_now):
            return None
        _save_run(connection, run)
        return run.copy()

    def _activate(self, run_id: str, lease_token: str, lease_seconds: float) -> RunRecord | None:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            run = _row_to_run(row)
            if not _activate(run, lease_token, lease_seconds, utc_now):
                return None
            _save_run(connection, run)
            return run.copy()

    def _release_reservation(self, run_id: str, lease_token: str) -> bool:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return False
            run = _row_to_run(row)
            if run.status != RunStatus.QUEUED or run.lease_token != lease_token:
                return False
            _clear_lease(run)
            _save_run(connection, run)
            return True

    def _renew_lease(self, run_id: str, lease_token: str, lease_seconds: float) -> bool:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return False
            run = _row_to_run(row)
            if not _renew(run, lease_token, lease_seconds, utc_now):
                return False
            _save_run(connection, run)
            return True

    def _abandon_lease(self, run_id: str, lease_token: str) -> bool:
        with transaction(self.path) as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return False
            run = _row_to_run(row)
            if run.lease_token != lease_token or is_terminal(run.status):
                return False
            run.lease_expires_at = utc_now()
            _save_run(connection, run)
            return True

    def _interrupt_stale(self, limit: int) -> list[RunEventRecord]:
        written: list[RunEventRecord] = []
        with transaction(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs WHERE status IN (?, ?) ORDER BY lease_expires_at",
                (RunStatus.RUNNING.value, RunStatus.CANCELLING.value),
            ).fetchall()
            for row in rows:
                if len(written) >= limit:
                    break
                run = _row_to_run(row)
                if not _is_stale(run, utc_now()):
                    continue
                written.append(_interrupt(connection, run, "The worker lease expired and the run was not replayed"))
        return written

    def _list_by_status(self, statuses: set[RunStatus]) -> list[RunRecord]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        with transaction(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM agent_runs WHERE status IN ({placeholders})",
                tuple(status.value for status in statuses),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def _idempotent_row(self, connection, user_id: UUID, idempotency_key: str):
        return connection.execute(
            "SELECT * FROM agent_runs WHERE user_id = ? AND idempotency_key = ?",
            (str(user_id), idempotency_key),
        ).fetchone()


async def recover_standalone_runs(store: SqliteRunStore) -> list[RunEventRecord]:
    """Interrupt runs left active by a previous gateway process."""
    return await asyncio.to_thread(
        _recover,
        store,
        "The local gateway restarted before the run finished. Request approval again before a risky tool runs.",
    )


def _recover(store: SqliteRunStore, message: str) -> list[RunEventRecord]:
    written: list[RunEventRecord] = []
    with transaction(store.path) as connection:
        rows = connection.execute(
            "SELECT * FROM agent_runs WHERE status IN (?, ?)",
            (RunStatus.RUNNING.value, RunStatus.CANCELLING.value),
        ).fetchall()
        for row in rows:
            written.append(_interrupt(connection, _row_to_run(row), message))
    return written


def _interrupt(connection, run: RunRecord, message: str) -> RunEventRecord:
    attempt = run.execution_attempt
    payload = {
        "error_code": "RUN_INTERRUPTED",
        "error_message": message,
        "execution_attempt": attempt,
    }
    _apply_event(run, "run_interrupted", payload, utc_now)
    _clear_lease(run)
    run.event_sequence += 1
    record = RunEventRecord(
        event_id=str(uuid4()),
        run_id=run.id,
        sequence=run.event_sequence,
        event_type="run_interrupted",
        schema_version=SCHEMA_VERSION,
        payload=payload,
        created_at=utc_now(),
    )
    _save_run(connection, run)
    _insert_event(connection, record)
    return record


def _save_run(connection, run: RunRecord) -> None:
    connection.execute(
        """
        INSERT INTO agent_runs (
            id, user_id, project_id, conversation_id, status, prompt, prompt_sha256,
            provider, model, created_at, started_at, completed_at, last_heartbeat_at,
            error_code, error_message, cancellation_requested, event_sequence, idempotency_key,
            worker_id, execution_attempt, lease_token, lease_acquired_at, lease_expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            project_id = excluded.project_id,
            conversation_id = excluded.conversation_id,
            status = excluded.status,
            prompt = excluded.prompt,
            prompt_sha256 = excluded.prompt_sha256,
            provider = excluded.provider,
            model = excluded.model,
            started_at = excluded.started_at,
            completed_at = excluded.completed_at,
            last_heartbeat_at = excluded.last_heartbeat_at,
            error_code = excluded.error_code,
            error_message = excluded.error_message,
            cancellation_requested = excluded.cancellation_requested,
            event_sequence = excluded.event_sequence,
            idempotency_key = excluded.idempotency_key,
            worker_id = excluded.worker_id,
            execution_attempt = excluded.execution_attempt,
            lease_token = excluded.lease_token,
            lease_acquired_at = excluded.lease_acquired_at,
            lease_expires_at = excluded.lease_expires_at
        """,
        (
            run.id,
            str(run.user_id),
            _uuid(run.project_id),
            _uuid(run.conversation_id),
            run.status.value,
            run.prompt,
            run.prompt_sha256,
            run.provider,
            run.model,
            _iso(run.created_at),
            _iso(run.started_at),
            _iso(run.completed_at),
            _iso(run.last_heartbeat_at),
            run.error_code,
            run.error_message,
            int(run.cancellation_requested),
            run.event_sequence,
            run.idempotency_key,
            run.worker_id,
            run.execution_attempt,
            run.lease_token,
            _iso(run.lease_acquired_at),
            _iso(run.lease_expires_at),
        ),
    )


def _insert_event(connection, record: RunEventRecord) -> None:
    connection.execute(
        """
        INSERT INTO agent_run_events (id, run_id, sequence, event_type, schema_version, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.event_id,
            record.run_id,
            record.sequence,
            record.event_type,
            record.schema_version,
            json.dumps(record.payload),
            _iso(record.created_at),
        ),
    )


def _load_events(connection, run_id: str) -> list[RunEventRecord]:
    rows = connection.execute(
        "SELECT * FROM agent_run_events WHERE run_id = ? ORDER BY sequence",
        (run_id,),
    ).fetchall()
    return [_row_to_event(row) for row in rows]


def _row_to_run(row) -> RunRecord:
    return RunRecord(
        id=row["id"],
        user_id=UUID(row["user_id"]),
        project_id=UUID(row["project_id"]) if row["project_id"] else None,
        conversation_id=UUID(row["conversation_id"]) if row["conversation_id"] else None,
        status=RunStatus(row["status"]),
        prompt=row["prompt"],
        prompt_sha256=row["prompt_sha256"],
        provider=row["provider"],
        model=row["model"],
        created_at=_parse_dt(row["created_at"]),
        started_at=_parse_dt(row["started_at"]),
        completed_at=_parse_dt(row["completed_at"]),
        last_heartbeat_at=_parse_dt(row["last_heartbeat_at"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        cancellation_requested=bool(row["cancellation_requested"]),
        event_sequence=row["event_sequence"],
        idempotency_key=row["idempotency_key"],
        worker_id=row["worker_id"],
        execution_attempt=row["execution_attempt"],
        lease_token=row["lease_token"],
        lease_acquired_at=_parse_dt(row["lease_acquired_at"]),
        lease_expires_at=_parse_dt(row["lease_expires_at"]),
    )


def _row_to_event(row) -> RunEventRecord:
    return RunEventRecord(
        event_id=row["id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        event_type=row["event_type"],
        schema_version=row["schema_version"],
        payload=json.loads(row["payload"]),
        created_at=_parse_dt(row["created_at"]),
    )


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)

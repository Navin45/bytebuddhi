"""PostgreSQL run store. Event sequence is allocated under a row lock."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, overload
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.runs.records import EVENT_PAGE_LIMIT, SCHEMA_VERSION, EventPage, RunEventRecord, RunRecord
from app.application.runs.status import RunStatus, is_terminal
from app.application.runs.store import (
    _activate,
    _apply_event,
    _clear_lease,
    _is_stale,
    _renew,
    _require_lease,
    _reserve,
    utc_now,
)
from app.infrastructure.persistence.postgres.models import AgentRunEventModel, AgentRunModel


class SqlRunStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def insert(self, run: RunRecord) -> RunRecord:
        try:
            return await self._insert(run)
        except IntegrityError:
            if not run.idempotency_key:
                raise
            existing = await self.find_idempotent(run.user_id, run.idempotency_key)
            if existing is None:
                raise
            return existing

    async def _insert(self, run: RunRecord) -> RunRecord:
        async with self._sessions() as session, session.begin():
            if run.idempotency_key:
                existing = await _idempotent(session, run.user_id, run.idempotency_key)
                if existing is not None:
                    return _to_record(existing)
            row = _to_model(run)
            session.add(row)
            await session.flush()
            return _to_record(row)

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._sessions() as session:
            row = await session.get(AgentRunModel, UUID(run_id))
            return _to_record(row) if row is not None else None

    async def get_for_user(self, run_id: str, user_id: UUID) -> RunRecord | None:
        run = await self.get(run_id)
        if run is None or run.user_id != user_id:
            return None
        return run

    async def find_idempotent(self, user_id: UUID, idempotency_key: str) -> RunRecord | None:
        async with self._sessions() as session:
            row = await _idempotent(session, user_id, idempotency_key)
            return _to_record(row) if row is not None else None

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        schema_version: int = SCHEMA_VERSION,
        lease_token: str | None = None,
    ) -> RunEventRecord:
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id)
            record = _to_record(row)
            if is_terminal(record.status) and record.status.value == _terminal_name(event_type):
                existing = await _last_event(session, row.id)
                if existing is not None and existing.event_type == event_type:
                    return _to_event(existing)
            if record.lease_token is not None or lease_token is not None:
                _require_lease(record, lease_token)
            _apply_event(record, event_type, payload, utc_now)
            record.event_sequence += 1
            _copy_status(record, row)
            event = _event_row(row, record, event_type, schema_version, payload)
            session.add(event)
            await session.flush()
            return _to_event(event)

    async def list_events(self, run_id: str, *, after_sequence: int, limit: int = EVENT_PAGE_LIMIT) -> EventPage:
        if after_sequence < 0 or limit < 1:
            raise ValueError("invalid cursor")
        async with self._sessions() as session:
            stmt = (
                select(AgentRunEventModel)
                .where(
                    AgentRunEventModel.run_id == UUID(run_id),
                    AgentRunEventModel.sequence > after_sequence,
                )
                .order_by(AgentRunEventModel.sequence.asc())
                .limit(limit + 1)
            )
            rows = list((await session.execute(stmt)).scalars())
        has_more = len(rows) > limit
        page = tuple(_to_event(row) for row in rows[:limit])
        next_sequence = page[-1].sequence if page else after_sequence
        return EventPage(events=page, next_sequence=next_sequence, has_more=has_more)

    async def touch_heartbeat(self, run_id: str, when: datetime | None = None) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(AgentRunModel, UUID(run_id))
            if row is None or is_terminal(RunStatus(row.status)):
                return
            row.last_heartbeat_at = when or utc_now()

    async def update_conversation(
        self, run_id: str, conversation_id: UUID | None, *, lease_token: str | None = None
    ) -> None:
        if conversation_id is None:
            return
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id)
            record = _to_record(row)
            if record.lease_token is not None:
                _require_lease(record, lease_token)
            row.conversation_id = conversation_id

    async def claim_run(self, run_id: str, *, worker_id: str, lease_seconds: float) -> RunRecord | None:
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id, missing_ok=True)
            if row is None:
                return None
            record = _to_record(row)
            if not _reserve(record, worker_id, lease_seconds, utc_now):
                return None
            _copy_lease(record, row)
            return _to_record(row)

    async def claim_next(self, *, worker_id: str, lease_seconds: float) -> RunRecord | None:
        now = utc_now()
        async with self._sessions() as session, session.begin():
            stmt = (
                select(AgentRunModel)
                .where(AgentRunModel.status == RunStatus.QUEUED.value)
                .where(or_(AgentRunModel.lease_expires_at.is_(None), AgentRunModel.lease_expires_at < now))
                .order_by(AgentRunModel.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            record = _to_record(row)
            if not _reserve(record, worker_id, lease_seconds, utc_now):
                return None
            _copy_lease(record, row)
            return _to_record(row)

    async def activate(self, run_id: str, lease_token: str, *, lease_seconds: float) -> RunRecord | None:
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id, missing_ok=True)
            if row is None:
                return None
            record = _to_record(row)
            if not _activate(record, lease_token, lease_seconds, utc_now):
                return None
            _copy_lease(record, row)
            _copy_status(record, row)
            return _to_record(row)

    async def release_reservation(self, run_id: str, lease_token: str) -> bool:
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id, missing_ok=True)
            if row is None or row.status != RunStatus.QUEUED.value or str(row.lease_token or "") != lease_token:
                return False
            record = _to_record(row)
            _clear_lease(record)
            _copy_lease(record, row)
            return True

    async def renew_lease(self, run_id: str, lease_token: str, *, lease_seconds: float) -> bool:
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id, missing_ok=True)
            if row is None:
                return False
            record = _to_record(row)
            if not _renew(record, lease_token, lease_seconds, utc_now):
                return False
            _copy_lease(record, row)
            _copy_status(record, row)
            return True

    async def abandon_lease(self, run_id: str, lease_token: str) -> bool:
        async with self._sessions() as session, session.begin():
            row = await _lock_run(session, run_id, missing_ok=True)
            if row is None or str(row.lease_token or "") != lease_token or is_terminal(RunStatus(row.status)):
                return False
            row.lease_expires_at = utc_now()
            return True

    async def interrupt_stale(self, *, limit: int) -> list[RunEventRecord]:
        now = utc_now()
        async with self._sessions() as session, session.begin():
            stmt = (
                select(AgentRunModel)
                .where(AgentRunModel.status.in_([RunStatus.RUNNING.value, RunStatus.CANCELLING.value]))
                .where(AgentRunModel.lease_expires_at.is_not(None))
                .where(AgentRunModel.lease_expires_at < now)
                .order_by(AgentRunModel.lease_expires_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = list((await session.execute(stmt)).scalars())
            written: list[RunEventRecord] = []
            for row in rows:
                record = _to_record(row)
                if not _is_stale(record, utc_now()):
                    continue
                attempt = record.execution_attempt
                payload = {
                    "error_code": "RUN_INTERRUPTED",
                    "error_message": "The worker lease expired and the run was not replayed",
                    "execution_attempt": attempt,
                }
                _apply_event(record, "run_interrupted", payload, utc_now)
                _clear_lease(record)
                record.event_sequence += 1
                _copy_status(record, row)
                _copy_lease(record, row)
                event = _event_row(row, record, "run_interrupted", SCHEMA_VERSION, payload)
                session.add(event)
                await session.flush()
                written.append(_to_event(event))
            return written


def _to_model(run: RunRecord) -> AgentRunModel:
    return AgentRunModel(
        id=UUID(run.id),
        user_id=run.user_id,
        project_id=run.project_id,
        conversation_id=run.conversation_id,
        status=run.status.value,
        prompt=run.prompt,
        prompt_sha256=run.prompt_sha256,
        provider=run.provider,
        model=run.model,
        created_at=run.created_at or utc_now(),
        started_at=run.started_at,
        completed_at=run.completed_at,
        last_heartbeat_at=run.last_heartbeat_at,
        error_code=run.error_code,
        error_message=run.error_message,
        cancellation_requested=run.cancellation_requested,
        event_sequence=run.event_sequence,
        idempotency_key=run.idempotency_key,
        worker_id=run.worker_id,
        execution_attempt=run.execution_attempt,
        lease_token=run.lease_token,
        lease_acquired_at=run.lease_acquired_at,
        lease_expires_at=run.lease_expires_at,
    )


def _copy_status(record: RunRecord, row: AgentRunModel) -> None:
    row.status = record.status.value
    row.event_sequence = record.event_sequence
    row.started_at = record.started_at
    row.completed_at = record.completed_at
    row.last_heartbeat_at = record.last_heartbeat_at
    row.cancellation_requested = record.cancellation_requested
    row.error_code = record.error_code
    row.error_message = record.error_message
    row.conversation_id = record.conversation_id
    row.execution_attempt = record.execution_attempt


def _copy_lease(record: RunRecord, row: AgentRunModel) -> None:
    row.worker_id = record.worker_id
    row.execution_attempt = record.execution_attempt
    row.lease_token = record.lease_token
    row.lease_acquired_at = record.lease_acquired_at
    row.lease_expires_at = record.lease_expires_at
    row.last_heartbeat_at = record.last_heartbeat_at


def _to_record(row: AgentRunModel) -> RunRecord:
    return RunRecord(
        id=str(row.id),
        user_id=row.user_id,
        project_id=row.project_id,
        conversation_id=row.conversation_id,
        status=RunStatus(row.status),
        prompt=row.prompt,
        prompt_sha256=row.prompt_sha256,
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        last_heartbeat_at=row.last_heartbeat_at,
        error_code=row.error_code,
        error_message=row.error_message,
        cancellation_requested=row.cancellation_requested,
        event_sequence=row.event_sequence,
        idempotency_key=row.idempotency_key,
        worker_id=row.worker_id,
        execution_attempt=row.execution_attempt,
        lease_token=row.lease_token,
        lease_acquired_at=row.lease_acquired_at,
        lease_expires_at=row.lease_expires_at,
    )


def _to_event(row: AgentRunEventModel) -> RunEventRecord:
    payload = dict(row.payload or {})
    return RunEventRecord(
        event_id=str(row.id),
        run_id=str(row.run_id),
        sequence=row.sequence,
        event_type=row.event_type,
        schema_version=row.schema_version,
        payload=payload,
        created_at=row.created_at,
    )


async def _idempotent(session: AsyncSession, user_id: UUID, idempotency_key: str) -> AgentRunModel | None:
    stmt = select(AgentRunModel).where(
        AgentRunModel.user_id == user_id,
        AgentRunModel.idempotency_key == idempotency_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@overload
async def _lock_run(session: AsyncSession, run_id: str, *, missing_ok: Literal[False] = False) -> AgentRunModel: ...


@overload
async def _lock_run(session: AsyncSession, run_id: str, *, missing_ok: Literal[True]) -> AgentRunModel | None: ...


async def _lock_run(session: AsyncSession, run_id: str, *, missing_ok: bool = False) -> AgentRunModel | None:
    stmt = select(AgentRunModel).where(AgentRunModel.id == UUID(run_id)).with_for_update()
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None and not missing_ok:
        raise KeyError(run_id)
    return row


async def _last_event(session: AsyncSession, run_id: UUID) -> AgentRunEventModel | None:
    stmt = (
        select(AgentRunEventModel)
        .where(AgentRunEventModel.run_id == run_id)
        .order_by(AgentRunEventModel.sequence.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _event_row(
    row: AgentRunModel,
    record: RunRecord,
    event_type: str,
    schema_version: int,
    payload: dict[str, object],
) -> AgentRunEventModel:
    return AgentRunEventModel(
        id=uuid4(),
        run_id=row.id,
        sequence=record.event_sequence,
        event_type=event_type,
        schema_version=schema_version,
        payload=dict(payload),
        created_at=utc_now(),
    )


def _terminal_name(event_type: str) -> str:
    from app.application.runs.store import _STATUS_EVENTS

    target = _STATUS_EVENTS.get(event_type)
    return target.value if target is not None else ""

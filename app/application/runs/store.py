"""Run persistence port and the in-memory store used by tests and the local worker fallback."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.application.runs.errors import LeaseLost
from app.application.runs.records import EVENT_PAGE_LIMIT, SCHEMA_VERSION, EventPage, RunEventRecord, RunRecord
from app.application.runs.status import RunStatus, assert_transition, is_terminal

_STATUS_EVENTS: dict[str, RunStatus] = {
    "run_started": RunStatus.RUNNING,
    "run_completed": RunStatus.COMPLETED,
    "run_failed": RunStatus.FAILED,
    "run_cancelled": RunStatus.CANCELLED,
    "run_interrupted": RunStatus.INTERRUPTED,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStore(Protocol):
    async def insert(self, run: RunRecord) -> RunRecord: ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def get_for_user(self, run_id: str, user_id: UUID) -> RunRecord | None: ...

    async def find_idempotent(self, user_id: UUID, idempotency_key: str) -> RunRecord | None: ...

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        schema_version: int = SCHEMA_VERSION,
        lease_token: str | None = None,
    ) -> RunEventRecord: ...

    async def list_events(self, run_id: str, *, after_sequence: int, limit: int = EVENT_PAGE_LIMIT) -> EventPage: ...

    async def touch_heartbeat(self, run_id: str, when: datetime | None = None) -> None: ...

    async def update_conversation(
        self, run_id: str, conversation_id: UUID | None, *, lease_token: str | None = None
    ) -> None: ...

    async def claim_run(self, run_id: str, *, worker_id: str, lease_seconds: float) -> RunRecord | None: ...

    async def claim_next(self, *, worker_id: str, lease_seconds: float) -> RunRecord | None: ...

    async def activate(self, run_id: str, lease_token: str, *, lease_seconds: float) -> RunRecord | None: ...

    async def release_reservation(self, run_id: str, lease_token: str) -> bool: ...

    async def renew_lease(self, run_id: str, lease_token: str, *, lease_seconds: float) -> bool: ...

    async def abandon_lease(self, run_id: str, lease_token: str) -> bool: ...

    async def interrupt_stale(self, *, limit: int) -> list[RunEventRecord]: ...


class MemoryRunStore:
    """Locked in-memory store. Sequence allocation is serialized per run."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or utc_now
        self._guard = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._runs: dict[str, RunRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._events: dict[str, list[RunEventRecord]] = {}

    async def insert(self, run: RunRecord) -> RunRecord:
        async with self._guard:
            if run.idempotency_key:
                existing_id = self._idempotency.get((str(run.user_id), run.idempotency_key))
                if existing_id is not None:
                    return self._runs[existing_id].copy()
                self._idempotency[(str(run.user_id), run.idempotency_key)] = run.id
            stored = run.copy()
            if stored.created_at is None:
                stored.created_at = self._clock()
            self._runs[stored.id] = stored
            self._events[stored.id] = []
            self._locks.setdefault(stored.id, asyncio.Lock())
            return stored.copy()

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._guard:
            run = self._runs.get(run_id)
            return run.copy() if run is not None else None

    async def get_for_user(self, run_id: str, user_id: UUID) -> RunRecord | None:
        run = await self.get(run_id)
        if run is None or run.user_id != user_id:
            return None
        return run

    async def find_idempotent(self, user_id: UUID, idempotency_key: str) -> RunRecord | None:
        async with self._guard:
            existing_id = self._idempotency.get((str(user_id), idempotency_key))
            if existing_id is None:
                return None
            return self._runs[existing_id].copy()

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        schema_version: int = SCHEMA_VERSION,
        lease_token: str | None = None,
    ) -> RunEventRecord:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(run_id)
            existing = _idempotent_terminal(run, event_type, self._events.get(run_id, []))
            if existing is not None:
                return existing
            _require_lease(run, lease_token)
            _apply_event(run, event_type, payload, self._clock)
            run.event_sequence += 1
            record = RunEventRecord(
                event_id=str(uuid4()),
                run_id=run_id,
                sequence=run.event_sequence,
                event_type=event_type,
                schema_version=schema_version,
                payload=dict(payload),
                created_at=self._clock(),
            )
            self._events[run_id].append(record)
            return record

    async def list_events(self, run_id: str, *, after_sequence: int, limit: int = EVENT_PAGE_LIMIT) -> EventPage:
        if after_sequence < 0 or limit < 1:
            raise ValueError("invalid cursor")
        async with self._guard:
            rows = [item for item in self._events.get(run_id, []) if item.sequence > after_sequence]
        rows.sort(key=lambda item: item.sequence)
        page = tuple(rows[:limit])
        has_more = len(rows) > limit
        next_sequence = page[-1].sequence if page else after_sequence
        return EventPage(events=page, next_sequence=next_sequence, has_more=has_more)

    async def touch_heartbeat(self, run_id: str, when: datetime | None = None) -> None:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None or is_terminal(run.status):
                return
            run.last_heartbeat_at = when or self._clock()

    async def update_conversation(
        self, run_id: str, conversation_id: UUID | None, *, lease_token: str | None = None
    ) -> None:
        if conversation_id is None:
            return
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            if run.lease_token is not None:
                _require_lease(run, lease_token)
            run.conversation_id = conversation_id

    async def claim_run(self, run_id: str, *, worker_id: str, lease_seconds: float) -> RunRecord | None:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None or not _reserve(run, worker_id, lease_seconds, self._clock):
                return None
            return run.copy()

    async def claim_next(self, *, worker_id: str, lease_seconds: float) -> RunRecord | None:
        async with self._guard:
            candidates = [
                run.id
                for run in self._runs.values()
                if run.status == RunStatus.QUEUED and not _lease_is_live(run, self._clock())
            ]
        candidates.sort(key=lambda run_id: self._runs[run_id].created_at or datetime.min.replace(tzinfo=UTC))
        for run_id in candidates:
            claimed = await self.claim_run(run_id, worker_id=worker_id, lease_seconds=lease_seconds)
            if claimed is not None:
                return claimed
        return None

    async def activate(self, run_id: str, lease_token: str, *, lease_seconds: float) -> RunRecord | None:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None or not _activate(run, lease_token, lease_seconds, self._clock):
                return None
            return run.copy()

    async def release_reservation(self, run_id: str, lease_token: str) -> bool:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None or run.status != RunStatus.QUEUED or run.lease_token != lease_token:
                return False
            _clear_lease(run)
            return True

    async def renew_lease(self, run_id: str, lease_token: str, *, lease_seconds: float) -> bool:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            return run is not None and _renew(run, lease_token, lease_seconds, self._clock)

    async def abandon_lease(self, run_id: str, lease_token: str) -> bool:
        lock = await self._lock_for(run_id)
        async with lock:
            run = self._runs.get(run_id)
            if run is None or run.lease_token != lease_token or is_terminal(run.status):
                return False
            run.lease_expires_at = self._clock()
            return True

    async def interrupt_stale(self, *, limit: int) -> list[RunEventRecord]:
        async with self._guard:
            stale_ids = [
                run.id
                for run in self._runs.values()
                if run.status in {RunStatus.RUNNING, RunStatus.CANCELLING}
                and run.lease_expires_at is not None
                and run.lease_expires_at < self._clock()
            ]
        stale_ids.sort(key=lambda run_id: self._runs[run_id].lease_expires_at or datetime.max.replace(tzinfo=UTC))
        written: list[RunEventRecord] = []
        for run_id in stale_ids[:limit]:
            lock = await self._lock_for(run_id)
            async with lock:
                run = self._runs.get(run_id)
                if run is None or not _is_stale(run, self._clock()):
                    continue
                attempt = run.execution_attempt
                _apply_event(
                    run,
                    "run_interrupted",
                    {
                        "error_code": "RUN_INTERRUPTED",
                        "error_message": "The worker lease expired and the run was not replayed",
                        "execution_attempt": attempt,
                    },
                    self._clock,
                )
                _clear_lease(run)
                run.event_sequence += 1
                record = RunEventRecord(
                    event_id=str(uuid4()),
                    run_id=run_id,
                    sequence=run.event_sequence,
                    event_type="run_interrupted",
                    schema_version=SCHEMA_VERSION,
                    payload={
                        "error_code": "RUN_INTERRUPTED",
                        "error_message": "The worker lease expired and the run was not replayed",
                        "execution_attempt": attempt,
                    },
                    created_at=self._clock(),
                )
                self._events[run_id].append(record)
                written.append(record)
        return written

    async def _lock_for(self, run_id: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(run_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[run_id] = lock
            return lock


def _apply_event(run: RunRecord, event_type: str, payload: dict[str, object], clock: Callable[[], datetime]) -> None:
    now = clock()
    if event_type == "run_cancel_requested":
        run.cancellation_requested = True
        if run.status == RunStatus.RUNNING:
            assert_transition(run.status, RunStatus.CANCELLING)
            run.status = RunStatus.CANCELLING
        return
    if event_type == "run_started" and run.status == RunStatus.RUNNING:
        return
    target = _STATUS_EVENTS.get(event_type)
    if target is None:
        return
    if is_terminal(run.status) and run.status == target:
        return
    assert_transition(run.status, target)
    run.status = target
    if target == RunStatus.RUNNING and run.started_at is None:
        run.started_at = now
        run.last_heartbeat_at = now
    if is_terminal(target):
        run.completed_at = now
        code = payload.get("error_code")
        message = payload.get("error_message")
        if isinstance(code, str):
            run.error_code = code[:64]
        if isinstance(message, str):
            run.error_message = message[:300]


def _require_lease(run: RunRecord, lease_token: str | None) -> None:
    if lease_token is None:
        return
    if run.lease_token != lease_token:
        raise LeaseLost()


def _idempotent_terminal(
    run: RunRecord,
    event_type: str,
    events: list[RunEventRecord],
) -> RunEventRecord | None:
    target = _STATUS_EVENTS.get(event_type)
    if target is None or not is_terminal(run.status) or run.status != target or not events:
        return None
    last = events[-1]
    if last.event_type == event_type:
        return last
    return None


def _lease_is_live(run: RunRecord, now: datetime) -> bool:
    return run.lease_token is not None and run.lease_expires_at is not None and run.lease_expires_at > now


def _is_stale(run: RunRecord, now: datetime) -> bool:
    return (
        run.status in {RunStatus.RUNNING, RunStatus.CANCELLING}
        and run.lease_expires_at is not None
        and run.lease_expires_at < now
    )


def _clear_lease(run: RunRecord) -> None:
    run.worker_id = None
    run.lease_token = None
    run.lease_acquired_at = None
    run.lease_expires_at = None


def _reserve(run: RunRecord, worker_id: str, lease_seconds: float, clock: Callable[[], datetime]) -> bool:
    now = clock()
    if run.status != RunStatus.QUEUED or _lease_is_live(run, now):
        return False
    run.worker_id = worker_id
    run.lease_token = str(uuid4())
    run.lease_acquired_at = now
    run.last_heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return True


def _activate(run: RunRecord, lease_token: str, lease_seconds: float, clock: Callable[[], datetime]) -> bool:
    if run.status != RunStatus.QUEUED or run.lease_token != lease_token:
        return False
    assert_transition(run.status, RunStatus.RUNNING)
    now = clock()
    run.status = RunStatus.RUNNING
    run.execution_attempt += 1
    if run.started_at is None:
        run.started_at = now
    run.last_heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return True


def _renew(run: RunRecord, lease_token: str, lease_seconds: float, clock: Callable[[], datetime]) -> bool:
    if run.lease_token != lease_token or run.status not in {RunStatus.RUNNING, RunStatus.CANCELLING}:
        return False
    now = clock()
    run.last_heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=lease_seconds)
    return True

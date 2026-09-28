"""Real PostgreSQL leases and Redis admission.

Skip when the compose services are not reachable. Reproduce with:

    docker compose up -d postgres redis
    uv run alembic upgrade head
    uv run pytest tests/integration/test_distributed_execution.py -q
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.runs.admission import AdmissionDenied, AdmissionUnavailable
from app.application.runs.bus import InProcessRunBus
from app.application.runs.config import RunExecutionConfig
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.errors import LeaseLost
from app.application.runs.identity import WorkerIdentity
from app.application.runs.records import RunEventRecord, RunRecord
from app.application.runs.status import RunStatus
from app.application.use_cases.agent.execute_task import ExecuteTaskResult
from app.infrastructure.persistence.postgres.models import UserModel
from app.infrastructure.persistence.postgres.reaper_lock import PostgresReaperLock
from app.infrastructure.persistence.postgres.run_store import SqlRunStore

POSTGRES_URL = os.environ.get(
    "BYTEBUDDHI_TEST_DATABASE_URL",
    "postgresql+asyncpg://bytebuddhi:bytebuddhi-local@127.0.0.1:5432/bytebuddhi",
)
REDIS_URL = os.environ.get("BYTEBUDDHI_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


def _record(user_id, *, key: str | None = None, prompt: str = "hello") -> RunRecord:
    return RunRecord(
        id=str(uuid4()),
        user_id=user_id,
        project_id=None,
        conversation_id=None,
        status=RunStatus.QUEUED,
        prompt=prompt,
        prompt_sha256=prompt,
        created_at=datetime.now(UTC),
        idempotency_key=key,
    )


async def _postgres_ready():
    engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        if os.environ.get("BYTEBUDDHI_REQUIRE_DISTRIBUTED") == "1":
            pytest.fail(f"PostgreSQL is required for release validation but not available: {exc}")
        pytest.skip(f"PostgreSQL is not available: {exc}")
    async with engine.connect() as connection:
        present = await connection.scalar(text("SELECT to_regclass('public.agent_runs')"))
        column = await connection.scalar(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'agent_runs' AND column_name = 'lease_expires_at'"
            )
        )
    if present is None or column is None:
        await engine.dispose()
        env = os.environ.copy()
        env["DATABASE_URL"] = POSTGRES_URL
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        engine = create_async_engine(POSTGRES_URL, pool_pre_ping=True)
        async with engine.connect() as connection:
            column = await connection.scalar(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'agent_runs' AND column_name = 'lease_expires_at'"
                )
            )
        if column is None:
            await engine.dispose()
            message = f"agent_runs lease columns are missing: {completed.stderr}"
            if os.environ.get("BYTEBUDDHI_REQUIRE_DISTRIBUTED") == "1":
                pytest.fail(message)
            pytest.skip(message)
    return engine


@pytest.fixture
async def pg():
    engine = await _postgres_ready()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id.hex}@lease.test",
                username=f"u{user_id.hex[:24]}",
                password_hash="not-a-secret",
                is_active=True,
                usage_quota=1,
            )
        )
    store = SqlRunStore(sessions)
    try:
        yield store, sessions, user_id
    finally:
        async with sessions() as session, session.begin():
            await session.execute(text("DELETE FROM agent_runs WHERE user_id = :user_id"), {"user_id": user_id})
            await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        await engine.dispose()


async def _redis():
    from redis.asyncio import Redis

    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        if os.environ.get("BYTEBUDDHI_REQUIRE_DISTRIBUTED") == "1":
            pytest.fail(f"Redis is required for release validation but not available: {exc}")
        pytest.skip(f"Redis is not available: {exc}")
    await client.flushdb()
    return client


async def _activate(store: SqlRunStore, user_id):
    run = await store.insert(_record(user_id))
    reserved = await store.claim_run(run.id, worker_id="worker-a", lease_seconds=30)
    assert reserved is not None and reserved.lease_token
    active = await store.activate(run.id, reserved.lease_token, lease_seconds=30)
    assert active is not None and active.lease_token
    return active


@pytest.mark.asyncio
async def test_postgres_idempotency_and_single_claim(pg) -> None:
    store, _sessions, user_id = pg
    first = await store.insert(_record(user_id, key="same", prompt="one"))
    second = await store.insert(_record(user_id, key="same", prompt="one"))
    assert first.id == second.id
    other = await store.claim_run(first.id, worker_id="worker-a", lease_seconds=30)
    conflict = await store.claim_run(first.id, worker_id="worker-b", lease_seconds=30)
    assert other is not None and conflict is None


@pytest.mark.asyncio
async def test_postgres_concurrent_sequences_and_two_workers(pg) -> None:
    store, _sessions, user_id = pg
    active = await _activate(store, user_id)
    queued = [await store.insert(_record(user_id)) for _ in range(4)]

    async def append_once() -> int:
        event = await store.append_event(
            active.id,
            "assistant_delta",
            {"delta": "x"},
            lease_token=active.lease_token,
        )
        return event.sequence

    sequences = await asyncio.gather(*(append_once() for _ in range(6)))
    assert sorted(sequences) == [1, 2, 3, 4, 5, 6]

    async def take(worker: str) -> str | None:
        claimed = await store.claim_next(worker_id=worker, lease_seconds=30)
        return None if claimed is None else claimed.id

    claimed_ids = await asyncio.gather(*(take(f"worker-{index}") for index in range(4)))
    assert sorted(item for item in claimed_ids if item) == sorted(run.id for run in queued)


@pytest.mark.asyncio
async def test_postgres_stale_lease_blocks_the_old_worker(pg) -> None:
    store, sessions, user_id = pg
    active = await _activate(store, user_id)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE agent_runs SET lease_expires_at = now() - interval '1 second' WHERE id = :run_id"),
            {"run_id": active.id},
        )
    renewed = await store.renew_lease(active.id, active.lease_token or "", lease_seconds=30)
    assert renewed is True
    missed = await store.interrupt_stale(limit=10)
    assert missed == []
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE agent_runs SET lease_expires_at = now() - interval '1 second' WHERE id = :run_id"),
            {"run_id": active.id},
        )
    interrupted = await store.interrupt_stale(limit=10)
    assert [event.event_type for event in interrupted] == ["run_interrupted"]
    with pytest.raises(LeaseLost):
        await store.append_event(active.id, "run_completed", {"duration_ms": 1}, lease_token=active.lease_token)
    current = await store.get(active.id)
    assert current is not None and current.status == RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_postgres_completion_and_reaper_pick_one_terminal_state(pg) -> None:
    store, sessions, user_id = pg
    active = await _activate(store, user_id)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE agent_runs SET lease_expires_at = now() - interval '1 second' WHERE id = :run_id"),
            {"run_id": active.id},
        )

    async def complete() -> None:
        try:
            await store.append_event(active.id, "run_completed", {"duration_ms": 1}, lease_token=active.lease_token)
        except Exception:
            return

    await asyncio.gather(complete(), store.interrupt_stale(limit=5))
    current = await store.get(active.id)
    page = await store.list_events(active.id, after_sequence=0)
    terminals = [event.event_type for event in page.events if event.event_type in {"run_completed", "run_interrupted"}]
    assert current is not None
    assert current.status in {RunStatus.COMPLETED, RunStatus.INTERRUPTED}
    expected = "run_completed" if current.status == RunStatus.COMPLETED else "run_interrupted"
    assert terminals == [expected]


@pytest.mark.asyncio
async def test_postgres_cancel_and_complete_cannot_both_commit(pg) -> None:
    store, _sessions, user_id = pg
    active = await _activate(store, user_id)

    async def cancel() -> None:
        await store.append_event(active.id, "run_cancel_requested", {}, lease_token=active.lease_token)

    async def complete() -> None:
        try:
            await store.append_event(active.id, "run_completed", {"duration_ms": 1}, lease_token=active.lease_token)
        except Exception:
            return

    await asyncio.gather(cancel(), complete())
    current = await store.get(active.id)
    page = await store.list_events(active.id, after_sequence=0)
    types = [event.event_type for event in page.events]
    assert current is not None
    assert current.status in {RunStatus.COMPLETED, RunStatus.CANCELLING}
    if current.status == RunStatus.COMPLETED:
        assert "run_completed" in types
    else:
        assert "run_completed" not in types


@pytest.mark.asyncio
async def test_postgres_reaper_lock_is_single_leader(pg) -> None:
    _store, sessions, _user_id = pg
    first = PostgresReaperLock(sessions)
    second = PostgresReaperLock(sessions)
    assert await first.try_acquire() is True
    assert await second.try_acquire() is False
    await first.release()
    assert await second.try_acquire() is True
    await second.release()


@pytest.mark.asyncio
async def test_two_workers_execute_each_run_once(pg) -> None:
    store, _sessions, user_id = pg
    from app.application.runs.admission import LocalAdmission

    seen: list[str] = []
    current = 0
    peak = 0

    async def execute(command):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        seen.append(command.run_id or "")
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="ok",
            run_state=AgentRunState(run_id=command.run_id or "", status=AgentStatus.COMPLETED, final_response="ok"),
            conversation_id="",
            workspace_id="ws",
        )

    queue = LocalRunQueue()
    admission = LocalAdmission(1)
    config = RunExecutionConfig(
        heartbeat_seconds=0.05, lease_timeout_seconds=5, reaper_interval_seconds=30, shutdown_grace_seconds=2
    )
    workers = [
        RunCoordinator(
            store,
            InProcessRunBus(),
            queue,
            execute,
            admission=admission,
            config=config,
            identity=WorkerIdentity.create(),
        )
        for _ in range(2)
    ]
    for worker in workers:
        await worker.start()
    try:
        created = []
        for index in range(4):
            created.append(
                await workers[0].create_run(
                    user_id=user_id,
                    prompt=f"job-{index}",
                    project_id=None,
                    conversation_id=None,
                    provider=None,
                    model=None,
                    idempotency_key=f"job-{index}",
                )
            )
        for _ in range(80):
            if len(seen) == 4:
                rows = [await store.get(run.id) for run in created]
                if all(row is not None and row.status == RunStatus.COMPLETED for row in rows):
                    break
            await asyncio.sleep(0.05)
        assert sorted(seen) == sorted(run.id for run in created)
        assert peak == 1
        tokens = set()
        for run in created:
            current_run = await store.get(run.id)
            assert current_run is not None and current_run.status == RunStatus.COMPLETED
            assert current_run.lease_token
            tokens.add(current_run.lease_token)
        assert len(tokens) == 4
    finally:
        for worker in workers:
            await worker.stop()


@pytest.mark.asyncio
async def test_redis_admission_queue_and_fanout() -> None:
    client = await _redis()
    from redis.asyncio import Redis

    from app.infrastructure.persistence.redis.run_admission import RedisRunAdmission
    from app.infrastructure.persistence.redis.run_fanout import RedisLiveNotifier, RedisRunListener, RedisRunQueue

    try:
        admission = RedisRunAdmission(client, max_active=1)
        await admission.acquire("run-a", "worker-a", 30)
        with pytest.raises(AdmissionDenied):
            await admission.acquire("run-b", "worker-b", 30)
        await admission.acquire("run-a", "worker-a", 30)
        with pytest.raises(AdmissionDenied):
            await admission.acquire("run-a", "worker-b", 30)
        await admission.release("run-a", "worker-a")
        await admission.acquire("run-b", "worker-b", 1)
        await asyncio.sleep(1.6)
        await admission.acquire("run-c", "worker-c", 30)
        await admission.release("run-c", "worker-c")

        limited = RedisRunAdmission(client, max_active=2)
        results = await asyncio.gather(
            *(limited.acquire(f"batch-{index}", "worker", 30) for index in range(5)),
            return_exceptions=True,
        )
        assert sum(item is None for item in results) == 2
        assert sum(isinstance(item, AdmissionDenied) for item in results) == 3

        queue = RedisRunQueue(client)
        await queue.enqueue("run-queue")
        assert await queue.poll(1) == "run-queue"

        bus = InProcessRunBus()
        listener_client = Redis.from_url(REDIS_URL)
        subscription = bus.subscribe("run-live")
        listener = RedisRunListener(listener_client, bus)
        await listener.start()
        await asyncio.sleep(0.2)
        event = RunEventRecord(
            event_id=str(uuid4()),
            run_id="run-live",
            sequence=1,
            event_type="assistant_delta",
            schema_version=1,
            payload={"delta": "hi"},
            created_at=datetime.now(UTC),
        )
        await RedisLiveNotifier(client).publish(event)
        received = await asyncio.wait_for(subscription.queue.get(), timeout=2)
        assert received.sequence == 1
        await listener.stop()
        await listener_client.aclose()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_outage_fails_admission_closed() -> None:
    from redis.asyncio import Redis

    from app.infrastructure.persistence.redis.run_admission import RedisRunAdmission

    client = Redis.from_url("redis://127.0.0.1:6399/0", socket_connect_timeout=0.2)
    admission = RedisRunAdmission(client, max_active=1)
    with pytest.raises(AdmissionUnavailable):
        await admission.acquire("run-down", "worker", 30)
    await client.aclose()


@pytest.mark.asyncio
async def test_queued_run_survives_a_lost_redis_message(pg) -> None:
    store, _sessions, user_id = pg
    client = await _redis()
    from app.infrastructure.persistence.redis.run_fanout import RedisRunQueue

    try:
        run = await store.insert(_record(user_id))
        queue = RedisRunQueue(client)
        await queue.enqueue(run.id)
        await client.delete("bytebuddhi:run-queue")
        claimed = await store.claim_next(worker_id="worker-recovered", lease_seconds=30)
        assert claimed is not None and claimed.id == run.id
        assert claimed.status == RunStatus.QUEUED
    finally:
        await client.aclose()

"""Lease fencing, admission, and stale-run recovery without a live model."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.runs.admission import AdmissionDenied, AdmissionUnavailable, LocalAdmission
from app.application.runs.bus import InProcessRunBus
from app.application.runs.config import RunExecutionConfig
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.errors import LeaseLost
from app.application.runs.identity import WorkerIdentity
from app.application.runs.metrics import RunMetrics
from app.application.runs.reaper import RunReaper
from app.application.runs.records import RunRecord
from app.application.runs.status import InvalidRunTransition, RunStatus
from app.application.runs.store import MemoryRunStore
from app.application.runs.writer import EventWriter
from app.application.use_cases.agent.execute_task import ExecuteTaskResult


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _run(run_id: str = "run_lease") -> RunRecord:
    return RunRecord(
        id=run_id,
        user_id=uuid4(),
        project_id=None,
        conversation_id=None,
        status=RunStatus.QUEUED,
        prompt="hello",
        prompt_sha256="abc",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_worker_identity_is_not_only_a_pid() -> None:
    first = WorkerIdentity.create()
    second = WorkerIdentity.create()
    assert first.worker_id != second.worker_id
    assert str(first.process_id) != first.worker_id


def test_execution_config_rejects_a_lease_shorter_than_the_heartbeat() -> None:
    with pytest.raises(ValueError):
        RunExecutionConfig(heartbeat_seconds=15, lease_timeout_seconds=15).validate()


@pytest.mark.asyncio
async def test_one_run_has_one_lease() -> None:
    clock = _Clock()
    store = MemoryRunStore(clock)
    await store.insert(_run("run_a"))
    await store.insert(_run("run_b"))
    first = await store.claim_run("run_a", worker_id="worker-a", lease_seconds=30)
    second = await store.claim_run("run_a", worker_id="worker-b", lease_seconds=30)
    other = await store.claim_next(worker_id="worker-b", lease_seconds=30)
    assert first is not None and second is None
    assert other is not None and other.id == "run_b"
    assert first.lease_token != other.lease_token


@pytest.mark.asyncio
async def test_old_worker_cannot_complete_after_the_reaper() -> None:
    clock = _Clock()
    store = MemoryRunStore(clock)
    await store.insert(_run())
    reserved = await store.claim_run("run_lease", worker_id="worker-a", lease_seconds=30)
    assert reserved is not None and reserved.lease_token is not None
    active = await store.activate("run_lease", reserved.lease_token, lease_seconds=30)
    assert active is not None and active.lease_token is not None
    clock.advance(31)
    writer = EventWriter(store, InProcessRunBus(), None)
    count = await RunReaper(store, writer, batch_size=10, metrics=RunMetrics()).run_once()
    assert count == 1
    current = await store.get("run_lease")
    assert current is not None and current.status == RunStatus.INTERRUPTED
    with pytest.raises(LeaseLost):
        await store.append_event(
            "run_lease",
            "run_completed",
            {"duration_ms": 1},
            lease_token=active.lease_token,
        )
    again = await store.renew_lease("run_lease", active.lease_token, lease_seconds=30)
    assert again is False


@pytest.mark.asyncio
async def test_completion_wins_when_it_commits_before_the_reaper() -> None:
    clock = _Clock()
    store = MemoryRunStore(clock)
    await store.insert(_run())
    reserved = await store.claim_run("run_lease", worker_id="worker-a", lease_seconds=30)
    assert reserved is not None and reserved.lease_token
    active = await store.activate("run_lease", reserved.lease_token, lease_seconds=30)
    assert active is not None and active.lease_token
    await store.append_event("run_lease", "run_completed", {"duration_ms": 1}, lease_token=active.lease_token)
    clock.advance(31)
    count = await RunReaper(
        store,
        EventWriter(store, InProcessRunBus(), None),
        batch_size=10,
        metrics=RunMetrics(),
    ).run_once()
    assert count == 0
    current = await store.get("run_lease")
    assert current is not None and current.status == RunStatus.COMPLETED
    repeated = await store.append_event(
        "run_lease",
        "run_completed",
        {"duration_ms": 1},
        lease_token=active.lease_token,
    )
    page = await store.list_events("run_lease", after_sequence=0)
    assert page.events[-1].event_id == repeated.event_id
    assert [item.event_type for item in page.events].count("run_completed") == 1


@pytest.mark.asyncio
async def test_a_live_heartbeat_keeps_the_reaper_away() -> None:
    clock = _Clock()
    store = MemoryRunStore(clock)
    await store.insert(_run())
    reserved = await store.claim_run("run_lease", worker_id="worker-a", lease_seconds=10)
    assert reserved is not None and reserved.lease_token
    await store.activate("run_lease", reserved.lease_token, lease_seconds=10)
    clock.advance(11)
    assert await store.renew_lease("run_lease", reserved.lease_token, lease_seconds=10)
    count = await RunReaper(
        store,
        EventWriter(store, InProcessRunBus(), None),
        batch_size=5,
        metrics=RunMetrics(),
    ).run_once()
    assert count == 0


@pytest.mark.asyncio
async def test_cancel_and_complete_cannot_both_win() -> None:
    clock = _Clock()
    store = MemoryRunStore(clock)
    await store.insert(_run())
    reserved = await store.claim_run("run_lease", worker_id="worker-a", lease_seconds=30)
    assert reserved is not None and reserved.lease_token
    await store.activate("run_lease", reserved.lease_token, lease_seconds=30)
    await store.append_event("run_lease", "run_cancel_requested", {}, lease_token=reserved.lease_token)
    with pytest.raises(InvalidRunTransition):
        await store.append_event("run_lease", "run_completed", {}, lease_token=reserved.lease_token)
    current = await store.get("run_lease")
    assert current is not None and current.status == RunStatus.CANCELLING


@pytest.mark.asyncio
async def test_admission_is_global_and_released_by_the_worker() -> None:
    admission = LocalAdmission(max_active=1)
    user_id = uuid4()
    queue = LocalRunQueue()
    gate = asyncio.Event()
    current = 0
    peak = 0
    finished: list[str] = []

    async def execute(command):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await gate.wait()
        current -= 1
        finished.append(command.run_id or "")
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="ok",
            run_state=AgentRunState(run_id=command.run_id or "", status=AgentStatus.COMPLETED, final_response="ok"),
            conversation_id=uuid4(),
            workspace_id="ws",
        )

    config = RunExecutionConfig(
        heartbeat_seconds=0.05,
        lease_timeout_seconds=2,
        reaper_interval_seconds=30,
        shutdown_grace_seconds=1,
    )
    store = MemoryRunStore()
    first = RunCoordinator(store, InProcessRunBus(), queue, execute, admission=admission, config=config)
    second = RunCoordinator(store, InProcessRunBus(), queue, execute, admission=admission, config=config)
    await first.start()
    await second.start()
    try:
        await first.create_run(
            user_id=user_id,
            prompt="one",
            project_id=None,
            conversation_id=None,
            provider=None,
            model=None,
            idempotency_key="one",
        )
        await second.create_run(
            user_id=user_id,
            prompt="two",
            project_id=None,
            conversation_id=None,
            provider=None,
            model=None,
            idempotency_key="two",
        )
        for _ in range(40):
            if current == 1:
                break
            await asyncio.sleep(0.05)
        assert current == 1
        await asyncio.sleep(0.3)
        assert peak == 1
        gate.set()
        for _ in range(40):
            if len(finished) == 2 and admission.active() == 0:
                break
            await asyncio.sleep(0.05)
        assert finished and len(set(finished)) == 2
        assert peak == 1
        assert admission.active() == 0
    finally:
        gate.set()
        await first.stop()
        await second.stop()


@pytest.mark.asyncio
async def test_shutdown_does_not_mark_the_run_completed() -> None:
    blocked = asyncio.Event()

    async def execute(command):
        await blocked.wait()
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="ok",
            run_state=AgentRunState(run_id=command.run_id or "", status=AgentStatus.COMPLETED, final_response="ok"),
            conversation_id=uuid4(),
            workspace_id="ws",
        )

    config = RunExecutionConfig(
        heartbeat_seconds=0.05,
        lease_timeout_seconds=1,
        reaper_interval_seconds=30,
        shutdown_grace_seconds=0.05,
    )
    coordinator = RunCoordinator(MemoryRunStore(), InProcessRunBus(), LocalRunQueue(), execute, config=config)
    await coordinator.start()
    created = await coordinator.create_run(
        user_id=uuid4(),
        prompt="stop",
        project_id=None,
        conversation_id=None,
        provider=None,
        model=None,
        idempotency_key=None,
    )
    current = None
    for _ in range(40):
        current = await coordinator.store.get(created.id)
        if current is not None and current.status == RunStatus.RUNNING:
            break
        await asyncio.sleep(0.05)
    assert current is not None and current.status == RunStatus.RUNNING
    await coordinator.stop()
    current = await coordinator.store.get(created.id)
    assert current is not None and current.status == RunStatus.RUNNING


@pytest.mark.asyncio
async def test_denied_admission_keeps_the_run_queued() -> None:
    admission = LocalAdmission(1)
    await admission.acquire("held", "other", 30)

    async def execute(command):
        raise AssertionError("admission denied")

    coordinator = RunCoordinator(
        MemoryRunStore(),
        InProcessRunBus(),
        LocalRunQueue(),
        execute,
        admission=admission,
        config=RunExecutionConfig(heartbeat_seconds=0.05, lease_timeout_seconds=1, reaper_interval_seconds=30),
    )
    created = await coordinator.create_run(
        user_id=uuid4(),
        prompt="wait",
        project_id=None,
        conversation_id=None,
        provider=None,
        model=None,
        idempotency_key=None,
    )
    await coordinator._claim_and_execute(created.id)
    current = await coordinator.store.get(created.id)
    assert current is not None and current.status == RunStatus.QUEUED
    with pytest.raises(AdmissionDenied):
        await admission.acquire("another", "worker", 30)


@pytest.mark.asyncio
async def test_expired_reservation_can_be_claimed_by_another_worker() -> None:
    clock = _Clock()
    store = MemoryRunStore(clock)
    await store.insert(_run())
    first = await store.claim_run("run_lease", worker_id="worker-a", lease_seconds=10)
    assert first is not None
    clock.advance(11)
    second = await store.claim_next(worker_id="worker-b", lease_seconds=10)
    assert second is not None and second.worker_id == "worker-b"
    assert second.lease_token != first.lease_token
    assert second.status == RunStatus.QUEUED


class _FlakyAdmission:
    mode = "redis"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def acquire(self, run_id: str, worker_id: str, ttl_seconds: float) -> None:
        return None

    async def release(self, run_id: str, worker_id: str) -> None:
        return None

    async def renew(self, run_id: str, worker_id: str, ttl_seconds: float) -> bool:
        self.calls += 1
        if self.calls <= self.failures:
            raise AdmissionUnavailable()
        return True


def _result(run_id: str) -> ExecuteTaskResult:
    return ExecuteTaskResult(
        run_id=run_id,
        response="ok",
        run_state=AgentRunState(run_id=run_id, status=AgentStatus.COMPLETED, final_response="ok"),
        conversation_id=uuid4(),
        workspace_id="ws",
    )


@pytest.mark.asyncio
async def test_transient_heartbeat_errors_do_not_drop_the_lease() -> None:
    admission = _FlakyAdmission(failures=2)

    async def execute(command):
        await asyncio.sleep(0.8)
        return _result(command.run_id or "")

    coordinator = RunCoordinator(
        MemoryRunStore(),
        InProcessRunBus(),
        LocalRunQueue(),
        execute,
        admission=admission,
        config=RunExecutionConfig(
            heartbeat_seconds=0.05,
            lease_timeout_seconds=5,
            reaper_interval_seconds=30,
            shutdown_grace_seconds=2,
        ),
    )
    await coordinator.start()
    try:
        created = await coordinator.create_run(
            user_id=uuid4(),
            prompt="retry",
            project_id=None,
            conversation_id=None,
            provider=None,
            model=None,
            idempotency_key=None,
        )
        for _ in range(40):
            current = await coordinator.store.get(created.id)
            if current is not None and current.status == RunStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)
        current = await coordinator.store.get(created.id)
        assert current is not None and current.status == RunStatus.COMPLETED
        assert admission.calls >= 2
    finally:
        await coordinator.stop()


@pytest.mark.asyncio
async def test_sustained_admission_loss_does_not_complete_the_run() -> None:
    async def execute(command):
        await asyncio.sleep(1.2)
        return _result(command.run_id or "")

    coordinator = RunCoordinator(
        MemoryRunStore(),
        InProcessRunBus(),
        LocalRunQueue(),
        execute,
        admission=_FlakyAdmission(failures=99),
        config=RunExecutionConfig(
            heartbeat_seconds=0.05,
            lease_timeout_seconds=5,
            reaper_interval_seconds=30,
            shutdown_grace_seconds=0.2,
        ),
    )
    await coordinator.start()
    try:
        created = await coordinator.create_run(
            user_id=uuid4(),
            prompt="down",
            project_id=None,
            conversation_id=None,
            provider=None,
            model=None,
            idempotency_key=None,
        )
        await asyncio.sleep(1.0)
        current = await coordinator.store.get(created.id)
        assert current is not None and current.status == RunStatus.RUNNING
        page = await coordinator.store.list_events(created.id, after_sequence=0)
        assert "run_completed" not in [item.event_type for item in page.events]
    finally:
        await coordinator.stop()

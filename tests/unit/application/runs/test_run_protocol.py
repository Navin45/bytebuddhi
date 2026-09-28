"""Durable run sequencing, replay, and live delivery."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.runs.bus import InProcessRunBus
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.errors import IdempotencyConflict, InvalidEventCursor, RunAlreadyCompleted
from app.application.runs.sequence import SequenceGap, SequenceTracker
from app.application.runs.status import InvalidRunTransition, RunStatus
from app.application.runs.store import MemoryRunStore
from app.application.runs.writer import EventWriter
from app.application.use_cases.agent.execute_task import ExecuteTaskResult


def test_sequence_tracker_rejects_gaps_and_ignores_duplicates() -> None:
    tracker = SequenceTracker()
    assert tracker.observe(1) == "applied"
    assert tracker.observe(1) == "duplicate"
    with pytest.raises(SequenceGap) as exc:
        tracker.observe(3)
    assert exc.value.expected == 2
    tracker.observe(2)
    assert tracker.last_sequence == 2


@pytest.mark.asyncio
async def test_event_sequence_starts_at_one_and_is_unique_under_concurrency() -> None:
    store = MemoryRunStore()
    user_id = uuid4()
    from app.application.runs.records import RunRecord

    await store.insert(
        RunRecord(
            id="run_concurrent",
            user_id=user_id,
            project_id=None,
            conversation_id=None,
            status=RunStatus.QUEUED,
            prompt="hello",
            prompt_sha256="abc",
        )
    )

    async def write(index: int) -> int:
        event = await store.append_event("run_concurrent", "assistant_delta", {"delta": str(index)})
        return event.sequence

    sequences = await asyncio.gather(*(write(index) for index in range(20)))
    assert sorted(sequences) == list(range(1, 21))
    page = await store.list_events("run_concurrent", after_sequence=0)
    assert page.events[0].sequence == 1
    assert page.events[0].schema_version == 1
    caught = await store.list_events("run_concurrent", after_sequence=18)
    assert [item.sequence for item in caught.events] == [19, 20]
    empty = await store.list_events("run_concurrent", after_sequence=20)
    assert empty.events == ()
    assert empty.has_more is False
    with pytest.raises(ValueError):
        await store.list_events("run_concurrent", after_sequence=-1)


@pytest.mark.asyncio
async def test_terminal_transition_is_rejected_after_completion() -> None:
    store = MemoryRunStore()
    user_id = uuid4()
    from app.application.runs.records import RunRecord

    await store.insert(
        RunRecord(
            id="run_done",
            user_id=user_id,
            project_id=None,
            conversation_id=None,
            status=RunStatus.QUEUED,
            prompt="hello",
            prompt_sha256="abc",
        )
    )
    await store.append_event("run_done", "run_started", {})
    await store.append_event("run_done", "run_completed", {"duration_ms": 1})
    with pytest.raises(InvalidRunTransition):
        await store.append_event("run_done", "run_started", {})


@pytest.mark.asyncio
async def test_redis_notification_failure_keeps_the_event() -> None:
    store = MemoryRunStore()
    bus = InProcessRunBus()

    class _Boom:
        async def publish(self, event) -> None:
            raise ConnectionError("redis down")

    writer = EventWriter(store, bus, _Boom())
    user_id = uuid4()
    from app.application.runs.records import RunRecord

    await store.insert(
        RunRecord(
            id="run_redis",
            user_id=user_id,
            project_id=None,
            conversation_id=None,
            status=RunStatus.QUEUED,
            prompt="hello",
            prompt_sha256="abc",
        )
    )
    event = await writer.append("run_redis", "run_queued", {})
    page = await store.list_events("run_redis", after_sequence=0)
    assert page.events[0].event_id == event.event_id
    assert page.events[0].sequence == 1


@pytest.mark.asyncio
async def test_slow_subscriber_is_marked_and_events_remain() -> None:
    store = MemoryRunStore()
    bus = InProcessRunBus(maxsize=1)
    writer = EventWriter(store, bus, None)
    user_id = uuid4()
    from app.application.runs.records import RunRecord

    await store.insert(
        RunRecord(
            id="run_slow",
            user_id=user_id,
            project_id=None,
            conversation_id=None,
            status=RunStatus.RUNNING,
            prompt="hello",
            prompt_sha256="abc",
        )
    )
    subscription = bus.subscribe("run_slow")
    await writer.append("run_slow", "assistant_delta", {"delta": "a"})
    await writer.append("run_slow", "assistant_delta", {"delta": "b"})
    assert subscription.overflowed is True
    page = await store.list_events("run_slow", after_sequence=0)
    assert len(page.events) == 2


@pytest.mark.asyncio
async def test_cancel_requested_is_distinct_from_cancelled() -> None:
    user_id = uuid4()

    async def execute(command):
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="",
            run_state=AgentRunState(run_id=command.run_id or "", status=AgentStatus.CANCELLED),
            conversation_id=uuid4(),
            workspace_id="ws",
        )

    coordinator = RunCoordinator(MemoryRunStore(), InProcessRunBus(), LocalRunQueue(), execute)
    created = await coordinator.create_run(
        user_id=user_id,
        prompt="stop me",
        project_id=None,
        conversation_id=None,
        provider=None,
        model=None,
        idempotency_key="cancel-key",
    )
    cancelled = await coordinator.cancel(created.id, user_id)
    types = [
        item.event_type
        for item in (await coordinator.list_events(created.id, user_id, after_sequence=0, limit=20)).events
    ]
    assert cancelled.status == RunStatus.CANCELLED
    assert types.count("run_cancel_requested") == 1
    assert types.count("run_cancelled") == 1
    again = await coordinator.cancel(created.id, user_id)
    assert again.status == RunStatus.CANCELLED
    types_again = [
        item.event_type
        for item in (await coordinator.list_events(created.id, user_id, after_sequence=0, limit=20)).events
    ]
    assert types_again.count("run_cancelled") == 1


@pytest.mark.asyncio
async def test_completed_run_cannot_be_cancelled() -> None:
    user_id = uuid4()

    async def execute(command):
        return ExecuteTaskResult(
            run_id=command.run_id or "",
            response="ok",
            run_state=AgentRunState(run_id=command.run_id or "", status=AgentStatus.COMPLETED, final_response="ok"),
            conversation_id=uuid4(),
            workspace_id="ws",
        )

    coordinator = RunCoordinator(MemoryRunStore(), InProcessRunBus(), LocalRunQueue(), execute)
    await coordinator.start()
    try:
        created = await coordinator.create_run(
            user_id=user_id,
            prompt="finish",
            project_id=None,
            conversation_id=None,
            provider=None,
            model=None,
            idempotency_key="finish-key",
        )
        for _ in range(50):
            current = await coordinator.get_run(created.id, user_id)
            if current.status == RunStatus.COMPLETED:
                break
            await asyncio.sleep(0.02)
        with pytest.raises(RunAlreadyCompleted):
            await coordinator.cancel(created.id, user_id)
        with pytest.raises(IdempotencyConflict):
            await coordinator.create_run(
                user_id=user_id,
                prompt="other",
                project_id=None,
                conversation_id=None,
                provider=None,
                model=None,
                idempotency_key="finish-key",
            )
        with pytest.raises(InvalidEventCursor):
            await coordinator.list_events(created.id, user_id, after_sequence=-1, limit=10)
    finally:
        await coordinator.stop()

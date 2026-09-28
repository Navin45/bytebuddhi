"""WebSocket auth, ownership, replay cursor, and slow-client disconnect."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import WebSocket

from app.application.runs.bus import InProcessRunBus
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.records import RunEventRecord
from app.application.runs.store import MemoryRunStore
from app.interfaces.api.routes.runs import get_websocket_user
from app.interfaces.api.run_stream import SLOW_CLIENT_CODE, serve_run_stream


def _coordinator() -> RunCoordinator:
    async def execute(_command):
        raise AssertionError("this test does not execute a run")

    return RunCoordinator(MemoryRunStore(), InProcessRunBus(maxsize=1), LocalRunQueue(), execute)


async def _create(coordinator: RunCoordinator, user_id):
    return await coordinator.create_run(
        user_id=user_id,
        prompt="hello",
        project_id=None,
        conversation_id=None,
        provider=None,
        model=None,
        idempotency_key=str(uuid4()),
    )


@pytest.mark.asyncio
async def test_websocket_auth_uses_the_bearer_token_and_hides_it() -> None:
    class _Socket:
        headers = {"authorization": "Bearer not-a-token"}

    repo = AsyncMock()
    assert await get_websocket_user(cast(WebSocket, _Socket()), repo) is None
    repo.get_by_id.assert_not_awaited()

    class _Missing:
        headers: dict[str, str] = {}

    assert await get_websocket_user(cast(WebSocket, _Missing()), repo) is None


@pytest.mark.asyncio
async def test_websocket_hides_another_users_run() -> None:
    coordinator = _coordinator()
    owner = uuid4()
    created = await _create(coordinator, owner)
    socket = _FakeSocket()
    await serve_run_stream(socket, coordinator, run_id=created.id, user_id=uuid4(), after_sequence=0)
    assert socket.closed == 4404
    assert created.id not in str(socket.sent)


@pytest.mark.asyncio
async def test_invalid_cursor_closes_without_events() -> None:
    coordinator = _coordinator()
    owner = uuid4()
    created = await _create(coordinator, owner)
    socket = _FakeSocket()
    await serve_run_stream(socket, coordinator, run_id=created.id, user_id=owner, after_sequence=-1)
    assert socket.closed == 1008
    assert socket.sent == []


@pytest.mark.asyncio
async def test_replay_is_strictly_after_the_cursor() -> None:
    coordinator = _coordinator()
    owner = uuid4()
    created = await _create(coordinator, owner)
    await coordinator.writer.append(created.id, "run_started", {})
    socket = _FakeSocket()
    task = asyncio.create_task(
        serve_run_stream(
            socket, coordinator, run_id=created.id, user_id=owner, after_sequence=1, keepalive_seconds=0.05
        )
    )
    for _ in range(50):
        if any(item.get("sequence") == 2 for item in socket.sent):
            break
        await asyncio.sleep(0.01)
    await coordinator.writer.append(created.id, "run_cancelled", {"error_code": "RUN_CANCELLED"})
    await task
    sequences = [item["sequence"] for item in socket.sent if "sequence" in item]
    assert 1 not in sequences
    assert sequences[0] == 2
    assert sequences == sorted(sequences)
    assert socket.closed == 1000


@pytest.mark.asyncio
async def test_slow_client_is_disconnected_and_events_remain() -> None:
    coordinator = _coordinator()
    owner = uuid4()
    created = await _create(coordinator, owner)
    socket = _BlockingSocket()
    task = asyncio.create_task(
        serve_run_stream(socket, coordinator, run_id=created.id, user_id=owner, after_sequence=0)
    )
    await socket.started.wait()
    await coordinator.writer.append(created.id, "assistant_delta", {"delta": "a"})
    await coordinator.writer.append(created.id, "assistant_delta", {"delta": "b"})
    socket.release.set()
    await task
    assert socket.closed == SLOW_CLIENT_CODE
    page = await coordinator.list_events(created.id, owner, after_sequence=0, limit=20)
    assert [item.event_type for item in page.events] == ["run_queued", "assistant_delta", "assistant_delta"]


@pytest.mark.asyncio
async def test_live_delivery_does_not_skip_ahead() -> None:
    coordinator = _coordinator()
    owner = uuid4()
    created = await _create(coordinator, owner)
    socket = _FakeSocket()
    task = asyncio.create_task(
        serve_run_stream(
            socket, coordinator, run_id=created.id, user_id=owner, after_sequence=0, keepalive_seconds=0.05
        )
    )
    for _ in range(50):
        if socket.sent:
            break
        await asyncio.sleep(0.01)
    coordinator.bus.publish(
        RunEventRecord(
            event_id="evt_gap",
            run_id=created.id,
            sequence=9,
            event_type="assistant_delta",
            schema_version=1,
            payload={"delta": "skip"},
            created_at=datetime.now(UTC),
        )
    )
    await coordinator.writer.append(created.id, "run_cancelled", {"error_code": "RUN_CANCELLED"})
    await task
    sequences = [item["sequence"] for item in socket.sent if "sequence" in item]
    assert sequences == [1, 2]
    assert all(item.get("data", {}).get("delta") != "skip" for item in socket.sent)


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: int | None = None

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = code


class _BlockingSocket(_FakeSocket):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._blocked = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)
        if not self._blocked:
            self._blocked = True
            self.started.set()
            await self.release.wait()

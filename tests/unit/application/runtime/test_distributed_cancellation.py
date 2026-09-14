"""Distributed cancellation via an optional shared store."""

import asyncio
from uuid import uuid4

import pytest

from app.application.runtime.cancellation import CancellationToken, RunCancellationRegistry


class FakeStore:
    def __init__(self) -> None:
        self.runs: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    async def put_run(self, run_id: str, user_id: str, ttl_seconds: int) -> None:
        self.runs[run_id] = user_id

    async def get_owner(self, run_id: str) -> str | None:
        return self.runs.get(run_id)

    async def delete_run(self, run_id: str) -> None:
        self.runs.pop(run_id, None)

    async def publish_cancel(self, run_id: str, user_id: str) -> None:
        self.published.append((run_id, user_id))
        await self._queue.put((run_id, user_id))

    async def listen_cancels(self):
        while True:
            yield await self._queue.get()


@pytest.mark.asyncio
async def test_cancel_on_non_owning_worker_reaches_owner() -> None:
    store = FakeStore()
    owner_reg = RunCancellationRegistry(store=store)
    other_reg = RunCancellationRegistry(store=store)
    user = uuid4()
    token = CancellationToken()
    await owner_reg.register("run_dist", user, token)
    await owner_reg.start_listener()
    try:
        accepted = await other_reg.request_cancel("run_dist", user)
        assert accepted is True
        await asyncio.sleep(0.05)
        assert token.is_cancelled() is True
        assert store.published == [("run_dist", str(user))]
    finally:
        await owner_reg.stop_listener()
        await owner_reg.release("run_dist")


@pytest.mark.asyncio
async def test_distributed_cancel_unknown_run_is_false() -> None:
    store = FakeStore()
    registry = RunCancellationRegistry(store=store)
    assert await registry.request_cancel("missing", uuid4()) is False


@pytest.mark.asyncio
async def test_cancel_all_local_on_shutdown() -> None:
    registry = RunCancellationRegistry()
    token = CancellationToken()
    await registry.register("run_sd", uuid4(), token)
    count = await registry.cancel_all_local()
    assert count == 1
    assert token.is_cancelled() is True

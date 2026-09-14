"""Shared cooperative cancellation for API, CLI, and VS Code clients.

In-process CancellationToken is canonical. An optional CancellationStore
(Redis) fans a cancel request to the worker that owns the run.

Identity authorization is the trusted user id passed by the caller.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


class CancellationToken:
    """Cooperative cancellation flag wrapping asyncio.Event."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def event(self) -> asyncio.Event:
        return self._event


@runtime_checkable
class CancellationStore(Protocol):
    """Optional shared coordination (typically Redis)."""

    async def put_run(self, run_id: str, user_id: str, ttl_seconds: int) -> None: ...

    async def get_owner(self, run_id: str) -> str | None: ...

    async def delete_run(self, run_id: str) -> None: ...

    async def publish_cancel(self, run_id: str, user_id: str) -> None: ...

    def listen_cancels(self) -> AsyncIterator[tuple[str, str]]: ...


@dataclass
class _RegisteredRun:
    user_id: UUID
    token: CancellationToken
    task: asyncio.Task[Any] | None = None


class RunCancellationRegistry:
    """Maps run_id to a cancellation token owned by a trusted user.

    Local map is always used. When a CancellationStore is attached, cancel
    requests are published so another API worker can honour them.
    """

    def __init__(self, store: CancellationStore | None = None, run_ttl_seconds: int = 7200) -> None:
        self._runs: dict[str, _RegisteredRun] = {}
        self._lock = asyncio.Lock()
        self._store = store
        self._run_ttl_seconds = run_ttl_seconds
        self._listener: asyncio.Task[None] | None = None

    def attach_store(self, store: CancellationStore | None) -> None:
        self._store = store

    async def start_listener(self) -> None:
        if self._store is None or self._listener is not None:
            return
        self._listener = asyncio.create_task(self._listen_loop(), name="cancel-listener")

    async def stop_listener(self) -> None:
        if self._listener is not None and not self._listener.done():
            self._listener.cancel()
            with suppress(asyncio.CancelledError):
                await self._listener
        self._listener = None

    async def register(self, run_id: str, user_id: UUID, token: CancellationToken) -> None:
        async with self._lock:
            self._runs[run_id] = _RegisteredRun(user_id=user_id, token=token)
        if self._store is not None:
            with suppress(Exception):
                await self._store.put_run(run_id, str(user_id), self._run_ttl_seconds)

    async def bind_task(self, run_id: str, task: asyncio.Task[Any]) -> None:
        async with self._lock:
            registered = self._runs.get(run_id)
            if registered is not None:
                registered.task = task

    async def request_cancel(self, run_id: str, user_id: UUID) -> bool:
        """Signal cancellation if the run exists and belongs to user_id.

        Returns False when the run is unknown or owned by someone else.
        Does not distinguish those cases to the caller (no oracle).
        """
        accepted = False
        async with self._lock:
            registered = self._runs.get(run_id)
            if registered is not None and registered.user_id == user_id:
                registered.token.cancel()
                if registered.task is not None and not registered.task.done():
                    registered.task.cancel()
                accepted = True
        if accepted:
            if self._store is not None:
                with suppress(Exception):
                    await self._store.publish_cancel(run_id, str(user_id))
            return True
        if self._store is None:
            return False
        try:
            owner = await self._store.get_owner(run_id)
        except Exception:
            return False
        if owner != str(user_id):
            return False
        await self._store.publish_cancel(run_id, str(user_id))
        return True

    async def release(self, run_id: str) -> None:
        async with self._lock:
            self._runs.pop(run_id, None)
        if self._store is not None:
            with suppress(Exception):
                await self._store.delete_run(run_id)

    async def cancel_all_local(self) -> int:
        """Shutdown helper: cancel every run owned by this process."""
        async with self._lock:
            items = list(self._runs.items())
        for _run_id, registered in items:
            registered.token.cancel()
            if registered.task is not None and not registered.task.done():
                registered.task.cancel()
        return len(items)

    async def _listen_loop(self) -> None:
        if self._store is None:
            return
        try:
            async for run_id, user_id in self._store.listen_cancels():
                try:
                    owner = UUID(user_id)
                except ValueError:
                    continue
                async with self._lock:
                    registered = self._runs.get(run_id)
                    if registered is None or registered.user_id != owner:
                        continue
                    registered.token.cancel()
                    if registered.task is not None and not registered.task.done():
                        registered.task.cancel()
        except asyncio.CancelledError:
            raise
        except Exception:
            return


_registry = RunCancellationRegistry()


def get_run_cancellation_registry() -> RunCancellationRegistry:
    """Registry used by the API cancel endpoint, chat handler, and shutdown."""
    return _registry


def reset_run_cancellation_registry() -> RunCancellationRegistry:
    """Test helper to replace in-flight run tracking."""
    global _registry
    _registry = RunCancellationRegistry()
    return _registry

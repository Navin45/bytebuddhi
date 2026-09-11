"""Shared cooperative cancellation for API, CLI, and VS Code clients.

Process-local, like the API rate limiter. Not a distributed lock. Identity
authorization for cancel requests is enforced by the caller (JWT user id).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
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


@dataclass
class _RegisteredRun:
    user_id: UUID
    token: CancellationToken
    task: asyncio.Task[Any] | None = None


class RunCancellationRegistry:
    """Maps run_id to a cancellation token owned by a trusted user."""

    def __init__(self) -> None:
        self._runs: dict[str, _RegisteredRun] = {}
        self._lock = asyncio.Lock()

    async def register(self, run_id: str, user_id: UUID, token: CancellationToken) -> None:
        async with self._lock:
            self._runs[run_id] = _RegisteredRun(user_id=user_id, token=token)

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
        async with self._lock:
            registered = self._runs.get(run_id)
            if registered is None or registered.user_id != user_id:
                return False
            registered.token.cancel()
            if registered.task is not None and not registered.task.done():
                registered.task.cancel()
            return True

    async def release(self, run_id: str) -> None:
        async with self._lock:
            self._runs.pop(run_id, None)


_registry = RunCancellationRegistry()


def get_run_cancellation_registry() -> RunCancellationRegistry:
    """Process-local registry used by the API cancel endpoint and chat handler."""
    return _registry


def reset_run_cancellation_registry() -> RunCancellationRegistry:
    """Test helper to replace in-flight run tracking."""
    global _registry
    _registry = RunCancellationRegistry()
    return _registry

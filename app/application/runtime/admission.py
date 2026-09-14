"""Per-user concurrent run admission. Process-local, like rate limiting."""

from __future__ import annotations

import asyncio
from uuid import UUID


class ConcurrentRunLimitExceeded(Exception):
    """Raised when a principal already has the maximum in-flight runs."""


class RunAdmissionController:
    """Fairness limiter: one user cannot occupy every worker slot."""

    def __init__(self, max_per_user: int = 4) -> None:
        if max_per_user < 1:
            raise ValueError("max_per_user must be >= 1")
        self.max_per_user = max_per_user
        self._counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: UUID | str) -> None:
        key = str(user_id)
        async with self._lock:
            current = self._counts.get(key, 0)
            if current >= self.max_per_user:
                raise ConcurrentRunLimitExceeded(f"User already has {current} active runs (limit {self.max_per_user})")
            self._counts[key] = current + 1

    async def release(self, user_id: UUID | str) -> None:
        key = str(user_id)
        async with self._lock:
            current = self._counts.get(key, 0)
            if current <= 1:
                self._counts.pop(key, None)
            else:
                self._counts[key] = current - 1

    def active_for(self, user_id: UUID | str) -> int:
        return self._counts.get(str(user_id), 0)


_controller = RunAdmissionController()


def get_run_admission_controller() -> RunAdmissionController:
    return _controller


def reset_run_admission_controller(max_per_user: int = 4) -> RunAdmissionController:
    global _controller
    _controller = RunAdmissionController(max_per_user=max_per_user)
    return _controller

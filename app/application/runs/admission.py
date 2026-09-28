"""Global run admission. The executing worker owns the slot, not the HTTP request."""

from __future__ import annotations

import asyncio
from typing import Protocol


class AdmissionDenied(Exception):
    """The global active-run limit is full."""


class AdmissionUnavailable(Exception):
    """Admission cannot be decided. Callers must not execute the run."""


class RunAdmission(Protocol):
    mode: str

    async def acquire(self, run_id: str, worker_id: str, ttl_seconds: float) -> None: ...

    async def release(self, run_id: str, worker_id: str) -> None: ...

    async def renew(self, run_id: str, worker_id: str, ttl_seconds: float) -> bool: ...


class UnlimitedAdmission:
    """Tests and single-process paths that do not configure a limit."""

    mode = "unlimited"

    async def acquire(self, run_id: str, worker_id: str, ttl_seconds: float) -> None:
        return None

    async def release(self, run_id: str, worker_id: str) -> None:
        return None

    async def renew(self, run_id: str, worker_id: str, ttl_seconds: float) -> bool:
        return True


class LocalAdmission:
    """Process-local global limit. Multi-worker deployments use Redis instead."""

    mode = "local"

    def __init__(self, max_active: int) -> None:
        if max_active < 1:
            raise ValueError("max_active must be >= 1")
        self.max_active = max_active
        self._slots: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, run_id: str, worker_id: str, ttl_seconds: float) -> None:
        del ttl_seconds
        async with self._lock:
            owner = self._slots.get(run_id)
            if owner == worker_id:
                return
            if owner is not None:
                raise AdmissionDenied()
            if len(self._slots) >= self.max_active:
                raise AdmissionDenied()
            self._slots[run_id] = worker_id

    async def release(self, run_id: str, worker_id: str) -> None:
        async with self._lock:
            if self._slots.get(run_id) == worker_id:
                self._slots.pop(run_id, None)

    async def renew(self, run_id: str, worker_id: str, ttl_seconds: float) -> bool:
        del ttl_seconds
        async with self._lock:
            return self._slots.get(run_id) == worker_id

    def active(self) -> int:
        return len(self._slots)

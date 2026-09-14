"""In-process OAuth state store for single-worker deployments."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import TypeVar

from app.application.ports.output.auth.oauth_state_store import OAuthStateRecord, OAuthStateStore

_MAX_ENTRIES = 4096
_T = TypeVar("_T")


class MemoryOAuthStateStore(OAuthStateStore):
    """Bounded, TTL, single-use in-memory tickets. Not shared across workers."""

    def __init__(self, *, max_entries: int = _MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._lock = asyncio.Lock()
        self._states: OrderedDict[str, tuple[float, OAuthStateRecord]] = OrderedDict()
        self._exchanges: OrderedDict[str, tuple[float, str]] = OrderedDict()

    async def put_state(self, state: str, record: OAuthStateRecord, ttl_seconds: int) -> None:
        async with self._lock:
            self._purge_locked()
            self._states[state] = (time.monotonic() + ttl_seconds, record)
            self._states.move_to_end(state)
            self._trim_locked(self._states)

    async def consume_state(self, state: str) -> OAuthStateRecord | None:
        async with self._lock:
            self._purge_locked()
            item = self._states.pop(state, None)
            if item is None:
                return None
            expires_at, record = item
            if expires_at < time.monotonic():
                return None
            return record

    async def put_exchange(self, code: str, user_id: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._purge_locked()
            self._exchanges[code] = (time.monotonic() + ttl_seconds, user_id)
            self._exchanges.move_to_end(code)
            self._trim_locked(self._exchanges)

    async def consume_exchange(self, code: str) -> str | None:
        async with self._lock:
            self._purge_locked()
            item = self._exchanges.pop(code, None)
            if item is None:
                return None
            expires_at, user_id = item
            if expires_at < time.monotonic():
                return None
            return user_id

    def _purge_locked(self) -> None:
        now = time.monotonic()
        for store in (self._states, self._exchanges):
            expired = [key for key, (expires_at, _) in store.items() if expires_at < now]
            for key in expired:
                store.pop(key, None)

    def _trim_locked(self, store: OrderedDict[str, _T]) -> None:
        while len(store) > self._max_entries:
            store.popitem(last=False)

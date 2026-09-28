"""Session-level advisory lock so only one process reaps stale runs."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

_LOCK_KEY = 872341


class PostgresReaperLock:
    """Holds one pooled connection for the life of the lock.

    A commit that returns the connection to the pool would either drop the
    lock or let the next checkout observe it as already held.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._connection: AsyncConnection | None = None
        self._held = False

    async def try_acquire(self) -> bool:
        if self._held:
            return True
        connection = await self._engine().connect()
        try:
            locked = bool(
                (await connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_KEY})).scalar()
            )
        except Exception:
            await connection.close()
            raise
        if not locked:
            await connection.close()
            return False
        self._connection = connection
        self._held = True
        return True

    async def release(self) -> None:
        connection = self._connection
        self._connection = None
        self._held = False
        if connection is None:
            return
        try:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_KEY})
        finally:
            await connection.close()

    def _engine(self) -> AsyncEngine:
        bind = self._sessions.kw["bind"]
        if not isinstance(bind, AsyncEngine):
            raise RuntimeError("reaper lock requires an async engine")
        return bind

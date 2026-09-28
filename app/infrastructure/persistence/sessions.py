"""Session dependency selected by profile. Business logic does not branch on the database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.infrastructure.config.profile import is_standalone


async def get_db() -> AsyncIterator[Any]:
    if is_standalone():
        from app.infrastructure.persistence.sqlite.database import open_session

        yield open_session()
        return
    from app.infrastructure.persistence.postgres.database import get_db as postgres_get_db

    async for session in postgres_get_db():
        yield session

"""CLI composition-root lifecycle. The only CLI module allowed to import infrastructure."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TextIO

from sqlalchemy import text

from app.interfaces.cli.app import CliApp
from app.interfaces.cli.errors import CliError
from app.interfaces.cli.exit_codes import ExitCode


@asynccontextmanager
async def cli_session(
    *,
    include_runtime: bool,
    debug: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> AsyncIterator[CliApp]:
    """Open application resources, yield a CliApp, then shut down cleanly."""
    from app.infrastructure.config.logger import setup_logging
    from app.infrastructure.config.settings import settings
    from app.infrastructure.persistence.postgres.database import AsyncSessionLocal, close_db

    setup_logging(stream=sys.stderr, level="DEBUG" if debug else None)
    try:
        settings.validate_runtime_configuration()
        settings.validate_model_settings()
    except RuntimeError as exc:
        raise CliError(str(exc), ExitCode.CONFIG_FAILURE) from exc

    redis_started = False
    try:
        from app.infrastructure.persistence.redis.client import get_redis_client

        await get_redis_client()
        redis_started = True
    except Exception:
        redis_started = False

    session = AsyncSessionLocal()
    graph = None
    try:
        if include_runtime:
            from app.interfaces.composition import compose_application_graph

            graph = compose_application_graph(session)
        else:
            from app.interfaces.composition import compose_identity_services

            graph = compose_identity_services(session)

        async def _health() -> dict[str, Any]:
            try:
                await session.execute(text("SELECT 1"))
                return {
                    "status": "healthy",
                    "service": "bytebuddhi-cli",
                    "database": "connected",
                }
            except Exception:
                return {
                    "status": "unhealthy",
                    "service": "bytebuddhi-cli",
                    "database": "disconnected",
                }

        yield CliApp(
            execute_task=graph.execute_task,
            list_projects=graph.list_projects,
            get_project=graph.get_project,
            resolve_local_project=graph.resolve_local_project,
            user_repository=graph.user_repository,
            health_check=_health,
            model_catalog=graph.model_catalog,
            stdout=stdout,
            stderr=stderr,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
        if graph is not None:
            await graph.aclose()
        try:
            from app.infrastructure.web.lifecycle import close_web_research_resources

            await close_web_research_resources()
        except Exception:
            pass
        if redis_started:
            try:
                from app.infrastructure.persistence.redis.client import close_redis_client

                await close_redis_client()
            except Exception:
                pass
        await close_db()

"""Health check routes: liveness vs readiness."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app._version import MIN_PROTOCOL_VERSION, PROTOCOL_VERSION
from app.infrastructure.config.profile import is_standalone
from app.infrastructure.config.settings import settings

router = APIRouter()


@router.get("/health")
@router.get("/health/live")
async def liveness():
    """Process is up. Does not probe PostgreSQL or Redis."""
    return {
        "status": "ok",
        "service": "ByteBuddhi API",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "min_protocol_version": MIN_PROTOCOL_VERSION,
    }


@router.get("/health/ready")
async def readiness():
    """Required dependencies for serving traffic."""
    checks: dict[str, str] = {}
    healthy = True
    if is_standalone():
        from app.infrastructure.config.profile import sqlite_database_path
        from app.infrastructure.persistence.sqlite.database import integrity_report

        report = integrity_report(sqlite_database_path())
        checks["database"] = "sqlite" if report in {"ok", "not_initialized"} else "unavailable"
        checks["redis"] = "not_required"
        if checks["database"] == "unavailable":
            healthy = False
    else:
        try:
            from app.infrastructure.persistence.postgres.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "postgres"
        except Exception:
            checks["database"] = "unavailable"
            healthy = False

    if not is_standalone() and settings.uses_redis_coordination:
        try:
            from app.infrastructure.persistence.redis.client import get_redis_client

            client = await get_redis_client()
            await client.ping()
            checks["redis"] = "ready"
        except Exception:
            checks["redis"] = "unavailable"
            healthy = False
    elif not is_standalone():
        checks["redis"] = "optional"

    from app.interfaces.api.run_runtime import execution_health

    checks.update(execution_health())
    if (
        checks.get("execution") == "unavailable"
        or checks.get("database") == "unavailable"
        or checks.get("redis") == "unavailable"
    ):
        healthy = False

    body = {"status": "ready" if healthy else "not_ready", "checks": checks}
    if not healthy:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)
    return body


@router.get("/health/db")
async def health_check_db():
    """Database connectivity. Returns 503 when unavailable."""
    try:
        if is_standalone():
            from app.infrastructure.config.profile import sqlite_database_path
            from app.infrastructure.persistence.sqlite.database import integrity_report

            report = integrity_report(sqlite_database_path())
            if report not in {"ok", "not_initialized"}:
                raise RuntimeError(report)
            return {"status": "healthy", "database": "sqlite"}
        from app.infrastructure.persistence.postgres.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "postgres"}
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "disconnected"},
        )

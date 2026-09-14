"""Health check routes: liveness vs readiness."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.infrastructure.config.settings import settings
from app.infrastructure.persistence.postgres.database import AsyncSessionLocal

router = APIRouter()


@router.get("/health")
@router.get("/health/live")
async def liveness():
    """Process is up. Does not probe PostgreSQL or Redis."""
    return {
        "status": "ok",
        "service": "ByteBuddhi API",
        "version": __version__,
    }


@router.get("/health/ready")
async def readiness():
    """Required dependencies for serving traffic."""
    checks: dict[str, str] = {}
    healthy = True
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
        healthy = False

    if settings.uses_redis_coordination:
        try:
            from app.infrastructure.persistence.redis.client import get_redis_client

            client = await get_redis_client()
            await client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
            healthy = False
    else:
        checks["redis"] = "optional"

    body = {"status": "ready" if healthy else "not_ready", "checks": checks}
    if not healthy:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)
    return body


@router.get("/health/db")
async def health_check_db():
    """Database connectivity. Returns 503 when unavailable."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "disconnected"},
        )

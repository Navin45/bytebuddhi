"""FastAPI main application."""

from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.infrastructure.config.logger import get_logger, setup_logging
from app.infrastructure.config.settings import settings
from app.infrastructure.persistence.postgres.database import close_db, init_db
from app.interfaces.api.middleware.error_handler import error_handler_middleware
from app.interfaces.api.middleware.rate_limiter import RateLimitMiddleware
from app.interfaces.api.middleware.request_limit import RequestSizeLimitMiddleware
from app.interfaces.api.middleware.security_headers import SecurityHeadersMiddleware
from app.interfaces.api.routes import agent, auth, chat, files, health, models, oauth, projects

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Handles startup and shutdown tasks including database
    and Redis connection initialization and cleanup.
    """
    logger.info("Starting ByteBuddhi API", env=settings.app_env)
    settings.validate_runtime_configuration()
    settings.validate_model_settings()

    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise

    try:
        from app.infrastructure.persistence.redis.client import get_redis_client

        client = await get_redis_client()
        logger.info("Redis initialized successfully")
        if settings.uses_redis_coordination:
            from app.application.runtime.cancellation import get_run_cancellation_registry
            from app.infrastructure.persistence.redis.cancellation_store import RedisCancellationStore

            registry = get_run_cancellation_registry()
            registry.attach_store(RedisCancellationStore(client))
            await registry.start_listener()
            logger.info("Distributed cancellation listener started")
        from app.infrastructure.auth.oauth.redis_state_store import RedisOAuthStateStore
        from app.infrastructure.auth.oauth.state import attach_oauth_state_store

        attach_oauth_state_store(RedisOAuthStateStore(client))
        logger.info("OAuth state store using Redis")
    except Exception as e:
        logger.error("Failed to initialize Redis", error=str(e))
        if settings.uses_redis_coordination:
            raise

    yield

    logger.info("Shutting down ByteBuddhi API")
    from app.application.runtime.cancellation import get_run_cancellation_registry

    registry = get_run_cancellation_registry()
    with suppress(Exception):
        cancelled = await registry.cancel_all_local()
        logger.info("Cancelled local runs on shutdown", count=cancelled)
    with suppress(Exception):
        await registry.stop_listener()

    await close_db()

    try:
        from app.infrastructure.persistence.redis.client import close_redis_client

        await close_redis_client()
    except Exception as e:
        logger.error("Error closing Redis", error=str(e))

    try:
        from app.infrastructure.web.lifecycle import close_web_research_resources

        await close_web_research_resources()
    except Exception as e:
        logger.error("Error closing web research resources", error=str(e))


app = FastAPI(
    title=settings.app_name,
    description="AI-Powered Coding Assistant API",
    version=__version__,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.middleware("http")(error_handler_middleware)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(oauth.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(models.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": __version__,
        "environment": settings.app_env,
        "docs": "/api/docs" if settings.debug else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.interfaces.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=30,
    )

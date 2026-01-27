"""FastAPI main application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure.config.logger import get_logger, setup_logging
from app.infrastructure.config.settings import settings
from app.infrastructure.persistence.postgres.database import close_db, init_db
from app.interfaces.api.middleware.error_handler import error_handler_middleware
from app.interfaces.api.middleware.rate_limiter import RateLimitMiddleware
from app.interfaces.api.routes import agent, auth, chat, health, projects

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.
    
    Handles startup and shutdown tasks including database
    and Redis connection initialization and cleanup.
    """
    # Startup
    logger.info("Starting ByteBuddhi API", env=settings.app_env)
    
    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))
        raise
    
    # Initialize Redis
    try:
        from app.infrastructure.persistence.redis.client import get_redis_client
        await get_redis_client()
        logger.info("Redis initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize Redis", error=str(e))
        # Redis is optional for basic functionality
    
    yield
    
    # Shutdown
    logger.info("Shutting down ByteBuddhi API")
    await close_db()
    
    # Close Redis connections
    try:
        from app.infrastructure.persistence.redis.client import close_redis_client
        await close_redis_client()
    except Exception as e:
        logger.error("Error closing Redis", error=str(e))


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="AI-Powered Coding Assistant API",
    version="0.1.0",
    docs_url="/api/docs" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Add error handler middleware
app.middleware("http")(error_handler_middleware)

# Include routers
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
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
    )

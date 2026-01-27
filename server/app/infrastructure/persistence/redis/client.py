"""Redis client configuration.

This module provides the Redis client setup and connection management
for the application's caching layer.
"""

import redis.asyncio as redis

from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


# Global Redis client instance
redis_client: redis.Redis = None


async def get_redis_client() -> redis.Redis:
    """Get or create Redis client instance.
    
    This function implements a singleton pattern for the Redis client.
    The client is created on first access and reused for subsequent calls.
    
    Returns:
        redis.Redis: Async Redis client instance
    """
    global redis_client
    
    if redis_client is None:
        redis_client = await create_redis_client()
    
    return redis_client


async def create_redis_client() -> redis.Redis:
    """Create a new Redis client instance.
    
    Configures the Redis client with connection pooling and settings
    from the application configuration.
    
    Returns:
        redis.Redis: Configured async Redis client
    """
    try:
        client = redis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=False,  # We handle encoding/decoding manually
            max_connections=settings.redis_max_connections,
        )
        
        # Test connection
        await client.ping()
        logger.info("Redis connection established", url=str(settings.redis_url))
        
        return client
    except redis.ConnectionError as e:
        logger.error("Failed to connect to Redis", error=str(e))
        raise
    except Exception as e:
        logger.error("Unexpected error creating Redis client", error=str(e))
        raise


async def close_redis_client() -> None:
    """Close the Redis client connection.
    
    Should be called during application shutdown to properly
    close the Redis connection pool.
    """
    global redis_client
    
    if redis_client is not None:
        try:
            await redis_client.close()
            logger.info("Redis connection closed")
            redis_client = None
        except Exception as e:
            logger.error("Error closing Redis connection", error=str(e))

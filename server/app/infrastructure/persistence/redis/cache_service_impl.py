"""Redis cache service implementation.

This module provides the concrete implementation of the CacheService interface
using Redis as the caching backend. It handles all caching operations including
get, set, delete, and TTL management.
"""

from typing import Any, Optional

import orjson
import redis.asyncio as redis

from app.application.ports.output.cache.cache_service import CacheService
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class RedisCacheService(CacheService):
    """Redis implementation of CacheService.
    
    This class provides a Redis-based caching layer for the application.
    It uses orjson for efficient JSON serialization/deserialization and
    supports TTL-based cache expiration.
    
    Attributes:
        redis_client: Async Redis client instance
    """

    def __init__(self, redis_client: redis.Redis):
        """Initialize cache service with Redis client.
        
        Args:
            redis_client: Async Redis client instance
        """
        self.redis_client = redis_client

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve value from cache.
        
        Attempts to retrieve and deserialize the cached value for the given key.
        Returns None if the key doesn't exist or if deserialization fails.
        
        Args:
            key: Cache key to retrieve
            
        Returns:
            Optional[Any]: Cached value if found, None otherwise
        """
        try:
            value = await self.redis_client.get(key)
            if value is None:
                return None
            
            # Deserialize JSON value
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            logger.warning("Failed to deserialize cached value", key=key)
            # Delete corrupted cache entry
            await self.redis_client.delete(key)
            return None
        except Exception as e:
            logger.error("Cache get operation failed", key=key, error=str(e))
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL.
        
        Serializes the value to JSON and stores it in Redis. If TTL is provided,
        the key will automatically expire after the specified number of seconds.
        
        Args:
            key: Cache key to set
            value: Value to cache (must be JSON-serializable)
            ttl: Optional time-to-live in seconds
            
        Returns:
            bool: True if operation succeeded, False otherwise
        """
        try:
            # Serialize value to JSON
            serialized_value = orjson.dumps(value)
            
            if ttl is not None:
                # Set with expiration
                await self.redis_client.setex(key, ttl, serialized_value)
            else:
                # Set without expiration
                await self.redis_client.set(key, serialized_value)
            
            return True
        except TypeError as e:
            logger.error("Value is not JSON-serializable", key=key, error=str(e))
            return False
        except Exception as e:
            logger.error("Cache set operation failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from cache.
        
        Args:
            key: Cache key to delete
            
        Returns:
            bool: True if key was deleted, False if key didn't exist
        """
        try:
            result = await self.redis_client.delete(key)
            return result > 0
        except Exception as e:
            logger.error("Cache delete operation failed", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache.
        
        Args:
            key: Cache key to check
            
        Returns:
            bool: True if key exists, False otherwise
        """
        try:
            result = await self.redis_client.exists(key)
            return result > 0
        except Exception as e:
            logger.error("Cache exists check failed", key=key, error=str(e))
            return False

    async def clear(self) -> bool:
        """Clear all cache entries.
        
        WARNING: This operation flushes the entire Redis database.
        Use with caution, especially in production environments.
        
        Returns:
            bool: True if operation succeeded, False otherwise
        """
        try:
            await self.redis_client.flushdb()
            logger.warning("Cache cleared - all entries deleted")
            return True
        except Exception as e:
            logger.error("Cache clear operation failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close Redis connection.
        
        Should be called during application shutdown to properly
        close the Redis connection pool.
        """
        try:
            await self.redis_client.close()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error("Failed to close Redis connection", error=str(e))

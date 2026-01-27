"""Dependency injection for API routes.

This module provides dependency functions for FastAPI routes,
including database sessions, repository instances, and service instances.
These dependencies follow the dependency injection pattern to decouple
route handlers from concrete implementations.
"""

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.cache.cache_service import CacheService
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.application.ports.output.repository.message_repository import (
    MessageRepository,
)
from app.application.ports.output.repository.project_repository import (
    ProjectRepository,
)
from app.application.ports.output.repository.user_repository import UserRepository
from app.infrastructure.llm.provider_factory import create_llm_provider
from app.infrastructure.persistence.postgres.database import get_db
from app.infrastructure.persistence.postgres.repositories import (
    ConversationRepositoryImpl,
    MessageRepositoryImpl,
    ProjectRepositoryImpl,
    UserRepositoryImpl,
)
from app.infrastructure.persistence.redis.cache_service_impl import RedisCacheService
from app.infrastructure.persistence.redis.client import get_redis_client


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session.
    
    This dependency provides a raw database session for use
    in route handlers that need direct database access.
    
    Yields:
        AsyncSession: Database session
    """
    async for session in get_db():
        yield session


async def get_user_repository(
    db: AsyncSession = Depends(get_db),
) -> UserRepository:
    """Get user repository instance.
    
    This dependency provides a UserRepository implementation
    for use in route handlers.
    
    Args:
        db: Database session from get_db dependency
        
    Returns:
        UserRepository: User repository instance
    """
    return UserRepositoryImpl(db)


async def get_project_repository(
    db: AsyncSession = Depends(get_db),
) -> ProjectRepository:
    """Get project repository instance.
    
    This dependency provides a ProjectRepository implementation
    for use in route handlers.
    
    Args:
        db: Database session from get_db dependency
        
    Returns:
        ProjectRepository: Project repository instance
    """
    return ProjectRepositoryImpl(db)


async def get_conversation_repository(
    db: AsyncSession = Depends(get_db),
) -> ConversationRepository:
    """Get conversation repository instance.
    
    This dependency provides a ConversationRepository implementation
    for use in route handlers.
    
    Args:
        db: Database session from get_db dependency
        
    Returns:
        ConversationRepository: Conversation repository instance
    """
    return ConversationRepositoryImpl(db)


async def get_message_repository(
    db: AsyncSession = Depends(get_db),
) -> MessageRepository:
    """Get message repository instance.
    
    This dependency provides a MessageRepository implementation
    for use in route handlers.
    
    Args:
        db: Database session from get_db dependency
        
    Returns:
        MessageRepository: Message repository instance
    """
    return MessageRepositoryImpl(db)


async def get_cache_service() -> AsyncGenerator[CacheService, None]:
    """Get cache service instance.
    
    This dependency provides a CacheService implementation
    using Redis as the backend.
    
    Yields:
        CacheService: Cache service instance
    """
    redis_client = await get_redis_client()
    cache_service = RedisCacheService(redis_client)
    try:
        yield cache_service
    finally:
        # Cleanup is handled by the global redis client
        pass


async def get_llm_provider() -> LLMProvider:
    """Get LLM provider instance.
    
    This dependency provides an LLM provider (OpenAI by default)
    for chat completions and embeddings.
    
    Returns:
        LLMProvider: LLM provider instance
    """
    return create_llm_provider()


async def get_embedding_provider() -> LLMProvider:
    """Get embedding provider instance.
    
    This dependency provides an LLM provider specifically
    configured for generating embeddings.
    
    Returns:
        LLMProvider: Embedding provider instance
    """
    from app.infrastructure.llm.provider_factory import create_embedding_provider
    
    return create_embedding_provider()

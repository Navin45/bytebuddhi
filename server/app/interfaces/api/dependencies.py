"""Dependency injection for API routes.

This module provides dependency functions for FastAPI routes,
including database sessions, repository instances, and service instances.
These dependencies follow the dependency injection pattern to decouple
route handlers from concrete implementations.
"""

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.cache.cache_service import CacheService
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.llm.model_gateway import ModelGateway
from app.application.ports.output.repository.code_chunk_repository import (
    CodeChunkRepository,
)
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.application.ports.output.repository.embedding_repository import (
    EmbeddingRepository,
)
from app.application.ports.output.repository.file_repository import FileRepository
from app.application.ports.output.repository.message_repository import (
    MessageRepository,
)
from app.application.ports.output.repository.project_repository import (
    ProjectRepository,
)
from app.application.ports.output.repository.user_repository import UserRepository
from app.application.ports.output.storage.file_storage_service import (
    FileStorageService,
)
from app.infrastructure.llm.provider_factory import create_llm_provider
from app.infrastructure.persistence.postgres.database import get_db
from app.infrastructure.persistence.postgres.repositories import (
    CodeChunkRepositoryImpl,
    ConversationRepositoryImpl,
    EmbeddingRepositoryImpl,
    FileRepositoryImpl,
    MessageRepositoryImpl,
    ProjectRepositoryImpl,
    UserRepositoryImpl,
)
from app.infrastructure.persistence.redis.cache_service_impl import RedisCacheService
from app.infrastructure.persistence.redis.client import get_redis_client
from app.infrastructure.storage import LocalFileStorageService


async def get_db_session() -> AsyncGenerator[AsyncSession]:
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


async def get_file_repository(
    db: AsyncSession = Depends(get_db),
) -> FileRepository:
    """Get file repository instance.

    This dependency provides a FileRepository implementation
    for use in route handlers.

    Args:
        db: Database session from get_db dependency

    Returns:
        FileRepository: File repository instance
    """
    return FileRepositoryImpl(db)


async def get_code_chunk_repository(
    db: AsyncSession = Depends(get_db),
) -> CodeChunkRepository:
    """Get code chunk repository instance.

    This dependency provides a CodeChunkRepository implementation
    for use in route handlers.

    Args:
        db: Database session from get_db dependency

    Returns:
        CodeChunkRepository: Code chunk repository instance
    """
    return CodeChunkRepositoryImpl(db)


async def get_embedding_repository(
    db: AsyncSession = Depends(get_db),
) -> EmbeddingRepository:
    """Get embedding repository instance.

    This dependency provides an EmbeddingRepository implementation
    for use in route handlers.

    Args:
        db: Database session from get_db dependency

    Returns:
        EmbeddingRepository: Embedding repository instance
    """
    return EmbeddingRepositoryImpl(db)


def get_file_storage_service() -> FileStorageService:
    """Get file storage service instance.

    This dependency provides a FileStorageService implementation
    for storing and retrieving file content.

    Returns:
        FileStorageService: File storage service instance
    """
    # Use local filesystem storage
    return LocalFileStorageService(base_path="./storage")


async def get_cache_service() -> AsyncGenerator[CacheService]:
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


def get_model_gateway() -> ModelGateway:
    """Get ModelGateway instance for agent tool execution."""
    from app.infrastructure.llm.provider_factory import create_model_gateway

    return create_model_gateway()


def get_tool_registry() -> Any:
    """Get ToolRegistry with default Phase 1 tools registered."""
    from app.application.tools.builtin.echo_tool import register_echo_tool
    from app.application.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_echo_tool(registry)
    return registry


def get_context_engine() -> Any:
    """Get ContextEngine instance."""
    from app.application.agent.context import ContextEngine

    return ContextEngine()


async def get_agent_runtime(
    db: AsyncSession = Depends(get_db),
    model_gateway: ModelGateway = Depends(get_model_gateway),
) -> Any:
    """Get AgentRuntime configured with ModelGateway, ToolRegistry, and Postgres checkpoint saver."""
    from app.application.agent.context import ContextEngine
    from app.application.agent.runtime import AgentRuntime
    from app.application.tools.builtin.echo_tool import register_echo_tool
    from app.application.tools.registry import ToolRegistry
    from app.infrastructure.persistence.postgres.checkpoint_saver import PostgresCheckpointSaver

    registry = ToolRegistry()
    register_echo_tool(registry)
    context_engine = ContextEngine()
    checkpointer = PostgresCheckpointSaver(db)

    return AgentRuntime(
        model_gateway=model_gateway,
        tool_registry=registry,
        context_engine=context_engine,
        checkpointer=checkpointer,
    )

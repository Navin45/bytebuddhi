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


def get_workspace() -> Any:
    """Get active Workspace instance."""
    from app.domain.models.workspace import Workspace

    return Workspace.create(root_path=".", workspace_id="default_workspace")


def get_artifact_store() -> Any:
    """Get ArtifactStore for archiving large process outputs."""
    from app.infrastructure.storage.local_artifact_store import LocalArtifactStore

    return LocalArtifactStore(base_dir="./storage/artifacts")


def get_process_manager() -> Any:
    """Get LocalProcessManager for OS command execution."""
    from app.infrastructure.execution.local_process_manager import LocalProcessManager

    return LocalProcessManager()


def get_command_policy() -> Any:
    """Get CommandPolicy instance."""
    from app.application.policy.command_policy import CommandPolicy

    return CommandPolicy()


def get_tool_policy_engine() -> Any:
    """Get ToolPolicyEngine instance."""
    from app.application.policy.tool_policy import ToolPolicyEngine

    return ToolPolicyEngine(command_policy=get_command_policy())


def get_command_executor(
    workspace: Any = Depends(get_workspace),
    process_manager: Any = Depends(get_process_manager),
    artifact_store: Any = Depends(get_artifact_store),
    command_policy: Any = Depends(get_command_policy),
) -> Any:
    """Get CommandExecutor instance."""
    from app.application.execution.command_executor import CommandExecutor

    return CommandExecutor(
        process_manager=process_manager,
        workspace=workspace,
        command_policy=command_policy,
        artifact_store=artifact_store,
    )


def get_tool_registry(
    command_executor: Any = Depends(get_command_executor),
) -> Any:
    """Get ToolRegistry with Phase 1 and Phase 2 tools registered."""
    from app.application.tools.builtin.command_tools import create_command_tool
    from app.application.tools.builtin.echo_tool import register_echo_tool
    from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
    from app.application.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_echo_tool(registry)

    # Register filesystem tools
    for defn, handler in create_filesystem_tools():
        registry.register(defn, handler)

    # Register command tool
    cmd_def, cmd_handler = create_command_tool(command_executor)
    registry.register(cmd_def, cmd_handler)

    return registry


def get_context_engine() -> Any:
    """Get ContextEngine instance."""
    from app.application.agent.context import ContextEngine

    return ContextEngine()


def get_sqlite_memory_store() -> Any:
    """Get SqliteMemoryStore for local operational memory."""
    from app.infrastructure.persistence.sqlite.sqlite_memory_store import SqliteMemoryStore

    return SqliteMemoryStore(db_path="./storage/operational_memory.db")


def get_postgres_memory_store(
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get PostgresMemoryStore for durable memory."""
    from app.infrastructure.persistence.postgres.repositories.postgres_memory_store import PostgresMemoryStore

    return PostgresMemoryStore(db)


async def get_memory_orchestrator(
    working_store: Any = Depends(get_sqlite_memory_store),
    durable_store: Any = Depends(get_postgres_memory_store),
    artifact_store: Any = Depends(get_artifact_store),
    embedding_provider: Any = Depends(get_embedding_provider),
) -> Any:
    """Get MemoryOrchestrator instance."""
    from app.application.memory.orchestrator import MemoryOrchestrator

    return MemoryOrchestrator(
        working_store=working_store,
        durable_store=durable_store,
        artifact_store=artifact_store,
        embedding_provider=embedding_provider,
    )


def get_code_parser() -> Any:
    """Get CodeParser instance."""
    from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser

    return TreeSitterCodeParser()


def get_code_index() -> Any:
    """Get CodeIndex instance."""
    from app.application.code.in_memory_index import InMemoryCodeIndex

    return InMemoryCodeIndex()


def get_code_intelligence_service(
    parser: Any = Depends(get_code_parser),
    index: Any = Depends(get_code_index),
) -> Any:
    """Get CodeIntelligenceService instance."""
    from app.application.code.intelligence_service import CodeIntelligenceService

    return CodeIntelligenceService(parser=parser, index=index)


def get_credential_provider() -> Any:
    """Get CredentialProvider instance."""
    from app.infrastructure.connectors.credentials.env_credential_provider import EnvAndDictCredentialProvider

    return EnvAndDictCredentialProvider()


def get_external_http_client() -> Any:
    """Get ExternalHttpClient instance."""
    from app.infrastructure.http.external_client import ExternalHttpClient

    return ExternalHttpClient()


def get_github_connector(
    credential_provider: Any = Depends(get_credential_provider),
    http_client: Any = Depends(get_external_http_client),
) -> Any:
    """Get reference GitHubConnector instance."""
    from app.infrastructure.connectors.github.github_connector import GitHubConnector

    return GitHubConnector(
        credential_provider=credential_provider,
        client=http_client,
    )


def get_mcp_capability_manager() -> Any:
    """Get MCPCapabilityManager instance."""
    from app.infrastructure.mcp.client_manager import MCPCapabilityManager

    return MCPCapabilityManager()


async def get_agent_runtime(
    db: AsyncSession = Depends(get_db),
    model_gateway: ModelGateway = Depends(get_model_gateway),
    workspace: Any = Depends(get_workspace),
    command_executor: Any = Depends(get_command_executor),
    tool_policy_engine: Any = Depends(get_tool_policy_engine),
    memory_orchestrator: Any = Depends(get_memory_orchestrator),
    code_intelligence_service: Any = Depends(get_code_intelligence_service),
    github_connector: Any = Depends(get_github_connector),
    mcp_manager: Any = Depends(get_mcp_capability_manager),
    artifact_store: Any = Depends(get_artifact_store),
) -> Any:
    """Get AgentRuntime configured with Phase 1-5 capabilities and Postgres checkpoint saver."""
    from app.application.agent.context import ContextEngine
    from app.application.agent.runtime import AgentRuntime
    from app.application.tools.builtin.code_tools import create_code_tools
    from app.application.tools.builtin.command_tools import create_command_tool
    from app.application.tools.builtin.echo_tool import register_echo_tool
    from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
    from app.application.tools.executor import ToolExecutor
    from app.application.tools.registry import ToolRegistry
    from app.infrastructure.persistence.postgres.checkpoint_saver import PostgresCheckpointSaver

    registry = ToolRegistry()
    register_echo_tool(registry)

    for defn, handler in create_filesystem_tools():
        registry.register(defn, handler)

    cmd_def, cmd_handler = create_command_tool(command_executor)
    registry.register(cmd_def, cmd_handler)

    for defn, handler in create_code_tools(code_intelligence_service, default_workspace=workspace):
        registry.register(defn, handler)

    # Register GitHub connector capabilities
    github_connector.register_capabilities(registry)

    # Wire registry into policy engine for risk & approval validation
    tool_policy_engine.registry = registry

    tool_executor = ToolExecutor(
        registry,
        policy_engine=tool_policy_engine,
        artifact_store=artifact_store,
    )
    context_engine = ContextEngine()
    checkpointer = PostgresCheckpointSaver(db)

    runtime = AgentRuntime(
        model_gateway=model_gateway,
        tool_registry=registry,
        context_engine=context_engine,
        tool_executor=tool_executor,
        checkpointer=checkpointer,
        workspace=workspace,
        memory_orchestrator=memory_orchestrator,
    )

    # Register multi-agent delegation capability
    from app.application.agent.orchestrator import MultiAgentOrchestrator
    from app.application.agent.registry import create_default_registry
    from app.application.tools.builtin.delegation_tools import create_delegation_tool

    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=create_default_registry(),
        artifact_store=artifact_store,
        policy_engine=tool_policy_engine,
    )
    del_def, del_handler = create_delegation_tool(orchestrator)
    registry.register(del_def, del_handler)

    return runtime


def get_agent_registry() -> Any:
    """Get default trusted AgentRegistry."""
    from app.application.agent.registry import create_default_registry

    return create_default_registry()


def get_context_projector() -> Any:
    """Get default AgentContextProjector."""
    from app.application.agent.context_projector import AgentContextProjector

    return AgentContextProjector()


def get_multi_agent_orchestrator(
    agent_runtime: Any = Depends(get_agent_runtime),
    agent_registry: Any = Depends(get_agent_registry),
    context_projector: Any = Depends(get_context_projector),
    artifact_store: Any = Depends(get_artifact_store),
    tool_policy_engine: Any = Depends(get_tool_policy_engine),
) -> Any:
    """Get MultiAgentOrchestrator instance."""
    from app.application.agent.orchestrator import MultiAgentOrchestrator

    return MultiAgentOrchestrator(
        agent_runtime=agent_runtime,
        agent_registry=agent_registry,
        context_projector=context_projector,
        artifact_store=artifact_store,
        policy_engine=tool_policy_engine,
    )

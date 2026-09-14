"""Dependency injection for API routes.

Composition-root lifetime model (FastAPI caches each Depends() result per request
unless noted). Do not share user/project/workspace/run identity across requests.

| Dependency | Lifetime | Statefulness | Concurrency | Cleanup |
|---|---|---|---|---|
| DB session | request | connection | one session per request | session close |
| Repositories | request | wrap session | not shared | with session |
| Settings | application | immutable config | safe | n/a |
| Tracer/Meter | application | SDK providers | safe | process shutdown |
| ArtifactStore | request instance, shared FS root | filesystem | project namespaces | n/a |
| ProcessManager | request | in-flight processes | isolate per execution | cancel/wait |
| ExternalHttpClient | request | httpx client | do not store user creds | close with request GC |
| CredentialProvider | request | env/dict | project-scoped secrets | n/a |
| MCP manager | request | server clients | per-request | close with request GC |
| ToolRegistry | request (built with runtime) | mutable index | not shared across users | n/a |
| ToolPolicyEngine | request | registry pointer | not shared | n/a |
| AgentRuntime | request | run loop + checkpointer | not shared | n/a |
| MultiAgentOrchestrator | request, attached to that runtime | budget counters | not shared across users | n/a |
| CodeIndex | request, ephemeral empty index | in-memory | not persistent, not cross-project | discarded |
| CodeParser | request | Tree-sitter | safe to recreate | n/a |
| Web research resources | application (lifecycle.py) | http/browser | bounded | API shutdown |
| WorkspaceResolutionService | request | mode/root from settings | no user identity stored | n/a |
| ExecuteTaskUseCase | request | none beyond deps | n/a | n/a |

User identity, project identity, workspace, and approvals are never taken from this
module; ExecuteTaskUseCase builds ExecutionContext after authorization.
"""

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.cache.cache_service import CacheService
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.llm.model_gateway import ModelGateway
from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.tracer import Tracer
from app.application.ports.output.repository.code_chunk_repository import (
    CodeChunkRepository,
)
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.application.ports.output.repository.embedding_repository import (
    EmbeddingRepository,
)
from app.application.ports.output.repository.external_identity_repository import (
    ExternalIdentityRepository,
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
    ExternalIdentityRepositoryImpl,
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


async def get_external_identity_repository(
    db: AsyncSession = Depends(get_db),
) -> ExternalIdentityRepository:
    return ExternalIdentityRepositoryImpl(db)


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
    """Get the routing ModelGateway (provider adapters behind the catalog)."""
    from app.infrastructure.llm.provider_factory import create_routing_gateway

    return create_routing_gateway()


def get_model_catalog() -> Any:
    from app.infrastructure.llm.provider_factory import build_model_catalog

    return build_model_catalog()


def get_workspace() -> Any:
    """Placeholder workspace for composition of command/code tools before a run.

    Request-scoped. Not an authorization boundary. ExecuteTaskUseCase resolves the
    authoritative project workspace; AgentRuntime.run receives that Workspace.
    Handlers must use ToolExecutionContext.workspace, not this default.
    """
    from app.domain.models.workspace import Workspace

    return Workspace.create(root_path="storage/workspaces/default", workspace_id="default_workspace")


def get_telemetry_tracer() -> Tracer:
    """Get global configured OpenTelemetry or NoOp tracer."""
    from app.infrastructure.observability import get_tracer

    return get_tracer()


def get_telemetry_meter() -> Meter:
    """Get global configured OpenTelemetry or NoOp meter."""
    from app.infrastructure.observability import get_meter

    return get_meter()


def get_artifact_store(
    tracer: Any = Depends(get_telemetry_tracer),
) -> Any:
    """Get ArtifactStore for archiving large process outputs."""
    from app.infrastructure.storage.local_artifact_store import LocalArtifactStore

    return LocalArtifactStore(base_dir="./storage/artifacts", tracer=tracer)


def get_process_manager(
    tracer: Any = Depends(get_telemetry_tracer),
    meter: Any = Depends(get_telemetry_meter),
) -> Any:
    """Get LocalProcessManager for OS command execution."""
    from app.infrastructure.execution.local_process_manager import LocalProcessManager

    return LocalProcessManager(tracer=tracer, meter=meter)


def get_command_policy() -> Any:
    """Get CommandPolicy instance."""
    from app.application.policy.command_policy import CommandPolicy

    return CommandPolicy()


def get_tool_policy_engine(
    command_policy: Any = Depends(get_command_policy),
    tracer: Any = Depends(get_telemetry_tracer),
    meter: Any = Depends(get_telemetry_meter),
) -> Any:
    """Get ToolPolicyEngine instance."""
    from app.application.policy.tool_policy import ToolPolicyEngine

    return ToolPolicyEngine(command_policy=command_policy, tracer=tracer, meter=meter)


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
    """Get ToolRegistry with built-in tools registered."""
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
    tracer: Any = Depends(get_telemetry_tracer),
    meter: Any = Depends(get_telemetry_meter),
) -> Any:
    """Get MemoryOrchestrator instance."""
    from app.application.memory.orchestrator import MemoryOrchestrator

    return MemoryOrchestrator(
        working_store=working_store,
        durable_store=durable_store,
        artifact_store=artifact_store,
        embedding_provider=embedding_provider,
        tracer=tracer,
        meter=meter,
    )


def get_code_parser() -> Any:
    """Get CodeParser instance."""
    from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser

    return TreeSitterCodeParser()


def get_code_index() -> Any:
    """Request-scoped ephemeral in-memory index.

    Not a persistent per-project index. Each request starts empty and is discarded.
    Do not treat this as cross-request code intelligence cache.
    """
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


def get_external_http_client(
    tracer: Any = Depends(get_telemetry_tracer),
    meter: Any = Depends(get_telemetry_meter),
) -> Any:
    """Get ExternalHttpClient instance."""
    from app.infrastructure.http.external_client import ExternalHttpClient

    return ExternalHttpClient(tracer=tracer, meter=meter)


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


def get_mcp_capability_manager(
    tracer: Any = Depends(get_telemetry_tracer),
    meter: Any = Depends(get_telemetry_meter),
) -> Any:
    """Get MCPCapabilityManager instance."""
    from app.infrastructure.mcp.client_manager import MCPCapabilityManager

    return MCPCapabilityManager(tracer=tracer, meter=meter)


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
    tracer: Any = Depends(get_telemetry_tracer),
    meter: Any = Depends(get_telemetry_meter),
) -> Any:
    """Get AgentRuntime configured with registered capabilities and Postgres checkpoint saver."""
    from app.interfaces.composition import assemble_agent_runtime

    return assemble_agent_runtime(
        db,
        model_gateway=model_gateway,
        workspace=workspace,
        command_executor=command_executor,
        tool_policy_engine=tool_policy_engine,
        memory_orchestrator=memory_orchestrator,
        code_intelligence_service=code_intelligence_service,
        github_connector=github_connector,
        mcp_manager=mcp_manager,
        artifact_store=artifact_store,
        tracer=tracer,
        meter=meter,
    )


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
) -> Any:
    """Return the orchestrator owned by the request's AgentRuntime.

    Delegation tools and application use cases must share this instance so budget
    counters stay consistent for the request. It is not an application singleton.
    """
    orchestrator = getattr(agent_runtime, "orchestrator", None)
    if orchestrator is None:
        raise RuntimeError("AgentRuntime was composed without a MultiAgentOrchestrator")
    return orchestrator


def get_workspace_resolution_service(
    project_repo: ProjectRepository = Depends(get_project_repository),
) -> Any:
    """Get authoritative WorkspaceResolutionService instance.

    Mode and root come from settings, never from model or client payload.
    Production requires WORKSPACE_MODE=managed.
    """
    from app.application.workspace.resolution_service import WorkspaceResolutionService
    from app.infrastructure.config.settings import settings as app_settings

    return WorkspaceResolutionService(
        project_repo=project_repo,
        base_storage_dir=app_settings.workspace_root,
        workspace_mode=app_settings.workspace_mode,
        workspace_root=app_settings.workspace_root,
    )


async def get_execute_task_use_case(
    workspace_resolution: Any = Depends(get_workspace_resolution_service),
    agent_runtime: Any = Depends(get_agent_runtime),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
    message_repo: MessageRepository = Depends(get_message_repository),
    model_catalog: Any = Depends(get_model_catalog),
) -> Any:
    """Get ExecuteTaskUseCase instance."""
    from app.application.use_cases.agent.execute_task import ExecuteTaskUseCase

    return ExecuteTaskUseCase(
        workspace_resolution_service=workspace_resolution,
        agent_runtime=agent_runtime,
        conversation_repo=conversation_repo,
        message_repo=message_repo,
        model_catalog=model_catalog,
    )


def get_oauth_service(
    users: UserRepository = Depends(get_user_repository),
    identities: ExternalIdentityRepository = Depends(get_external_identity_repository),
    http_client: Any = Depends(get_external_http_client),
    tracer: Any = Depends(get_telemetry_tracer),
) -> Any:
    """Assemble OAuthService for the current request. Provider SDKs stay in adapters."""
    from app.application.auth.config import OAuthRuntimeConfig
    from app.application.auth.oauth_service import OAuthService
    from app.infrastructure.auth.oauth.factory import build_oauth_registry
    from app.infrastructure.auth.oauth.state import get_oauth_state_store
    from app.infrastructure.config.settings import settings as app_settings

    config = OAuthRuntimeConfig(
        google_enabled=app_settings.google_oauth_enabled,
        github_enabled=app_settings.github_oauth_enabled,
        google_redirect_uri=app_settings.google_redirect_uri,
        github_redirect_uri=app_settings.github_redirect_uri,
        state_ttl_seconds=app_settings.oauth_state_ttl_seconds,
        exchange_ttl_seconds=app_settings.oauth_exchange_ttl_seconds,
        post_login_redirect=app_settings.oauth_post_login_redirect,
        vscode_redirect=app_settings.oauth_vscode_redirect,
        cli_redirect=app_settings.oauth_cli_redirect,
    )
    return OAuthService(
        registry=build_oauth_registry(app_settings, http_client),
        state_store=get_oauth_state_store(),
        users=users,
        identities=identities,
        config=config,
        tracer=tracer,
    )

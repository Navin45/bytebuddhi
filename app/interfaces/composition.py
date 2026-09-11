"""Shared application composition used by the API and CLI.

This is the composition root for AgentRuntime assembly. Interface adapters
must not duplicate this graph.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent.runtime import AgentRuntime
from app.application.ports.output.repository.user_repository import UserRepository
from app.application.use_cases.agent.execute_task import ExecuteTaskUseCase
from app.application.use_cases.project.get_project import GetProjectUseCase
from app.application.use_cases.project.list_projects import ListProjectsUseCase
from app.application.use_cases.project.resolve_project_by_local_path import ResolveProjectByLocalPathUseCase


def assemble_agent_runtime(
    db: AsyncSession,
    *,
    model_gateway: Any,
    workspace: Any,
    command_executor: Any,
    tool_policy_engine: Any,
    memory_orchestrator: Any,
    code_intelligence_service: Any,
    github_connector: Any,
    mcp_manager: Any,
    artifact_store: Any,
    tracer: Any,
    meter: Any,
) -> AgentRuntime:
    """Build the canonical AgentRuntime with a request/CLI-scoped MultiAgentOrchestrator."""
    from app.application.agent.context import ContextEngine
    from app.application.agent.orchestrator import MultiAgentOrchestrator
    from app.application.agent.registry import create_default_registry
    from app.application.tools.builtin.code_tools import create_code_tools
    from app.application.tools.builtin.command_tools import create_command_tool
    from app.application.tools.builtin.delegation_tools import create_delegation_tool
    from app.application.tools.builtin.echo_tool import register_echo_tool
    from app.application.tools.builtin.filesystem_tools import create_filesystem_tools
    from app.application.tools.builtin.web_research import create_web_research_tool
    from app.application.tools.executor import ToolExecutor
    from app.application.tools.registry import ToolRegistry
    from app.infrastructure.config.settings import settings as app_settings
    from app.infrastructure.persistence.postgres.checkpoint_saver import PostgresCheckpointSaver
    from app.infrastructure.web.lifecycle import get_web_research_resources

    registry = ToolRegistry()
    register_echo_tool(registry)

    for defn, handler in create_filesystem_tools():
        registry.register(defn, handler)

    cmd_def, cmd_handler = create_command_tool(command_executor)
    registry.register(cmd_def, cmd_handler)

    for defn, handler in create_code_tools(code_intelligence_service, default_workspace=workspace):
        registry.register(defn, handler)

    github_connector.register_capabilities(registry)

    if mcp_manager is not None:
        mcp_manager.registry = registry

    web_resources = get_web_research_resources(
        settings=app_settings,
        artifact_store=artifact_store,
        tracer=tracer,
        meter=meter,
    )
    web_def, web_handler = create_web_research_tool(web_resources.service)
    registry.register(web_def, web_handler)

    tool_policy_engine.registry = registry

    tool_executor = ToolExecutor(
        registry,
        policy_engine=tool_policy_engine,
        artifact_store=artifact_store,
        tracer=tracer,
        meter=meter,
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
        tracer=tracer,
        meter=meter,
    )

    orchestrator = MultiAgentOrchestrator(
        agent_runtime=runtime,
        agent_registry=create_default_registry(),
        artifact_store=artifact_store,
        policy_engine=tool_policy_engine,
        tracer=tracer,
        meter=meter,
    )
    del_def, del_handler = create_delegation_tool(orchestrator)
    registry.register(del_def, del_handler)
    runtime.orchestrator = orchestrator
    return runtime


@dataclass
class ApplicationGraph:
    """CLI/API-shared application services constructed from one composition root."""

    list_projects: ListProjectsUseCase
    get_project: GetProjectUseCase
    resolve_local_project: ResolveProjectByLocalPathUseCase
    user_repository: UserRepository
    execute_task: ExecuteTaskUseCase | None = None
    http_client: Any = None
    mcp_manager: Any = None

    async def aclose(self) -> None:
        if self.http_client is not None and hasattr(self.http_client, "close"):
            await self.http_client.close()
        if self.mcp_manager is not None and hasattr(self.mcp_manager, "close_all"):
            await self.mcp_manager.close_all()


def compose_identity_services(db: AsyncSession) -> ApplicationGraph:
    """Project/user services without constructing AgentRuntime."""
    from app.infrastructure.config.settings import settings as app_settings
    from app.infrastructure.persistence.postgres.repositories import (
        ProjectRepositoryImpl,
        UserRepositoryImpl,
    )

    project_repo = ProjectRepositoryImpl(db)
    return ApplicationGraph(
        list_projects=ListProjectsUseCase(project_repo),
        get_project=GetProjectUseCase(project_repo),
        resolve_local_project=ResolveProjectByLocalPathUseCase(
            project_repo,
            workspace_mode=app_settings.workspace_mode,
        ),
        user_repository=UserRepositoryImpl(db),
    )


def compose_application_graph(db: AsyncSession) -> ApplicationGraph:
    """Build ExecuteTaskUseCase and supporting services using the shared runtime graph."""
    from app.application.code.in_memory_index import InMemoryCodeIndex
    from app.application.code.intelligence_service import CodeIntelligenceService
    from app.application.execution.command_executor import CommandExecutor
    from app.application.memory.orchestrator import MemoryOrchestrator
    from app.application.policy.command_policy import CommandPolicy
    from app.application.policy.tool_policy import ToolPolicyEngine
    from app.application.workspace.resolution_service import WorkspaceResolutionService
    from app.domain.models.workspace import Workspace
    from app.infrastructure.config.settings import settings as app_settings
    from app.infrastructure.connectors.credentials.env_credential_provider import EnvAndDictCredentialProvider
    from app.infrastructure.connectors.github.github_connector import GitHubConnector
    from app.infrastructure.execution.local_process_manager import LocalProcessManager
    from app.infrastructure.http.external_client import ExternalHttpClient
    from app.infrastructure.llm.provider_factory import create_embedding_provider, create_model_gateway
    from app.infrastructure.mcp.client_manager import MCPCapabilityManager
    from app.infrastructure.observability import get_meter, get_tracer
    from app.infrastructure.parser.tree_sitter_parser import TreeSitterCodeParser
    from app.infrastructure.persistence.postgres.repositories import (
        ConversationRepositoryImpl,
        MessageRepositoryImpl,
        ProjectRepositoryImpl,
        UserRepositoryImpl,
    )
    from app.infrastructure.persistence.postgres.repositories.postgres_memory_store import PostgresMemoryStore
    from app.infrastructure.persistence.sqlite.sqlite_memory_store import SqliteMemoryStore
    from app.infrastructure.storage.local_artifact_store import LocalArtifactStore

    tracer = get_tracer()
    meter = get_meter()
    workspace = Workspace.create(root_path="storage/workspaces/default", workspace_id="default_workspace")
    artifact_store = LocalArtifactStore(base_dir="./storage/artifacts", tracer=tracer)
    process_manager = LocalProcessManager(tracer=tracer, meter=meter)
    command_policy = CommandPolicy()
    tool_policy_engine = ToolPolicyEngine(command_policy=command_policy, tracer=tracer, meter=meter)
    command_executor = CommandExecutor(
        process_manager=process_manager,
        workspace=workspace,
        command_policy=command_policy,
        artifact_store=artifact_store,
    )
    http_client = ExternalHttpClient(tracer=tracer, meter=meter)
    github_connector = GitHubConnector(
        credential_provider=EnvAndDictCredentialProvider(),
        client=http_client,
    )
    mcp_manager = MCPCapabilityManager(tracer=tracer, meter=meter)
    code_intelligence = CodeIntelligenceService(parser=TreeSitterCodeParser(), index=InMemoryCodeIndex())
    memory_orchestrator = MemoryOrchestrator(
        working_store=SqliteMemoryStore(db_path="./storage/operational_memory.db"),
        durable_store=PostgresMemoryStore(db),
        artifact_store=artifact_store,
        embedding_provider=create_embedding_provider(),
        tracer=tracer,
        meter=meter,
    )
    runtime = assemble_agent_runtime(
        db,
        model_gateway=create_model_gateway(),
        workspace=workspace,
        command_executor=command_executor,
        tool_policy_engine=tool_policy_engine,
        memory_orchestrator=memory_orchestrator,
        code_intelligence_service=code_intelligence,
        github_connector=github_connector,
        mcp_manager=mcp_manager,
        artifact_store=artifact_store,
        tracer=tracer,
        meter=meter,
    )
    project_repo = ProjectRepositoryImpl(db)
    workspace_resolution = WorkspaceResolutionService(
        project_repo=project_repo,
        base_storage_dir=app_settings.workspace_root,
        workspace_mode=app_settings.workspace_mode,
        workspace_root=app_settings.workspace_root,
    )
    execute_task = ExecuteTaskUseCase(
        workspace_resolution_service=workspace_resolution,
        agent_runtime=runtime,
        conversation_repo=ConversationRepositoryImpl(db),
        message_repo=MessageRepositoryImpl(db),
    )
    return ApplicationGraph(
        execute_task=execute_task,
        list_projects=ListProjectsUseCase(project_repo),
        get_project=GetProjectUseCase(project_repo),
        resolve_local_project=ResolveProjectByLocalPathUseCase(
            project_repo,
            workspace_mode=app_settings.workspace_mode,
        ),
        user_repository=UserRepositoryImpl(db),
        http_client=http_client,
        mcp_manager=mcp_manager,
    )

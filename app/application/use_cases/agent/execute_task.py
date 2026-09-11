"""Pure application use case for executing agent tasks decoupled from HTTP transport."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from app.application.agent.runtime import AgentRuntime
from app.application.agent.state import AgentRunState
from app.application.ports.output.logger import get_logger
from app.application.ports.output.repository.conversation_repository import ConversationRepository
from app.application.ports.output.repository.message_repository import MessageRepository
from app.application.workspace.resolution_service import WorkspaceResolutionService
from app.domain.models.conversation import Conversation
from app.domain.models.execution_context import ExecutionContext
from app.domain.models.message import Message, MessageRole

logger = get_logger(__name__)


@dataclass
class ExecuteTaskCommand:
    """Input command for executing an agent task."""

    prompt: str
    user_id: UUID | str
    project_id: UUID | str | None = None
    conversation_id: UUID | str | None = None
    run_id: str | None = None


@dataclass
class ExecuteTaskResult:
    """Result of task execution."""

    run_id: str
    response: str
    run_state: AgentRunState
    conversation_id: UUID | str
    workspace_id: str


class ExecuteTaskUseCase:
    """Orchestrates task execution through authoritative authorization, workspace resolution, and canonical runtime."""

    def __init__(
        self,
        workspace_resolution_service: WorkspaceResolutionService,
        agent_runtime: AgentRuntime,
        conversation_repo: ConversationRepository | None = None,
        message_repo: MessageRepository | None = None,
    ) -> None:
        self.workspace_resolution = workspace_resolution_service
        self.agent_runtime = agent_runtime
        self.conversation_repo = conversation_repo
        self.message_repo = message_repo

    async def execute(self, command: ExecuteTaskCommand) -> ExecuteTaskResult:
        """Execute a task with trusted context and isolated workspace."""
        user_uuid = UUID(str(command.user_id)) if isinstance(command.user_id, str) else command.user_id
        project_uuid: UUID | None = None
        if command.project_id:
            project_uuid = UUID(str(command.project_id)) if isinstance(command.project_id, str) else command.project_id

        # 1. Authoritative workspace resolution (enforces ownership and path boundaries)
        workspace = await self.workspace_resolution.resolve_workspace(
            user_id=user_uuid,
            project_id=project_uuid,
        )

        run_id = command.run_id or f"run_{uuid4().hex[:12]}"

        # 2. Build trusted immutable ExecutionContext immediately after workspace resolution.
        execution_context = ExecutionContext(
            user_id=user_uuid,
            project_id=project_uuid,
            conversation_id=command.conversation_id,
            run_id=run_id,
            workspace_id=workspace.workspace_id,
        )

        # 3. Resolve or create conversation if repositories provided
        conv_id = command.conversation_id
        if self.conversation_repo and conv_id is None:
            new_conv = Conversation.create(
                user_id=user_uuid,
                project_id=project_uuid,
                title=command.prompt[:30],
            )
            created_conv = await self.conversation_repo.create(new_conv)
            conv_id = created_conv.id

        if conv_id is not None and conv_id != execution_context.conversation_id:
            execution_context = execution_context.with_conversation_id(conv_id)

        # 4. Save human message if message repo provided
        if self.message_repo and conv_id is not None:
            conv_uuid = UUID(str(conv_id)) if isinstance(conv_id, str) else conv_id
            human_msg = Message.create(
                conversation_id=conv_uuid,
                role=MessageRole.USER,
                content=command.prompt,
            )
            await self.message_repo.create(human_msg)

        # 5. Invoke canonical AgentRuntime with the trusted context.
        logger.info(
            "Executing task via canonical runtime",
            run_id=run_id,
            user_id=str(user_uuid),
            project_id=str(project_uuid),
            workspace_id=workspace.workspace_id,
        )

        run_state = await self.agent_runtime.run(
            messages=[{"role": "user", "content": command.prompt}],
            workspace=workspace,
            run_id=run_id,
            execution_context=execution_context,
        )

        response_text = run_state.final_response or ""

        # 6. Save assistant message if message repo provided
        if self.message_repo and conv_id is not None:
            conv_uuid = UUID(str(conv_id)) if isinstance(conv_id, str) else conv_id
            ai_msg = Message.create(
                conversation_id=conv_uuid,
                role=MessageRole.ASSISTANT,
                content=response_text,
            )
            await self.message_repo.create(ai_msg)

        return ExecuteTaskResult(
            run_id=run_id,
            response=response_text,
            run_state=run_state,
            conversation_id=conv_id or run_id,
            workspace_id=workspace.workspace_id,
        )

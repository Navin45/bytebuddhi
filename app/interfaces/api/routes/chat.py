"""Chat API routes.

This module provides endpoints for chat functionality including
conversation management and message sending with streaming support.
"""

import asyncio
import contextlib
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.application.agent.errors import ModelSelectionError
from app.application.agent.types import AgentStatus
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.application.ports.output.repository.message_repository import MessageRepository
from app.application.runtime.admission import ConcurrentRunLimitExceeded, get_run_admission_controller
from app.application.runtime.cancellation import CancellationToken, get_run_cancellation_registry
from app.application.runtime.events import BoundedExecutionEventBus, ExecutionEventType
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskUseCase
from app.domain.models.conversation import Conversation
from app.domain.models.user import User
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import (
    get_conversation_repository,
    get_execute_task_use_case,
    get_message_repository,
)
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.chat_schema import (
    ConversationCreateRequest,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageCreateRequest,
    MessageResponse,
)
from app.interfaces.api.sse import SSEStreamHandler

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    request: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
):
    """Create a new conversation.

    Creates a new chat conversation, optionally associated with a project.

    Args:
        request: Conversation creation data
        current_user: Authenticated user
        conversation_repo: Conversation repository instance

    Returns:
        ConversationResponse: Created conversation information
    """
    conversation = Conversation.create(
        user_id=current_user.id,
        project_id=request.project_id,
        title=request.title or "New Conversation",
    )

    created_conversation = await conversation_repo.create(conversation)

    logger.info(
        "Conversation created",
        conversation_id=str(created_conversation.id),
        user_id=str(current_user.id),
    )

    return ConversationResponse.model_validate(created_conversation)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
):
    """List all conversations for the authenticated user.

    Returns conversations ordered by last update (most recent first).
    By default, archived conversations are excluded.

    Args:
        include_archived: Whether to include archived conversations
        current_user: Authenticated user
        conversation_repo: Conversation repository instance

    Returns:
        List[ConversationResponse]: List of user's conversations
    """
    conversations = await conversation_repo.get_by_user_id(current_user.id, include_archived=include_archived)
    return [ConversationResponse.model_validate(c) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
):
    """Get a specific conversation by ID.

    Retrieves conversation details. User must own the conversation.

    Args:
        conversation_id: Conversation ID
        current_user: Authenticated user
        conversation_repo: Conversation repository instance

    Returns:
        ConversationResponse: Conversation information

    Raises:
        HTTPException: If conversation not found or user doesn't own it
    """
    conversation = await conversation_repo.get_by_id(conversation_id)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Check ownership
    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this conversation",
        )

    return ConversationResponse.model_validate(conversation)


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    request: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
):
    """Update a conversation.

    Updates conversation fields (title, archive status).
    User must own the conversation.

    Args:
        conversation_id: Conversation ID
        request: Conversation update data
        current_user: Authenticated user
        conversation_repo: Conversation repository instance

    Returns:
        ConversationResponse: Updated conversation information

    Raises:
        HTTPException: If conversation not found or user doesn't own it
    """
    conversation = await conversation_repo.get_by_id(conversation_id)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Check ownership
    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this conversation",
        )

    # Update fields
    if request.title is not None:
        conversation.update_title(request.title)
    if request.is_archived is not None:
        conversation.is_archived = request.is_archived
        conversation.mark_updated()

    updated_conversation = await conversation_repo.update(conversation)

    logger.info(
        "Conversation updated",
        conversation_id=str(conversation_id),
        user_id=str(current_user.id),
    )

    return ConversationResponse.model_validate(updated_conversation)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conversation_id: UUID,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
    message_repo: MessageRepository = Depends(get_message_repository),
):
    """Get messages for a conversation.

    Returns messages in chronological order. User must own the conversation.

    Args:
        conversation_id: Conversation ID
        limit: Maximum number of messages to return
        current_user: Authenticated user
        conversation_repo: Conversation repository instance
        message_repo: Message repository instance

    Returns:
        List[MessageResponse]: List of messages

    Raises:
        HTTPException: If conversation not found or user doesn't own it
    """
    conversation = await conversation_repo.get_by_id(conversation_id)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Check ownership
    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this conversation",
        )

    messages = await message_repo.get_by_conversation_id(conversation_id, limit=limit)
    return [MessageResponse.model_validate(m) for m in messages]


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    request: MessageCreateRequest,
    current_user: User = Depends(get_current_user),
    conversation_repo: ConversationRepository = Depends(get_conversation_repository),
    execute_task: ExecuteTaskUseCase = Depends(get_execute_task_use_case),
):
    """Send a message in a conversation.

    HTTP layer owns auth, conversation ownership, and SSE transport.
    Agent execution is owned by ExecuteTaskUseCase.
    """
    conversation = await conversation_repo.get_by_id(conversation_id)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if conversation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to send messages in this conversation",
        )

    async def generate_response():
        admission = get_run_admission_controller()
        try:
            await admission.acquire(current_user.id)
        except ConcurrentRunLimitExceeded:
            yield SSEStreamHandler.format_sse(
                {"type": "error", "error": "Too many concurrent runs"},
                event="error",
            )
            return
        token = CancellationToken()
        run_id = f"run_{uuid4().hex[:12]}"
        registry = get_run_cancellation_registry()
        bus = BoundedExecutionEventBus()
        await registry.register(run_id, current_user.id, token)
        yield SSEStreamHandler.format_sse(
            {"type": "run_started", "run_id": run_id, "conversation_id": str(conversation_id)},
            event="run_started",
        )
        task = asyncio.create_task(
            execute_task.execute(
                ExecuteTaskCommand(
                    prompt=request.content,
                    user_id=current_user.id,
                    project_id=conversation.project_id,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    parent_message_id=request.parent_message_id,
                    cancellation_token=token,
                    event_sink=bus,
                    model_provider=request.model.provider if request.model else None,
                    model_name=request.model.model if request.model else None,
                )
            )
        )
        await registry.bind_task(run_id, task)
        try:
            result = await task
            bus.close()
            streamed_tools: list[str] = []
            async for event in bus:
                if event.type == ExecutionEventType.TOOL_STARTED:
                    name = str(event.payload.get("tool_name", ""))
                    if name:
                        streamed_tools.append(name)
                        yield SSEStreamHandler.format_sse(
                            {"type": "tool_call", "name": name},
                            event="tool_call",
                        )
            run_state = result.run_state
            for tc in run_state.tool_calls:
                if tc.name not in streamed_tools:
                    yield SSEStreamHandler.format_sse(
                        {"type": "tool_call", "name": tc.name},
                        event="tool_call",
                    )

            if run_state.status == AgentStatus.CANCELLED:
                yield SSEStreamHandler.format_sse(
                    {"type": "cancelled", "run_id": run_id},
                    event="cancelled",
                )
            elif run_state.status == AgentStatus.COMPLETED:
                content = run_state.final_response or ""
                yield SSEStreamHandler.format_sse(
                    {"type": "content", "content": content},
                    event="content",
                )
                yield SSEStreamHandler.format_sse(
                    {"type": "done", "message_id": str(result.conversation_id), "run_id": run_id},
                    event="done",
                )
            else:
                error_message = run_state.error.message if run_state.error else "Agent execution failed"
                yield SSEStreamHandler.format_sse(
                    {"type": "error", "error": error_message},
                    event="error",
                )

        except asyncio.CancelledError:
            token.cancel()
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            current = asyncio.current_task()
            if current is not None and current.cancelled():
                raise
            yield SSEStreamHandler.format_sse(
                {"type": "cancelled", "run_id": run_id},
                event="cancelled",
            )
            return
        except ModelSelectionError as e:
            yield SSEStreamHandler.format_sse(
                {"type": "error", "error": e.message},
                event="error",
            )
            return
        except Exception as e:
            logger.error("Error generating response", error=str(e))
            yield SSEStreamHandler.format_sse(
                {"type": "error", "error": "Agent execution failed"},
                event="error",
            )
        finally:
            bus.close()
            await registry.release(run_id)
            await admission.release(current_user.id)

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
    )

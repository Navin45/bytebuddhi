"""Chat API routes.

This module provides endpoints for chat functionality including
conversation management and message sending with streaming support.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.application.agent import ByteBuddhiAgent
from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.application.ports.output.repository.message_repository import MessageRepository
from app.domain.models.conversation import Conversation
from app.domain.models.message import Message
from app.domain.models.user import User
from app.infrastructure.config.logger import get_logger
from app.infrastructure.monitoring import is_langsmith_enabled
from app.infrastructure.persistence.postgres.checkpoint_saver import get_checkpoint_saver
from app.interfaces.api.dependencies import (
    get_conversation_repository,
    get_db_session,
    get_llm_provider,
    get_message_repository,
)
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.agent_schema import (
    AgentFeedbackRequest,
    AgentFeedbackResponse,
)
from app.interfaces.api.schemas.chat_schema import (
    ChatRequest,
    ChatResponse,
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


@router.get("/conversations", response_model=List[ConversationResponse])
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
    conversations = await conversation_repo.get_by_user_id(
        current_user.id,
        include_archived=include_archived
    )
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


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
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
    message_repo: MessageRepository = Depends(get_message_repository),
    llm: LLMProvider = Depends(get_llm_provider),
):
    """Send a message in a conversation.
    
    Sends a user message and generates an AI response. Returns streaming
    response with Server-Sent Events.
    
    Args:
        conversation_id: Conversation ID
        request: Message content
        current_user: Authenticated user
        conversation_repo: Conversation repository instance
        message_repo: Message repository instance
        llm: LLM provider instance
        
    Returns:
        StreamingResponse: SSE stream of AI response
        
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
            detail="Not authorized to send messages in this conversation",
        )
    
    # Create user message
    user_message = Message.create(
        conversation_id=conversation_id,
        role="user",
        content=request.content,
        parent_message_id=request.parent_message_id,
    )
    await message_repo.create(user_message)
    
    # Get conversation history
    history = await message_repo.get_by_conversation_id(conversation_id, limit=10)
    
    # Build messages for LLM
    llm_messages = [
        {"role": msg.role, "content": msg.content}
        for msg in history
    ]
    
    # Generate streaming response
    async def generate_response():
        """Generate and stream AI response."""
        try:
            # Stream LLM response
            content_chunks = []
            async for chunk in llm.generate_stream(llm_messages):
                content_chunks.append(chunk)
                yield SSEStreamHandler.format_sse(
                    {"type": "content", "content": chunk},
                    event="content"
                )
            
            # Save assistant message
            full_content = "".join(content_chunks)
            assistant_message = Message.create(
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                parent_message_id=user_message.id,
            )
            saved_message = await message_repo.create(assistant_message)
            
            # Send done event with message ID
            yield SSEStreamHandler.format_sse(
                {
                    "type": "done",
                    "message_id": str(saved_message.id),
                },
                event="done"
            )
            
        except Exception as e:
            logger.error("Error generating response", error=str(e))
            yield SSEStreamHandler.format_sse(
                {"type": "error", "error": str(e)},
                event="error"
            )
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
    )

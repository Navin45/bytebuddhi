from typing import Optional
from uuid import UUID

from app.application.dto.chat_dto import ConversationResponseDTO, CreateConversationDTO
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.domain.models.conversation import Conversation


class CreateConversationUseCase:
    """Use case for creating a conversation."""

    def __init__(self, conversation_repository: ConversationRepository):
        self.conversation_repository = conversation_repository

    async def execute(self, dto: CreateConversationDTO) -> ConversationResponseDTO:
        """Execute the use case."""
        # Create domain model
        conversation = Conversation.create(
            user_id=dto.user_id,
            project_id=dto.project_id,
            title=dto.title,
        )

        # Save to repository
        saved_conversation = await self.conversation_repository.create(conversation)

        # Return DTO
        return ConversationResponseDTO(
            id=saved_conversation.id,
            user_id=saved_conversation.user_id,
            project_id=saved_conversation.project_id,
            title=saved_conversation.title,
            created_at=saved_conversation.created_at,
            updated_at=saved_conversation.updated_at,
            is_archived=saved_conversation.is_archived,
        )
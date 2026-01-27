from app.application.dto.chat_dto import MessageResponseDTO, SendMessageDTO
from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.application.ports.output.repository.message_repository import MessageRepository
from app.domain.exceptions.conversation_exceptions import ConversationNotFoundException
from app.domain.models.message import Message


class SendMessageUseCase:
    """Use case for sending a message."""

    def __init__(
        self,
        message_repository: MessageRepository,
        conversation_repository: ConversationRepository,
    ):
        self.message_repository = message_repository
        self.conversation_repository = conversation_repository

    async def execute(self, dto: SendMessageDTO) -> MessageResponseDTO:
        """Execute the use case."""
        # Verify conversation exists
        conversation = await self.conversation_repository.get_by_id(dto.conversation_id)
        if not conversation:
            raise ConversationNotFoundException(str(dto.conversation_id))

        # Create message
        message = Message.create(
            conversation_id=dto.conversation_id,
            role=dto.role,
            content=dto.content,
            parent_message_id=dto.parent_message_id,
        )

        # Save message
        saved_message = await self.message_repository.create(message)

        # Update conversation timestamp
        conversation.updated_at = saved_message.created_at
        await self.conversation_repository.update(conversation)

        # Return DTO
        return MessageResponseDTO(
            id=saved_message.id,
            conversation_id=saved_message.conversation_id,
            role=saved_message.role,
            content=saved_message.content,
            created_at=saved_message.created_at,
            parent_message_id=saved_message.parent_message_id,
            feedback=saved_message.feedback,
        )
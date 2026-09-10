from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models.message import Message


class MessageRepository(ABC):
    """Abstract repository for Message entity."""

    @abstractmethod
    async def create(self, message: Message) -> Message:
        """Create a new message."""
        pass

    @abstractmethod
    async def get_by_id(self, message_id: UUID) -> Message | None:
        """Get message by ID."""
        pass

    @abstractmethod
    async def get_by_conversation_id(self, conversation_id: UUID, limit: int | None = None) -> list[Message]:
        """Get all messages for a conversation."""
        pass

    @abstractmethod
    async def update(self, message: Message) -> Message:
        """Update message."""
        pass

    @abstractmethod
    async def delete(self, message_id: UUID) -> bool:
        """Delete message."""
        pass

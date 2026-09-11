from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models.conversation import Conversation


class ConversationRepository(ABC):
    """Abstract repository for Conversation entity."""

    @abstractmethod
    async def create(self, conversation: Conversation) -> Conversation:
        """Create a new conversation."""
        pass

    @abstractmethod
    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        """Get conversation by ID."""
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: UUID, include_archived: bool = False) -> list[Conversation]:
        """Get all conversations for a user."""
        pass

    @abstractmethod
    async def update(self, conversation: Conversation) -> Conversation:
        """Update conversation."""
        pass

    @abstractmethod
    async def delete(self, conversation_id: UUID) -> bool:
        """Delete conversation."""
        pass

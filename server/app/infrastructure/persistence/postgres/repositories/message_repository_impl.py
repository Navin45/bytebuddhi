"""Message repository implementation for PostgreSQL.

This module provides the concrete implementation of the MessageRepository interface
using SQLAlchemy async sessions. It handles all database operations for Message entities.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.message_repository import MessageRepository
from app.domain.models.message import Message
from app.infrastructure.persistence.postgres.models import MessageModel


class MessageRepositoryImpl(MessageRepository):
    """PostgreSQL implementation of MessageRepository.
    
    This class implements the MessageRepository interface, providing concrete
    database operations for managing chat messages within conversations.
    
    Attributes:
        session: AsyncSession instance for database operations
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.
        
        Args:
            session: SQLAlchemy async session for database operations
        """
        self.session = session

    async def create(self, message: Message) -> Message:
        """Create a new message in the database.
        
        Args:
            message: Domain Message entity to persist
            
        Returns:
            Message: The created message
        """
        message_model = MessageModel(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            metadata=message.metadata,
            parent_message_id=message.parent_message_id,
            feedback=message.feedback,
        )
        self.session.add(message_model)
        await self.session.flush()
        return self._to_domain(message_model)

    async def get_by_id(self, message_id: UUID) -> Optional[Message]:
        """Retrieve a message by its ID.
        
        Args:
            message_id: UUID of the message to retrieve
            
        Returns:
            Optional[Message]: Message if found, None otherwise
        """
        result = await self.session.execute(
            select(MessageModel).where(MessageModel.id == message_id)
        )
        message_model = result.scalar_one_or_none()
        return self._to_domain(message_model) if message_model else None

    async def get_by_conversation_id(
        self, conversation_id: UUID, limit: Optional[int] = None
    ) -> List[Message]:
        """Retrieve all messages for a specific conversation.
        
        Messages are returned in chronological order (oldest first) to maintain
        conversation flow. An optional limit can be specified to retrieve only
        the most recent N messages.
        
        Args:
            conversation_id: UUID of the conversation
            limit: Optional maximum number of messages to retrieve
            
        Returns:
            List[Message]: List of messages in the conversation
        """
        query = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at.asc())
        )
        
        if limit is not None:
            # Get the most recent N messages, but still return them in chronological order
            # This requires a subquery to first get the latest N, then order them
            subquery = (
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation_id)
                .order_by(MessageModel.created_at.desc())
                .limit(limit)
                .subquery()
            )
            query = select(MessageModel).select_from(subquery).order_by(
                MessageModel.created_at.asc()
            )
        
        result = await self.session.execute(query)
        message_models = result.scalars().all()
        return [self._to_domain(model) for model in message_models]

    async def update(self, message: Message) -> Message:
        """Update an existing message.
        
        Typically used to update feedback or metadata. Message content
        is generally immutable after creation.
        
        Args:
            message: Domain Message entity with updated values
            
        Returns:
            Message: The updated message
        """
        result = await self.session.execute(
            select(MessageModel).where(MessageModel.id == message.id)
        )
        message_model = result.scalar_one()
        
        # Update mutable fields
        message_model.feedback = message.feedback
        message_model.metadata = message.metadata
        
        await self.session.flush()
        return self._to_domain(message_model)

    async def delete(self, message_id: UUID) -> bool:
        """Delete a message from the database.
        
        Note: Deleting a parent message will set parent_message_id to NULL
        for child messages due to the ON DELETE SET NULL constraint.
        
        Args:
            message_id: UUID of the message to delete
            
        Returns:
            bool: True if message was deleted, False if not found
        """
        result = await self.session.execute(
            select(MessageModel).where(MessageModel.id == message_id)
        )
        message_model = result.scalar_one_or_none()
        if message_model:
            await self.session.delete(message_model)
            await self.session.flush()
            return True
        return False

    @staticmethod
    def _to_domain(model: MessageModel) -> Message:
        """Convert SQLAlchemy model to domain entity.
        
        Args:
            model: SQLAlchemy MessageModel instance
            
        Returns:
            Message: Domain Message entity
        """
        return Message(
            id=model.id,
            conversation_id=model.conversation_id,
            role=model.role,
            content=model.content,
            created_at=model.created_at,
            metadata=model.metadata,
            parent_message_id=model.parent_message_id,
            feedback=model.feedback,
        )

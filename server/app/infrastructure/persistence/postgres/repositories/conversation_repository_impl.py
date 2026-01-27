"""Conversation repository implementation for PostgreSQL.

This module provides the concrete implementation of the ConversationRepository interface
using SQLAlchemy async sessions. It handles all database operations for Conversation entities.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.conversation_repository import (
    ConversationRepository,
)
from app.domain.models.conversation import Conversation
from app.infrastructure.persistence.postgres.models import ConversationModel


class ConversationRepositoryImpl(ConversationRepository):
    """PostgreSQL implementation of ConversationRepository.
    
    This class implements the ConversationRepository interface, providing concrete
    database operations for managing chat conversations.
    
    Attributes:
        session: AsyncSession instance for database operations
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.
        
        Args:
            session: SQLAlchemy async session for database operations
        """
        self.session = session

    async def create(self, conversation: Conversation) -> Conversation:
        """Create a new conversation in the database.
        
        Args:
            conversation: Domain Conversation entity to persist
            
        Returns:
            Conversation: The created conversation
        """
        conversation_model = ConversationModel(
            id=conversation.id,
            user_id=conversation.user_id,
            project_id=conversation.project_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            is_archived=conversation.is_archived,
            metadata=conversation.metadata,
        )
        self.session.add(conversation_model)
        await self.session.flush()
        return self._to_domain(conversation_model)

    async def get_by_id(self, conversation_id: UUID) -> Optional[Conversation]:
        """Retrieve a conversation by its ID.
        
        Args:
            conversation_id: UUID of the conversation to retrieve
            
        Returns:
            Optional[Conversation]: Conversation if found, None otherwise
        """
        result = await self.session.execute(
            select(ConversationModel).where(ConversationModel.id == conversation_id)
        )
        conversation_model = result.scalar_one_or_none()
        return self._to_domain(conversation_model) if conversation_model else None

    async def get_by_user_id(
        self, user_id: UUID, include_archived: bool = False
    ) -> List[Conversation]:
        """Retrieve all conversations for a specific user.
        
        By default, archived conversations are excluded. Set include_archived=True
        to retrieve all conversations including archived ones.
        
        Args:
            user_id: UUID of the user
            include_archived: Whether to include archived conversations
            
        Returns:
            List[Conversation]: List of conversations owned by the user
        """
        query = select(ConversationModel).where(ConversationModel.user_id == user_id)
        
        if not include_archived:
            query = query.where(ConversationModel.is_archived == False)
        
        query = query.order_by(ConversationModel.updated_at.desc())
        
        result = await self.session.execute(query)
        conversation_models = result.scalars().all()
        return [self._to_domain(model) for model in conversation_models]

    async def update(self, conversation: Conversation) -> Conversation:
        """Update an existing conversation.
        
        Args:
            conversation: Domain Conversation entity with updated values
            
        Returns:
            Conversation: The updated conversation
        """
        result = await self.session.execute(
            select(ConversationModel).where(ConversationModel.id == conversation.id)
        )
        conversation_model = result.scalar_one()
        
        # Update fields
        conversation_model.title = conversation.title
        conversation_model.updated_at = conversation.updated_at
        conversation_model.is_archived = conversation.is_archived
        conversation_model.metadata = conversation.metadata
        
        await self.session.flush()
        return self._to_domain(conversation_model)

    async def delete(self, conversation_id: UUID) -> bool:
        """Delete a conversation from the database.
        
        This performs a hard delete. All related messages will be cascade deleted
        due to foreign key constraints.
        
        Args:
            conversation_id: UUID of the conversation to delete
            
        Returns:
            bool: True if conversation was deleted, False if not found
        """
        result = await self.session.execute(
            select(ConversationModel).where(ConversationModel.id == conversation_id)
        )
        conversation_model = result.scalar_one_or_none()
        if conversation_model:
            await self.session.delete(conversation_model)
            await self.session.flush()
            return True
        return False

    @staticmethod
    def _to_domain(model: ConversationModel) -> Conversation:
        """Convert SQLAlchemy model to domain entity.
        
        Args:
            model: SQLAlchemy ConversationModel instance
            
        Returns:
            Conversation: Domain Conversation entity
        """
        return Conversation(
            id=model.id,
            user_id=model.user_id,
            project_id=model.project_id,
            title=model.title,
            created_at=model.created_at,
            updated_at=model.updated_at,
            is_archived=model.is_archived,
            metadata=model.metadata,
        )

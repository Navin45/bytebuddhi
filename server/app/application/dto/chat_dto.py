from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CreateConversationDTO(BaseModel):
    """DTO for creating a conversation."""

    user_id: UUID
    project_id: Optional[UUID] = None
    title: Optional[str] = None


class SendMessageDTO(BaseModel):
    """DTO for sending a message."""

    conversation_id: UUID
    content: str
    role: str = "user"
    parent_message_id: Optional[UUID] = None


class ConversationResponseDTO(BaseModel):
    """DTO for conversation response."""

    id: UUID
    user_id: UUID
    project_id: Optional[UUID]
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_archived: bool

    class Config:
        from_attributes = True


class MessageResponseDTO(BaseModel):
    """DTO for message response."""

    id: UUID
    conversation_id: UUID
    role: str
    content: str
    created_at: datetime
    parent_message_id: Optional[UUID]
    feedback: Optional[int]

    class Config:
        from_attributes = True
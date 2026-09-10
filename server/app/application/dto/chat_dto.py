from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CreateConversationDTO(BaseModel):
    """DTO for creating a conversation."""

    user_id: UUID
    project_id: UUID | None = None
    title: str | None = None


class SendMessageDTO(BaseModel):
    """DTO for sending a message."""

    conversation_id: UUID
    content: str
    role: str = "user"
    parent_message_id: UUID | None = None


class ConversationResponseDTO(BaseModel):
    """DTO for conversation response."""

    id: UUID
    user_id: UUID
    project_id: UUID | None
    title: str | None
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
    parent_message_id: UUID | None
    feedback: int | None

    class Config:
        from_attributes = True

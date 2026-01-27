"""Chat schemas for API requests and responses.

This module defines Pydantic schemas for chat-related endpoints
including conversation and message management.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.interfaces.api.schemas.common import TimestampMixin


class ConversationCreateRequest(BaseModel):
    """Request schema for creating a new conversation."""
    
    project_id: Optional[UUID] = Field(default=None, description="Associated project ID")
    title: Optional[str] = Field(default=None, max_length=500, description="Conversation title")


class ConversationUpdateRequest(BaseModel):
    """Request schema for updating a conversation."""
    
    title: Optional[str] = Field(default=None, max_length=500, description="Conversation title")
    is_archived: Optional[bool] = Field(default=None, description="Archive status")


class ConversationResponse(TimestampMixin):
    """Response schema for conversation information."""
    
    id: UUID = Field(..., description="Conversation ID")
    user_id: UUID = Field(..., description="Owner user ID")
    project_id: Optional[UUID] = Field(default=None, description="Associated project ID")
    title: str = Field(..., description="Conversation title")
    is_archived: bool = Field(..., description="Whether conversation is archived")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")
    message_count: Optional[int] = Field(default=None, description="Number of messages in conversation")
    
    class Config:
        """Pydantic configuration."""
        from_attributes = True


class MessageCreateRequest(BaseModel):
    """Request schema for sending a message in a conversation."""
    
    content: str = Field(..., min_length=1, description="Message content")
    parent_message_id: Optional[UUID] = Field(default=None, description="Parent message ID for threading")


class MessageResponse(BaseModel):
    """Response schema for message information."""
    
    id: UUID = Field(..., description="Message ID")
    conversation_id: UUID = Field(..., description="Conversation ID")
    role: str = Field(..., description="Message role (user/assistant/system)")
    content: str = Field(..., description="Message content")
    created_at: datetime = Field(..., description="Creation timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")
    parent_message_id: Optional[UUID] = Field(default=None, description="Parent message ID")
    feedback: Optional[str] = Field(default=None, description="User feedback (positive/negative)")
    
    class Config:
        """Pydantic configuration."""
        from_attributes = True


class MessageFeedbackRequest(BaseModel):
    """Request schema for providing feedback on a message."""
    
    feedback: str = Field(..., description="Feedback type (positive/negative)")


class ChatRequest(BaseModel):
    """Request schema for chat completion."""
    
    message: str = Field(..., min_length=1, description="User message")
    conversation_id: Optional[UUID] = Field(default=None, description="Existing conversation ID")
    project_id: Optional[UUID] = Field(default=None, description="Project context ID")
    stream: bool = Field(default=True, description="Whether to stream the response")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8000, description="Maximum tokens to generate")


class ChatResponse(BaseModel):
    """Response schema for chat completion."""
    
    conversation_id: UUID = Field(..., description="Conversation ID")
    message_id: UUID = Field(..., description="Assistant message ID")
    content: str = Field(..., description="Assistant response content")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Response metadata")


class StreamChunk(BaseModel):
    """Schema for streaming response chunks."""
    
    type: str = Field(..., description="Chunk type (content/metadata/error/done)")
    content: Optional[str] = Field(default=None, description="Content chunk")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata")
    error: Optional[str] = Field(default=None, description="Error message if type is error")

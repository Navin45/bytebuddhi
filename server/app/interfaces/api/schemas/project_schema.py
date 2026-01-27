"""Project schemas for API requests and responses.

This module defines Pydantic schemas for project-related endpoints
including project creation, updates, and responses.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.interfaces.api.schemas.common import TimestampMixin


class ProjectCreateRequest(BaseModel):
    """Request schema for creating a new project."""
    
    name: str = Field(..., min_length=1, max_length=200, description="Project name")
    description: Optional[str] = Field(default=None, max_length=1000, description="Project description")
    repository_url: Optional[str] = Field(default=None, max_length=500, description="Git repository URL")
    local_path: Optional[str] = Field(default=None, max_length=500, description="Local filesystem path")
    language: Optional[str] = Field(default=None, max_length=50, description="Primary programming language")
    framework: Optional[str] = Field(default=None, max_length=100, description="Framework or tech stack")


class ProjectUpdateRequest(BaseModel):
    """Request schema for updating an existing project."""
    
    name: Optional[str] = Field(default=None, min_length=1, max_length=200, description="Project name")
    description: Optional[str] = Field(default=None, max_length=1000, description="Project description")
    repository_url: Optional[str] = Field(default=None, max_length=500, description="Git repository URL")
    local_path: Optional[str] = Field(default=None, max_length=500, description="Local filesystem path")
    language: Optional[str] = Field(default=None, max_length=50, description="Primary programming language")
    framework: Optional[str] = Field(default=None, max_length=100, description="Framework or tech stack")
    is_active: Optional[bool] = Field(default=None, description="Whether project is active")


class ProjectResponse(TimestampMixin):
    """Response schema for project information."""
    
    id: UUID = Field(..., description="Project ID")
    user_id: UUID = Field(..., description="Owner user ID")
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(default=None, description="Project description")
    repository_url: Optional[str] = Field(default=None, description="Git repository URL")
    local_path: Optional[str] = Field(default=None, description="Local filesystem path")
    language: Optional[str] = Field(default=None, description="Primary programming language")
    framework: Optional[str] = Field(default=None, description="Framework or tech stack")
    last_indexed_at: Optional[datetime] = Field(default=None, description="Last indexing timestamp")
    is_active: bool = Field(..., description="Whether project is active")
    
    class Config:
        """Pydantic configuration."""
        from_attributes = True


class ProjectIndexRequest(BaseModel):
    """Request schema for triggering project indexing."""
    
    force: bool = Field(default=False, description="Force re-indexing even if recently indexed")


class ProjectIndexResponse(BaseModel):
    """Response schema for project indexing operation."""
    
    project_id: UUID = Field(..., description="Project ID")
    status: str = Field(..., description="Indexing status (started/in_progress/completed)")
    files_indexed: int = Field(default=0, description="Number of files indexed")
    chunks_created: int = Field(default=0, description="Number of code chunks created")
    embeddings_generated: int = Field(default=0, description="Number of embeddings generated")

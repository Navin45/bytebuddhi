from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class CreateProjectDTO(BaseModel):
    """DTO for creating a project."""

    user_id: UUID
    name: str
    description: Optional[str] = None
    repository_url: Optional[str] = None
    local_path: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None


class UpdateProjectDTO(BaseModel):
    """DTO for updating a project."""

    name: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None


class ProjectResponseDTO(BaseModel):
    """DTO for project response."""

    id: UUID
    user_id: UUID
    name: str
    description: Optional[str]
    repository_url: Optional[str]
    local_path: Optional[str]
    language: Optional[str]
    framework: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_indexed_at: Optional[datetime]
    is_active: bool

    class Config:
        from_attributes = True
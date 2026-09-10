from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CreateProjectDTO(BaseModel):
    """DTO for creating a project."""

    user_id: UUID
    name: str
    description: str | None = None
    repository_url: str | None = None
    local_path: str | None = None
    language: str | None = None
    framework: str | None = None


class UpdateProjectDTO(BaseModel):
    """DTO for updating a project."""

    name: str | None = None
    description: str | None = None
    language: str | None = None
    framework: str | None = None


class ProjectResponseDTO(BaseModel):
    """DTO for project response."""

    id: UUID
    user_id: UUID
    name: str
    description: str | None
    repository_url: str | None
    local_path: str | None
    language: str | None
    framework: str | None
    created_at: datetime
    updated_at: datetime
    last_indexed_at: datetime | None
    is_active: bool

    class Config:
        from_attributes = True

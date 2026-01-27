from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from app.domain.models.project import Project


class ProjectRepository(ABC):
    """Abstract repository for Project entity."""

    @abstractmethod
    async def create(self, project: Project) -> Project:
        """Create a new project."""
        pass

    @abstractmethod
    async def get_by_id(self, project_id: UUID) -> Optional[Project]:
        """Get project by ID."""
        pass

    @abstractmethod
    async def get_by_user_id(self, user_id: UUID) -> List[Project]:
        """Get all projects for a user."""
        pass

    @abstractmethod
    async def get_by_name(self, user_id: UUID, name: str) -> Optional[Project]:
        """Get project by name for a specific user."""
        pass

    @abstractmethod
    async def update(self, project: Project) -> Project:
        """Update project."""
        pass

    @abstractmethod
    async def delete(self, project_id: UUID) -> bool:
        """Delete project."""
        pass

    @abstractmethod
    async def exists_by_name(self, user_id: UUID, name: str) -> bool:
        """Check if project exists by name for a user."""
        pass
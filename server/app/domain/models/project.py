from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4


class Project:
    """Domain model for Project entity."""

    def __init__(
        self,
        id: UUID,
        user_id: UUID,
        name: str,
        description: Optional[str],
        repository_url: Optional[str],
        local_path: Optional[str],
        language: Optional[str],
        framework: Optional[str],
        created_at: datetime,
        updated_at: datetime,
        last_indexed_at: Optional[datetime],
        is_active: bool = True,
    ):
        self.id = id
        self.user_id = user_id
        self.name = name
        self.description = description
        self.repository_url = repository_url
        self.local_path = local_path
        self.language = language
        self.framework = framework
        self.created_at = created_at
        self.updated_at = updated_at
        self.last_indexed_at = last_indexed_at
        self.is_active = is_active

    @staticmethod
    def create(
        user_id: UUID,
        name: str,
        description: Optional[str] = None,
        repository_url: Optional[str] = None,
        local_path: Optional[str] = None,
        language: Optional[str] = None,
        framework: Optional[str] = None,
    ) -> "Project":
        """Factory method to create a new project."""
        now = datetime.utcnow()
        return Project(
            id=uuid4(),
            user_id=user_id,
            name=name,
            description=description,
            repository_url=repository_url,
            local_path=local_path,
            language=language,
            framework=framework,
            created_at=now,
            updated_at=now,
            last_indexed_at=None,
            is_active=True,
        )

    def mark_as_indexed(self) -> None:
        """Mark the project as indexed."""
        self.last_indexed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def update_info(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        language: Optional[str] = None,
        framework: Optional[str] = None,
    ) -> None:
        """Update project information."""
        if name:
            self.name = name
        if description:
            self.description = description
        if language:
            self.language = language
        if framework:
            self.framework = framework
        self.updated_at = datetime.utcnow()
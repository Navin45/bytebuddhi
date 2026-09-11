from datetime import datetime
from uuid import UUID, uuid4


class Project:
    """Domain model for Project entity."""

    def __init__(
        self,
        id: UUID,
        user_id: UUID,
        name: str,
        description: str | None,
        repository_url: str | None,
        local_path: str | None,
        language: str | None,
        framework: str | None,
        created_at: datetime,
        updated_at: datetime,
        last_indexed_at: datetime | None,
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
        description: str | None = None,
        repository_url: str | None = None,
        local_path: str | None = None,
        language: str | None = None,
        framework: str | None = None,
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
        name: str | None = None,
        description: str | None = None,
        language: str | None = None,
        framework: str | None = None,
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

    def mark_updated(self) -> None:
        """Mark the project as updated."""
        self.updated_at = datetime.utcnow()

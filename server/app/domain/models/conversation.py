from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4


class Conversation:
    """Domain model for Conversation entity."""

    def __init__(
        self,
        id: UUID,
        user_id: UUID,
        project_id: Optional[UUID],
        title: Optional[str],
        created_at: datetime,
        updated_at: datetime,
        is_archived: bool = False,
        metadata: Optional[dict] = None,
    ):
        self.id = id
        self.user_id = user_id
        self.project_id = project_id
        self.title = title
        self.created_at = created_at
        self.updated_at = updated_at
        self.is_archived = is_archived
        self.metadata = metadata or {}

    @staticmethod
    def create(
        user_id: UUID,
        project_id: Optional[UUID] = None,
        title: Optional[str] = None,
    ) -> "Conversation":
        """Factory method to create a new conversation."""
        now = datetime.utcnow()
        return Conversation(
            id=uuid4(),
            user_id=user_id,
            project_id=project_id,
            title=title or "New Conversation",
            created_at=now,
            updated_at=now,
            is_archived=False,
        )

    def archive(self) -> None:
        """Archive the conversation."""
        self.is_archived = True
        self.updated_at = datetime.utcnow()

    def update_title(self, title: str) -> None:
        """Update conversation title."""
        self.title = title
        self.updated_at = datetime.utcnow()
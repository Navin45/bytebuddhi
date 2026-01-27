from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4


class File:
    """Domain model for File entity."""

    def __init__(
        self,
        id: UUID,
        project_id: UUID,
        file_path: str,
        file_name: str,
        file_type: str,
        size_bytes: int,
        content_hash: str,
        last_modified: datetime,
        created_at: datetime,
        is_deleted: bool = False,
    ):
        self.id = id
        self.project_id = project_id
        self.file_path = file_path
        self.file_name = file_name
        self.file_type = file_type
        self.size_bytes = size_bytes
        self.content_hash = content_hash
        self.last_modified = last_modified
        self.created_at = created_at
        self.is_deleted = is_deleted

    @staticmethod
    def create(
        project_id: UUID,
        file_path: str,
        file_name: str,
        file_type: str,
        size_bytes: int,
        content_hash: str,
        last_modified: Optional[datetime] = None,
    ) -> "File":
        """Factory method to create a new file."""
        now = datetime.utcnow()
        return File(
            id=uuid4(),
            project_id=project_id,
            file_path=file_path,
            file_name=file_name,
            file_type=file_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
            last_modified=last_modified or now,
            created_at=now,
            is_deleted=False,
        )

    def mark_as_deleted(self) -> None:
        """Mark the file as deleted."""
        self.is_deleted = True

    def update_content(self, content_hash: str, size_bytes: int) -> None:
        """Update file content metadata."""
        self.content_hash = content_hash
        self.size_bytes = size_bytes
        self.last_modified = datetime.utcnow()

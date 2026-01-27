from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4


class CodeChunk:
    """Domain model for Code Chunk entity."""

    def __init__(
        self,
        id: UUID,
        file_id: UUID,
        project_id: UUID,
        chunk_text: str,
        chunk_index: int,
        start_line: int,
        end_line: int,
        created_at: datetime,
        updated_at: datetime,
        metadata: Optional[dict] = None,
    ):
        self.id = id
        self.file_id = file_id
        self.project_id = project_id
        self.chunk_text = chunk_text
        self.chunk_index = chunk_index
        self.start_line = start_line
        self.end_line = end_line
        self.created_at = created_at
        self.updated_at = updated_at
        self.metadata = metadata or {}

    @staticmethod
    def create(
        file_id: UUID,
        project_id: UUID,
        chunk_text: str,
        chunk_index: int,
        start_line: int,
        end_line: int,
        metadata: Optional[dict] = None,
    ) -> "CodeChunk":
        """Factory method to create a new code chunk."""
        now = datetime.utcnow()
        return CodeChunk(
            id=uuid4(),
            file_id=file_id,
            project_id=project_id,
            chunk_text=chunk_text,
            chunk_index=chunk_index,
            start_line=start_line,
            end_line=end_line,
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )

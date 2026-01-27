from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4


class Embedding:
    """Domain model for Embedding entity."""

    def __init__(
        self,
        id: UUID,
        code_chunk_id: UUID,
        project_id: UUID,
        embedding_vector: List[float],
        model_name: str,
        created_at: datetime,
        metadata: Optional[dict] = None,
    ):
        self.id = id
        self.code_chunk_id = code_chunk_id
        self.project_id = project_id
        self.embedding_vector = embedding_vector
        self.model_name = model_name
        self.created_at = created_at
        self.metadata = metadata or {}

        # Validate embedding dimension
        if len(embedding_vector) == 0:
            raise ValueError("Embedding vector cannot be empty")

    @staticmethod
    def create(
        code_chunk_id: UUID,
        project_id: UUID,
        embedding_vector: List[float],
        model_name: str,
        metadata: Optional[dict] = None,
    ) -> "Embedding":
        """Factory method to create a new embedding."""
        return Embedding(
            id=uuid4(),
            code_chunk_id=code_chunk_id,
            project_id=project_id,
            embedding_vector=embedding_vector,
            model_name=model_name,
            created_at=datetime.utcnow(),
            metadata=metadata,
        )

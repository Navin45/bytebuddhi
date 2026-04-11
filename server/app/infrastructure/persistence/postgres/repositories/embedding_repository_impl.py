"""Embedding repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.embedding_repository import (
    EmbeddingRepository,
)
from app.domain.models.embedding import Embedding
from app.infrastructure.persistence.postgres.models import EmbeddingModel


class EmbeddingRepositoryImpl(EmbeddingRepository):
    """PostgreSQL implementation of EmbeddingRepository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, embedding: Embedding) -> Embedding:
        """Create a new embedding."""
        embedding_model = EmbeddingModel(
            id=embedding.id,
            code_chunk_id=embedding.code_chunk_id,
            project_id=embedding.project_id,
            embedding=embedding.embedding_vector,
            model_name=embedding.model_name,
            created_at=embedding.created_at,
            extra_metadata=embedding.metadata or {},
        )
        self.session.add(embedding_model)
        await self.session.flush()
        return self._to_domain(embedding_model)

    async def get_by_id(self, embedding_id: UUID) -> Optional[Embedding]:
        """Get embedding by ID."""
        result = await self.session.execute(
            select(EmbeddingModel).where(EmbeddingModel.id == embedding_id)
        )
        embedding_model = result.scalar_one_or_none()
        return self._to_domain(embedding_model) if embedding_model else None

    async def get_by_code_chunk_id(self, code_chunk_id: UUID) -> Optional[Embedding]:
        """Get embedding by code chunk ID."""
        result = await self.session.execute(
            select(EmbeddingModel).where(
                EmbeddingModel.code_chunk_id == code_chunk_id
            )
        )
        embedding_model = result.scalar_one_or_none()
        return self._to_domain(embedding_model) if embedding_model else None

    async def search_similar(
        self, 
        project_id: UUID,
        query_vector: List[float],
        limit: int = 10
    ) -> List[tuple[Embedding, float]]:
        """Search for similar embeddings using vector similarity.
        
        Uses pgvector's cosine distance operator (<=>).
        Lower distance = higher similarity.
        """
        # Build query with pgvector cosine distance
        query = select(
            EmbeddingModel,
            EmbeddingModel.embedding.cosine_distance(query_vector).label("distance")
        ).where(
            EmbeddingModel.project_id == project_id
        ).order_by(
            "distance"
        ).limit(limit)
        
        result = await self.session.execute(query)
        rows = result.all()
        
        # Convert to domain models with similarity scores
        # Similarity = 1 - distance (so higher is better)
        return [
            (self._to_domain(row[0]), 1.0 - row[1])
            for row in rows
        ]

    async def delete_by_project_id(self, project_id: UUID) -> bool:
        """Delete all embeddings for a project."""
        result = await self.session.execute(
            delete(EmbeddingModel).where(EmbeddingModel.project_id == project_id)
        )
        await self.session.flush()
        return result.rowcount > 0

    @staticmethod
    def _to_domain(model: EmbeddingModel) -> Embedding:
        """Convert SQLAlchemy model to domain model."""
        return Embedding(
            id=model.id,
            code_chunk_id=model.code_chunk_id,
            project_id=model.project_id,
            embedding_vector=model.embedding,
            model_name=model.model_name,
            created_at=model.created_at,
            metadata=model.extra_metadata,
        )

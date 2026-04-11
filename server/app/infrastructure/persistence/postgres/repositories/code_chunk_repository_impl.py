"""Code chunk repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.code_chunk_repository import (
    CodeChunkRepository,
)
from app.domain.models.code_chunk import CodeChunk
from app.infrastructure.persistence.postgres.models import CodeChunkModel


class CodeChunkRepositoryImpl(CodeChunkRepository):
    """PostgreSQL implementation of CodeChunkRepository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, code_chunk: CodeChunk) -> CodeChunk:
        """Create a new code chunk."""
        chunk_model = CodeChunkModel(
            id=code_chunk.id,
            file_id=code_chunk.file_id,
            project_id=code_chunk.project_id,
            chunk_text=code_chunk.chunk_text,
            chunk_index=code_chunk.chunk_index,
            start_line=code_chunk.start_line,
            end_line=code_chunk.end_line,
            created_at=code_chunk.created_at,
            updated_at=code_chunk.updated_at,
            extra_metadata=code_chunk.metadata or {},
        )
        self.session.add(chunk_model)
        await self.session.flush()
        return self._to_domain(chunk_model)

    async def get_by_id(self, chunk_id: UUID) -> Optional[CodeChunk]:
        """Get code chunk by ID."""
        result = await self.session.execute(
            select(CodeChunkModel).where(CodeChunkModel.id == chunk_id)
        )
        chunk_model = result.scalar_one_or_none()
        return self._to_domain(chunk_model) if chunk_model else None

    async def get_by_file_id(self, file_id: UUID) -> List[CodeChunk]:
        """Get all code chunks for a file."""
        result = await self.session.execute(
            select(CodeChunkModel)
            .where(CodeChunkModel.file_id == file_id)
            .order_by(CodeChunkModel.chunk_index)
        )
        chunk_models = result.scalars().all()
        return [self._to_domain(model) for model in chunk_models]

    async def get_by_project_id(self, project_id: UUID) -> List[CodeChunk]:
        """Get all code chunks for a project."""
        result = await self.session.execute(
            select(CodeChunkModel)
            .where(CodeChunkModel.project_id == project_id)
            .order_by(CodeChunkModel.file_id, CodeChunkModel.chunk_index)
        )
        chunk_models = result.scalars().all()
        return [self._to_domain(model) for model in chunk_models]

    async def delete_by_file_id(self, file_id: UUID) -> bool:
        """Delete all code chunks for a file."""
        result = await self.session.execute(
            delete(CodeChunkModel).where(CodeChunkModel.file_id == file_id)
        )
        await self.session.flush()
        return result.rowcount > 0

    @staticmethod
    def _to_domain(model: CodeChunkModel) -> CodeChunk:
        """Convert SQLAlchemy model to domain model."""
        return CodeChunk(
            id=model.id,
            file_id=model.file_id,
            project_id=model.project_id,
            chunk_text=model.chunk_text,
            chunk_index=model.chunk_index,
            start_line=model.start_line,
            end_line=model.end_line,
            created_at=model.created_at,
            updated_at=model.updated_at,
            metadata=model.extra_metadata,
        )

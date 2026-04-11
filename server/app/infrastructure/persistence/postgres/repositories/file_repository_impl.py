"""File repository implementation."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.file_repository import FileRepository
from app.domain.models.file import File
from app.infrastructure.persistence.postgres.models import FileModel


class FileRepositoryImpl(FileRepository):
    """PostgreSQL implementation of FileRepository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, file: File) -> File:
        """Create a new file."""
        file_model = FileModel(
            id=file.id,
            project_id=file.project_id,
            file_path=file.file_path,
            file_name=file.file_name,
            file_type=file.file_type,
            size_bytes=file.size_bytes,
            content_hash=file.content_hash,
            last_modified=file.last_modified,
            created_at=file.created_at,
            is_deleted=file.is_deleted,
        )
        self.session.add(file_model)
        await self.session.flush()
        return self._to_domain(file_model)

    async def get_by_id(self, file_id: UUID) -> Optional[File]:
        """Get file by ID."""
        result = await self.session.execute(
            select(FileModel).where(FileModel.id == file_id)
        )
        file_model = result.scalar_one_or_none()
        return self._to_domain(file_model) if file_model else None

    async def get_by_project_id(
        self, 
        project_id: UUID,
        include_deleted: bool = False
    ) -> List[File]:
        """Get all files for a project."""
        query = select(FileModel).where(FileModel.project_id == project_id)
        
        if not include_deleted:
            query = query.where(FileModel.is_deleted == False)
        
        query = query.order_by(FileModel.created_at.desc())
        
        result = await self.session.execute(query)
        file_models = result.scalars().all()
        return [self._to_domain(model) for model in file_models]

    async def get_by_path(
        self, 
        project_id: UUID, 
        file_path: str
    ) -> Optional[File]:
        """Get file by project ID and file path."""
        result = await self.session.execute(
            select(FileModel).where(
                FileModel.project_id == project_id,
                FileModel.file_path == file_path
            )
        )
        file_model = result.scalar_one_or_none()
        return self._to_domain(file_model) if file_model else None

    async def update(self, file: File) -> File:
        """Update an existing file."""
        result = await self.session.execute(
            select(FileModel).where(FileModel.id == file.id)
        )
        file_model = result.scalar_one()
        
        file_model.file_path = file.file_path
        file_model.file_name = file.file_name
        file_model.file_type = file.file_type
        file_model.size_bytes = file.size_bytes
        file_model.content_hash = file.content_hash
        file_model.last_modified = file.last_modified
        file_model.is_deleted = file.is_deleted
        
        await self.session.flush()
        return self._to_domain(file_model)

    async def delete(self, file_id: UUID) -> bool:
        """Soft delete a file."""
        result = await self.session.execute(
            select(FileModel).where(FileModel.id == file_id)
        )
        file_model = result.scalar_one_or_none()
        
        if file_model:
            file_model.is_deleted = True
            await self.session.flush()
            return True
        return False

    async def exists_by_path(
        self, 
        project_id: UUID, 
        file_path: str
    ) -> bool:
        """Check if file exists at given path in project."""
        result = await self.session.execute(
            select(FileModel.id).where(
                FileModel.project_id == project_id,
                FileModel.file_path == file_path,
                FileModel.is_deleted == False
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _to_domain(model: FileModel) -> File:
        """Convert SQLAlchemy model to domain model."""
        return File(
            id=model.id,
            project_id=model.project_id,
            file_path=model.file_path,
            file_name=model.file_name,
            file_type=model.file_type,
            size_bytes=model.size_bytes,
            content_hash=model.content_hash,
            last_modified=model.last_modified,
            created_at=model.created_at,
            is_deleted=model.is_deleted,
        )

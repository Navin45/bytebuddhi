"""Local filesystem storage service implementation."""

import aiofiles
from pathlib import Path
from typing import Optional
from uuid import UUID

from app.application.ports.output.storage.file_storage_service import (
    FileStorageService,
)
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class LocalFileStorageService(FileStorageService):
    """Local filesystem implementation of FileStorageService."""

    def __init__(self, base_path: str = "./storage"):
        """Initialize local file storage.
        
        Args:
            base_path: Base directory for file storage
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, project_id: UUID, file_id: UUID) -> Path:
        """Get the storage path for a file.
        
        Args:
            project_id: Project ID
            file_id: File ID
            
        Returns:
            Path: Full path to the file
        """
        project_dir = self.base_path / "projects" / str(project_id) / "files"
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / f"{file_id}.txt"

    async def save_file(
        self, project_id: UUID, file_id: UUID, content: str, file_name: str
    ) -> str:
        """Save file content to local filesystem."""
        file_path = self._get_file_path(project_id, file_id)
        
        try:
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)
            
            logger.info(
                "File saved to local storage",
                file_id=str(file_id),
                project_id=str(project_id),
                path=str(file_path),
            )
            return str(file_path)
            
        except Exception as e:
            logger.error(
                "Failed to save file to local storage",
                file_id=str(file_id),
                error=str(e),
            )
            raise

    async def get_file(self, project_id: UUID, file_id: UUID) -> Optional[str]:
        """Retrieve file content from local filesystem."""
        file_path = self._get_file_path(project_id, file_id)
        
        if not file_path.exists():
            logger.warning(
                "File not found in local storage",
                file_id=str(file_id),
                path=str(file_path),
            )
            return None
        
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            
            logger.info(
                "File retrieved from local storage",
                file_id=str(file_id),
                size=len(content),
            )
            return content
            
        except Exception as e:
            logger.error(
                "Failed to read file from local storage",
                file_id=str(file_id),
                error=str(e),
            )
            raise

    async def delete_file(self, project_id: UUID, file_id: UUID) -> bool:
        """Delete file from local filesystem."""
        file_path = self._get_file_path(project_id, file_id)
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            logger.info(
                "File deleted from local storage",
                file_id=str(file_id),
                path=str(file_path),
            )
            return True
            
        except Exception as e:
            logger.error(
                "Failed to delete file from local storage",
                file_id=str(file_id),
                error=str(e),
            )
            raise

    async def file_exists(self, project_id: UUID, file_id: UUID) -> bool:
        """Check if file exists in local filesystem."""
        file_path = self._get_file_path(project_id, file_id)
        return file_path.exists()

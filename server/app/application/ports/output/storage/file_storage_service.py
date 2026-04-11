"""File storage service interface."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from uuid import UUID


class FileStorageService(ABC):
    """Abstract service for file storage operations."""

    @abstractmethod
    async def save_file(
        self, project_id: UUID, file_id: UUID, content: str, file_name: str
    ) -> str:
        """Save file content to storage.
        
        Args:
            project_id: Project ID
            file_id: File ID
            content: File content
            file_name: Original filename
            
        Returns:
            str: Storage path where file was saved
        """
        pass

    @abstractmethod
    async def get_file(self, project_id: UUID, file_id: UUID) -> Optional[str]:
        """Retrieve file content from storage.
        
        Args:
            project_id: Project ID
            file_id: File ID
            
        Returns:
            Optional[str]: File content if found, None otherwise
        """
        pass

    @abstractmethod
    async def delete_file(self, project_id: UUID, file_id: UUID) -> bool:
        """Delete file from storage.
        
        Args:
            project_id: Project ID
            file_id: File ID
            
        Returns:
            bool: True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def file_exists(self, project_id: UUID, file_id: UUID) -> bool:
        """Check if file exists in storage.
        
        Args:
            project_id: Project ID
            file_id: File ID
            
        Returns:
            bool: True if file exists, False otherwise
        """
        pass

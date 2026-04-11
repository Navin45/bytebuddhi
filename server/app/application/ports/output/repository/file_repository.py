"""File repository interface."""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from app.domain.models.file import File


class FileRepository(ABC):
    """Abstract repository for File entity operations."""

    @abstractmethod
    async def create(self, file: File) -> File:
        """Create a new file.
        
        Args:
            file: File domain model to create
            
        Returns:
            File: Created file
        """
        pass

    @abstractmethod
    async def get_by_id(self, file_id: UUID) -> Optional[File]:
        """Get file by ID.
        
        Args:
            file_id: File ID
            
        Returns:
            Optional[File]: File if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_project_id(
        self, 
        project_id: UUID,
        include_deleted: bool = False
    ) -> List[File]:
        """Get all files for a project.
        
        Args:
            project_id: Project ID
            include_deleted: Whether to include soft-deleted files
            
        Returns:
            List[File]: List of files in the project
        """
        pass

    @abstractmethod
    async def get_by_path(
        self, 
        project_id: UUID, 
        file_path: str
    ) -> Optional[File]:
        """Get file by project ID and file path.
        
        Args:
            project_id: Project ID
            file_path: File path within project
            
        Returns:
            Optional[File]: File if found, None otherwise
        """
        pass

    @abstractmethod
    async def update(self, file: File) -> File:
        """Update an existing file.
        
        Args:
            file: File domain model with updates
            
        Returns:
            File: Updated file
        """
        pass

    @abstractmethod
    async def delete(self, file_id: UUID) -> bool:
        """Soft delete a file.
        
        Args:
            file_id: File ID
            
        Returns:
            bool: True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def exists_by_path(
        self, 
        project_id: UUID, 
        file_path: str
    ) -> bool:
        """Check if file exists at given path in project.
        
        Args:
            project_id: Project ID
            file_path: File path to check
            
        Returns:
            bool: True if file exists, False otherwise
        """
        pass

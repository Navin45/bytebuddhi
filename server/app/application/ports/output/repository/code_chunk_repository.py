"""Code chunk repository interface."""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from app.domain.models.code_chunk import CodeChunk


class CodeChunkRepository(ABC):
    """Abstract repository for CodeChunk entity operations."""

    @abstractmethod
    async def create(self, code_chunk: CodeChunk) -> CodeChunk:
        """Create a new code chunk.
        
        Args:
            code_chunk: CodeChunk domain model to create
            
        Returns:
            CodeChunk: Created code chunk
        """
        pass

    @abstractmethod
    async def get_by_id(self, chunk_id: UUID) -> Optional[CodeChunk]:
        """Get code chunk by ID.
        
        Args:
            chunk_id: Code chunk ID
            
        Returns:
            Optional[CodeChunk]: Code chunk if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_file_id(self, file_id: UUID) -> List[CodeChunk]:
        """Get all code chunks for a file.
        
        Args:
            file_id: File ID
            
        Returns:
            List[CodeChunk]: List of code chunks in the file
        """
        pass

    @abstractmethod
    async def get_by_project_id(self, project_id: UUID) -> List[CodeChunk]:
        """Get all code chunks for a project.
        
        Args:
            project_id: Project ID
            
        Returns:
            List[CodeChunk]: List of code chunks in the project
        """
        pass

    @abstractmethod
    async def delete_by_file_id(self, file_id: UUID) -> bool:
        """Delete all code chunks for a file.
        
        Args:
            file_id: File ID
            
        Returns:
            bool: True if deleted, False otherwise
        """
        pass

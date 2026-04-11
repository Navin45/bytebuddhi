"""Embedding repository interface."""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from app.domain.models.embedding import Embedding


class EmbeddingRepository(ABC):
    """Abstract repository for Embedding entity operations."""

    @abstractmethod
    async def create(self, embedding: Embedding) -> Embedding:
        """Create a new embedding.
        
        Args:
            embedding: Embedding domain model to create
            
        Returns:
            Embedding: Created embedding
        """
        pass

    @abstractmethod
    async def get_by_id(self, embedding_id: UUID) -> Optional[Embedding]:
        """Get embedding by ID.
        
        Args:
            embedding_id: Embedding ID
            
        Returns:
            Optional[Embedding]: Embedding if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_code_chunk_id(self, code_chunk_id: UUID) -> Optional[Embedding]:
        """Get embedding by code chunk ID.
        
        Args:
            code_chunk_id: Code chunk ID
            
        Returns:
            Optional[Embedding]: Embedding if found, None otherwise
        """
        pass

    @abstractmethod
    async def search_similar(
        self, 
        project_id: UUID,
        query_vector: List[float],
        limit: int = 10
    ) -> List[tuple[Embedding, float]]:
        """Search for similar embeddings using vector similarity.
        
        Args:
            project_id: Project ID to search within
            query_vector: Query embedding vector
            limit: Maximum number of results
            
        Returns:
            List[tuple[Embedding, float]]: List of (embedding, similarity_score) tuples
        """
        pass

    @abstractmethod
    async def delete_by_project_id(self, project_id: UUID) -> bool:
        """Delete all embeddings for a project.
        
        Args:
            project_id: Project ID
            
        Returns:
            bool: True if deleted, False otherwise
        """
        pass

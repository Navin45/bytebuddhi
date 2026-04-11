"""File processing service for code chunking and embedding generation."""

import re
from typing import List
from uuid import UUID

from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.repository.code_chunk_repository import (
    CodeChunkRepository,
)
from app.application.ports.output.repository.embedding_repository import (
    EmbeddingRepository,
)
from app.domain.models.code_chunk import CodeChunk
from app.domain.models.embedding import Embedding
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class FileProcessingService:
    """Service for processing code files into chunks and embeddings."""

    def __init__(
        self,
        code_chunk_repo: CodeChunkRepository,
        embedding_repo: EmbeddingRepository,
        llm_provider: LLMProvider,
    ):
        self.code_chunk_repo = code_chunk_repo
        self.embedding_repo = embedding_repo
        self.llm_provider = llm_provider

    async def process_file(
        self,
        file_id: UUID,
        project_id: UUID,
        file_content: str,
        file_type: str,
    ) -> dict:
        """Process a file: chunk it and generate embeddings.
        
        Args:
            file_id: File ID
            project_id: Project ID
            file_content: File content text
            file_type: File type (e.g., 'python', 'javascript')
            
        Returns:
            dict: Processing results with chunk and embedding counts
        """
        logger.info(
            "Processing file",
            file_id=str(file_id),
            project_id=str(project_id),
            file_type=file_type,
        )

        # Delete existing chunks and embeddings for this file
        await self.code_chunk_repo.delete_by_file_id(file_id)

        # Chunk the file
        chunks = await self._chunk_file(file_id, project_id, file_content, file_type)
        
        if not chunks:
            logger.warning("No chunks created for file", file_id=str(file_id))
            return {"chunks_created": 0, "embeddings_created": 0}

        # Generate embeddings for each chunk
        embeddings_created = 0
        for chunk in chunks:
            try:
                embedding = await self._generate_embedding(chunk)
                if embedding:
                    embeddings_created += 1
            except Exception as e:
                logger.error(
                    "Failed to generate embedding",
                    chunk_id=str(chunk.id),
                    error=str(e),
                )

        logger.info(
            "File processing complete",
            file_id=str(file_id),
            chunks_created=len(chunks),
            embeddings_created=embeddings_created,
        )

        return {
            "chunks_created": len(chunks),
            "embeddings_created": embeddings_created,
        }

    async def _chunk_file(
        self,
        file_id: UUID,
        project_id: UUID,
        file_content: str,
        file_type: str,
    ) -> List[CodeChunk]:
        """Chunk file content into semantic code blocks.
        
        For now, uses simple line-based chunking. In the future,
        this can be enhanced with tree-sitter for syntax-aware chunking.
        
        Args:
            file_id: File ID
            project_id: Project ID
            file_content: File content
            file_type: File type
            
        Returns:
            List[CodeChunk]: Created code chunks
        """
        chunks = []
        lines = file_content.split('\n')
        
        # Simple chunking: split by functions/classes or every N lines
        chunk_size = 50  # lines per chunk
        overlap = 5  # overlapping lines
        
        current_line = 0
        chunk_index = 0
        
        while current_line < len(lines):
            end_line = min(current_line + chunk_size, len(lines))
            chunk_lines = lines[current_line:end_line]
            chunk_text = '\n'.join(chunk_lines)
            
            # Skip empty chunks
            if chunk_text.strip():
                chunk = CodeChunk.create(
                    file_id=file_id,
                    project_id=project_id,
                    chunk_text=chunk_text,
                    chunk_index=chunk_index,
                    start_line=current_line + 1,  # 1-indexed
                    end_line=end_line,
                    metadata={
                        "file_type": file_type,
                        "total_lines": len(lines),
                    }
                )
                
                created_chunk = await self.code_chunk_repo.create(chunk)
                chunks.append(created_chunk)
                chunk_index += 1
            
            # Move to next chunk with overlap
            current_line += chunk_size - overlap
        
        return chunks

    async def _generate_embedding(self, chunk: CodeChunk) -> Embedding:
        """Generate embedding for a code chunk.
        
        Args:
            chunk: Code chunk to embed
            
        Returns:
            Embedding: Created embedding
        """
        try:
            # Generate embedding using LLM provider
            embedding_vector = await self.llm_provider.create_embedding(
                chunk.chunk_text
            )
            
            # Create embedding domain model
            embedding = Embedding.create(
                code_chunk_id=chunk.id,
                project_id=chunk.project_id,
                embedding_vector=embedding_vector,
                model_name=self.llm_provider.model_name,
                metadata={
                    "chunk_index": chunk.chunk_index,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                }
            )
            
            # Save to database
            created_embedding = await self.embedding_repo.create(embedding)
            return created_embedding
            
        except Exception as e:
            logger.error(
                "Failed to generate embedding",
                chunk_id=str(chunk.id),
                error=str(e),
            )
            raise

    async def search_code(
        self,
        project_id: UUID,
        query: str,
        limit: int = 10,
    ) -> List[dict]:
        """Search for relevant code chunks using semantic search.
        
        Args:
            project_id: Project ID to search within
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List[dict]: Search results with code chunks and scores
        """
        logger.info(
            "Searching code",
            project_id=str(project_id),
            query=query[:50],
            limit=limit,
        )

        # Generate embedding for the query
        query_vector = await self.llm_provider.create_embedding(query)
        
        # Search for similar embeddings
        results = await self.embedding_repo.search_similar(
            project_id=project_id,
            query_vector=query_vector,
            limit=limit,
        )
        
        # Format results with chunk information
        search_results = []
        for embedding, score in results:
            # Get the corresponding code chunk
            chunk = await self.code_chunk_repo.get_by_id(embedding.code_chunk_id)
            if chunk:
                search_results.append({
                    "chunk_id": str(chunk.id),
                    "chunk_text": chunk.chunk_text,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "similarity_score": score,
                    "file_id": str(chunk.file_id),
                })
        
        logger.info(
            "Search complete",
            project_id=str(project_id),
            results_found=len(search_results),
        )
        
        return search_results

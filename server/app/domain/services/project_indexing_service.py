"""Project indexing domain service.

This service coordinates the business logic for indexing a project's
codebase, including file parsing, chunking, and embedding generation.
This is domain logic that spans multiple entities (Project, File, CodeChunk).
"""

from typing import List
from uuid import UUID

from app.domain.models.code_chunk import CodeChunk
from app.domain.models.file import File
from app.domain.models.project import Project
from app.domain.value_objects.file_path import FilePath
from app.domain.value_objects.language import Language


class ProjectIndexingService:
    """Domain service for project indexing operations.
    
    This service encapsulates the business rules for indexing a project,
    which involves coordinating multiple domain entities and enforcing
    indexing policies.
    
    Domain services are used when business logic:
    - Doesn't naturally belong to a single entity
    - Requires coordination between multiple entities
    - Represents a significant domain operation
    """

    @staticmethod
    def should_index_file(file_path: FilePath, allowed_extensions: List[str]) -> bool:
        """Determine if a file should be indexed.
        
        Business rule: Only index files with allowed extensions and
        exclude certain directories (node_modules, .git, etc.).
        
        Args:
            file_path: Path to the file
            allowed_extensions: List of allowed file extensions
            
        Returns:
            bool: True if file should be indexed
        """
        # Check extension
        if file_path.extension not in allowed_extensions:
            return False
        
        # Exclude common directories
        excluded_dirs = {
            "node_modules",
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            "dist",
            "build",
            ".next",
            "target",
        }
        
        path_parts = file_path.value.split("/")
        if any(excluded in path_parts for excluded in excluded_dirs):
            return False
        
        return True

    @staticmethod
    def calculate_chunk_size(language: Language) -> int:
        """Calculate optimal chunk size based on language.
        
        Business rule: Different languages have different optimal
        chunk sizes based on their typical structure.
        
        Args:
            language: Programming language
            
        Returns:
            int: Optimal chunk size in lines
        """
        # Language-specific chunk sizes
        chunk_sizes = {
            "python": 50,
            "javascript": 40,
            "typescript": 40,
            "java": 60,
            "go": 45,
            "rust": 50,
            "cpp": 55,
            "c": 55,
        }
        
        return chunk_sizes.get(language.name, 50)

    @staticmethod
    def create_chunks_from_file(
        file: File,
        content: str,
        chunk_size: int,
    ) -> List[CodeChunk]:
        """Create code chunks from file content.
        
        Business rule: Split file into overlapping chunks for better
        context preservation during retrieval.
        
        Args:
            file: File entity
            content: File content
            chunk_size: Size of each chunk in lines
            
        Returns:
            List[CodeChunk]: List of code chunks
        """
        lines = content.split("\n")
        chunks = []
        overlap = chunk_size // 4  # 25% overlap
        
        chunk_index = 0
        start = 0
        
        while start < len(lines):
            end = min(start + chunk_size, len(lines))
            chunk_text = "\n".join(lines[start:end])
            
            # Create chunk
            chunk = CodeChunk.create(
                file_id=file.id,
                project_id=file.project_id,
                chunk_text=chunk_text,
                chunk_index=chunk_index,
                start_line=start + 1,  # 1-indexed
                end_line=end,
            )
            
            chunks.append(chunk)
            
            # Move to next chunk with overlap
            start = end - overlap if end < len(lines) else end
            chunk_index += 1
        
        return chunks

    @staticmethod
    def validate_project_for_indexing(project: Project) -> None:
        """Validate that a project is ready for indexing.
        
        Business rule: Project must be active and have a valid path.
        
        Args:
            project: Project to validate
            
        Raises:
            ValueError: If project is not valid for indexing
        """
        if not project.is_active:
            raise ValueError(f"Project {project.name} is not active")
        
        if not project.local_path:
            raise ValueError(f"Project {project.name} has no local path")

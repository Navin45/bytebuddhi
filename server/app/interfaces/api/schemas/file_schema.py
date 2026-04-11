"""File API schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.interfaces.api.schemas.common import TimestampMixin


class FileUploadRequest(BaseModel):
    """Request schema for file upload."""
    
    file_name: str = Field(..., max_length=255, description="Name of the file")
    file_path: str = Field(..., max_length=1000, description="Relative path within project")
    file_type: str = Field(..., max_length=50, description="File type/extension (e.g., 'python', 'javascript')")
    content: str = Field(..., description="File content (text)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "file_name": "main.py",
                "file_path": "src/main.py",
                "file_type": "python",
                "content": "def hello():\n    print('Hello World')"
            }
        }


class FileResponse(TimestampMixin):
    """Response schema for file information."""
    
    id: UUID = Field(..., description="File ID")
    project_id: UUID = Field(..., description="Project ID")
    file_name: str = Field(..., description="File name")
    file_path: str = Field(..., description="File path within project")
    file_type: str = Field(..., description="File type")
    size_bytes: int = Field(..., description="File size in bytes")
    content_hash: str = Field(..., description="SHA-256 hash of file content")
    last_modified: datetime = Field(..., description="Last modification timestamp")
    is_deleted: bool = Field(..., description="Whether file is soft-deleted")
    
    class Config:
        """Pydantic configuration."""
        from_attributes = True


class FileListResponse(BaseModel):
    """Response schema for file list."""
    
    files: list[FileResponse] = Field(..., description="List of files")
    total: int = Field(..., description="Total number of files")


class FileProcessingResponse(BaseModel):
    """Response schema for file processing."""
    
    file_id: UUID = Field(..., description="File ID")
    chunks_created: int = Field(..., description="Number of code chunks created")
    embeddings_created: int = Field(..., description="Number of embeddings created")
    message: str = Field(..., description="Status message")


class CodeSearchRequest(BaseModel):
    """Request schema for code search."""
    
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of results")


class CodeSearchResult(BaseModel):
    """Individual search result."""
    
    chunk_id: UUID = Field(..., description="Code chunk ID")
    file_id: UUID = Field(..., description="File ID")
    chunk_text: str = Field(..., description="Code chunk text")
    start_line: int = Field(..., description="Start line number")
    end_line: int = Field(..., description="End line number")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Similarity score (0-1)")


class CodeSearchResponse(BaseModel):
    """Response schema for code search."""
    
    results: list[CodeSearchResult] = Field(..., description="Search results")
    total: int = Field(..., description="Total number of results")
    query: str = Field(..., description="Original search query")


class FileContentResponse(BaseModel):
    """Response schema for file content retrieval."""
    
    file_id: UUID = Field(..., description="File ID")
    file_name: str = Field(..., description="File name")
    file_path: str = Field(..., description="File path within project")
    file_type: str = Field(..., description="File type")
    content: str = Field(..., description="File content")
    size_bytes: int = Field(..., description="File size in bytes")


class BatchDeleteRequest(BaseModel):
    """Request schema for batch file deletion."""
    
    file_ids: list[UUID] = Field(..., min_length=1, max_length=100, description="File IDs to delete")


class BatchDeleteResponse(BaseModel):
    """Response schema for batch file deletion."""
    
    deleted: list[UUID] = Field(..., description="Successfully deleted file IDs")
    not_found: list[UUID] = Field(..., description="File IDs that were not found")
    total_deleted: int = Field(..., description="Total number of files deleted")


class GitSyncResponse(BaseModel):
    """Response schema for Git repository sync."""
    
    project_id: UUID = Field(..., description="Project ID")
    files_discovered: int = Field(..., description="Total files found in repository")
    files_added: int = Field(..., description="New files indexed")
    files_updated: int = Field(..., description="Files updated")
    files_unchanged: int = Field(..., description="Files with no changes")
    message: str = Field(..., description="Sync status message")

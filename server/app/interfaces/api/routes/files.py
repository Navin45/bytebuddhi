"""File API routes.

This module provides endpoints for file management including
file upload, retrieval, deletion, processing, and semantic search.
"""

import hashlib
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.output.llm.llm_provider import LLMProvider
from app.application.ports.output.repository.code_chunk_repository import (
    CodeChunkRepository,
)
from app.application.ports.output.repository.embedding_repository import (
    EmbeddingRepository,
)
from app.application.ports.output.repository.file_repository import FileRepository
from app.application.ports.output.repository.project_repository import ProjectRepository
from app.application.ports.output.storage.file_storage_service import (
    FileStorageService,
)
from app.domain.models.file import File
from app.domain.models.user import User
from app.domain.services.file_processing_service import FileProcessingService
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings
from app.interfaces.api.dependencies import (
    get_code_chunk_repository,
    get_embedding_provider,
    get_embedding_repository,
    get_file_repository,
    get_file_storage_service,
    get_project_repository,
)
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.file_schema import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    CodeSearchResponse,
    CodeSearchResult,
    FileContentResponse,
    FileListResponse,
    FileProcessingResponse,
    FileResponse,
    FileUploadRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/projects/{project_id}/files", tags=["Files"])


@router.post("/upload", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: UUID,
    request: FileUploadRequest,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
    storage_service: FileStorageService = Depends(get_file_storage_service),
):
    """Upload a file to a project.
    
    Validates file type and size, calculates content hash for deduplication,
    and stores file metadata in the database.
    
    Args:
        project_id: Project ID
        request: File upload data
        current_user: Authenticated user
        file_repo: File repository instance
        project_repo: Project repository instance
        
    Returns:
        FileResponse: Uploaded file information
        
    Raises:
        HTTPException: If project not found, unauthorized, or validation fails
    """
    # Verify project exists and user owns it
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to upload files to this project",
        )
    
    # Validate file type
    if request.file_type not in settings.allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{request.file_type}' not allowed. Allowed types: {settings.allowed_extensions}",
        )
    
    # Calculate file size and validate
    content_bytes = request.content.encode('utf-8')
    size_bytes = len(content_bytes)
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    
    if size_bytes > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size ({size_bytes} bytes) exceeds maximum ({max_size_bytes} bytes)",
        )
    
    # Calculate content hash (SHA-256)
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    
    # Check if file already exists at this path
    if await file_repo.exists_by_path(project_id, request.file_path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"File already exists at path '{request.file_path}'",
        )
    
    # Create file
    file = File.create(
        project_id=project_id,
        file_path=request.file_path,
        file_name=request.file_name,
        file_type=request.file_type,
        size_bytes=size_bytes,
        content_hash=content_hash,
        last_modified=datetime.utcnow(),
    )
    
    created_file = await file_repo.create(file)
    
    # Save file content to storage
    try:
        await storage_service.save_file(
            project_id=project_id,
            file_id=created_file.id,
            content=request.content,
            file_name=request.file_name,
        )
    except Exception as e:
        # Rollback: Delete file metadata if storage fails
        await file_repo.delete(created_file.id)
        logger.error(
            "Failed to save file content to storage",
            file_id=str(created_file.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save file content",
        )
    
    logger.info(
        "File uploaded",
        file_id=str(created_file.id),
        project_id=str(project_id),
        user_id=str(current_user.id),
        file_path=request.file_path,
    )
    
    return FileResponse.model_validate(created_file)


@router.get("", response_model=FileListResponse)
async def list_files(
    project_id: UUID,
    include_deleted: bool = False,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """List all files in a project.
    
    Returns files ordered by creation date (most recent first).
    
    Args:
        project_id: Project ID
        include_deleted: Whether to include soft-deleted files
        current_user: Authenticated user
        file_repo: File repository instance
        project_repo: Project repository instance
        
    Returns:
        FileListResponse: List of files with total count
        
    Raises:
        HTTPException: If project not found or user doesn't own it
    """
    # Verify project exists and user owns it
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this project",
        )
    
    files = await file_repo.get_by_project_id(project_id, include_deleted=include_deleted)
    
    return FileListResponse(
        files=[FileResponse.model_validate(f) for f in files],
        total=len(files),
    )


@router.get("/{file_id}", response_model=FileResponse)
async def get_file(
    project_id: UUID,
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """Get file metadata by ID.
    
    Args:
        project_id: Project ID  
        file_id: File ID
        current_user: Authenticated user
        file_repo: File repository instance
        project_repo: Project repository instance
        
    Returns:
        FileResponse: File information
        
    Raises:
        HTTPException: If file/project not found or unauthorized
    """
    # Verify project exists and user owns it
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this project",
        )
    
    file = await file_repo.get_by_id(file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    
    # Verify file belongs to this project
    if file.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in this project",
        )
    
    return FileResponse.model_validate(file)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    project_id: UUID,
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
    storage_service: FileStorageService = Depends(get_file_storage_service),
):
    """Soft delete a file.
    
    Sets the file's is_deleted flag to True. The file remains in the database
    but won't appear in standard file listings.
    
    Args:
        project_id: Project ID
        file_id: File ID
        current_user: Authenticated user
        file_repo: File repository instance
        project_repo: Project repository instance
        
    Raises:
        HTTPException: If file/project not found or unauthorized
    """
    # Verify project exists and user owns it
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this project",
        )
    
    file = await file_repo.get_by_id(file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    
    # Verify file belongs to this project
    if file.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in this project",
        )
    
    # Soft delete in database
    await file_repo.delete(file_id)
    
    # Delete file content from storage
    try:
        await storage_service.delete_file(project_id, file_id)
    except Exception as e:
        logger.warning(
            "Failed to delete file from storage (soft delete still successful)",
            file_id=str(file_id),
            error=str(e),
        )
    
    logger.info(
        "File deleted",
        file_id=str(file_id),
        project_id=str(project_id),
        user_id=str(current_user.id),
    )


@router.post("/{file_id}/process", response_model=FileProcessingResponse)
async def process_file(
    project_id: UUID,
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
    code_chunk_repo: CodeChunkRepository = Depends(get_code_chunk_repository),
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repository),
    llm_provider: LLMProvider = Depends(get_embedding_provider),
    storage_service: FileStorageService = Depends(get_file_storage_service),
):
    """Process a file to generate code chunks and embeddings.
    
    This endpoint:
    1. Splits the file into semantic code chunks
    2. Generates embeddings for each chunk using OpenAI
    3. Stores chunks and embeddings for semantic search
    
    Args:
        project_id: Project ID
        file_id: File ID to process
        current_user: Authenticated user
        file_repo: File repository
        project_repo: Project repository
        code_chunk_repo: Code chunk repository
        embedding_repo: Embedding repository
        llm_provider: LLM provider for embeddings
        
    Returns:
        FileProcessingResponse: Processing results
        
    Raises:
        HTTPException: If file/project not found or unauthorized
    """
    # Verify project exists and user owns it
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to process files in this project",
        )
    
    # Get file
    file = await file_repo.get_by_id(file_id)
    if not file or file.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    
    # Retrieve file content from storage
    file_content = await storage_service.get_file(project_id, file_id)
    if not file_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File content not found in storage",
        )
    
    # Create processing service
    processing_service = FileProcessingService(
        code_chunk_repo=code_chunk_repo,
        embedding_repo=embedding_repo,
        llm_provider=llm_provider,
    )
    
    # Process file
    result = await processing_service.process_file(
        file_id=file_id,
        project_id=project_id,
        file_content=file_content,
        file_type=file.file_type,
    )
    
    return FileProcessingResponse(
        file_id=file_id,
        chunks_created=result["chunks_created"],
        embeddings_created=result["embeddings_created"],
        message=f"File processed successfully: {result['chunks_created']} chunks, {result['embeddings_created']} embeddings",
    )


@router.get("/../search", response_model=CodeSearchResponse)
async def search_code(
    project_id: UUID,
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
    code_chunk_repo: CodeChunkRepository = Depends(get_code_chunk_repository),
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repository),
    llm_provider: LLMProvider = Depends(get_embedding_provider),
):
    """Search for code using semantic similarity.
    
    Uses vector embeddings to find code chunks similar to the query.
    
    Args:
        project_id: Project ID to search within
        query: Search query text
        limit: Maximum number of results (1-50)
        current_user: Authenticated user
        project_repo: Project repository
        code_chunk_repo: Code chunk repository
        embedding_repo: Embedding repository
        llm_provider: LLM provider for query embedding
        
    Returns:
        CodeSearchResponse: Search results with similarity scores
        
    Raises:
        HTTPException: If project not found or unauthorized
    """
    # Verify project exists and user owns it
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to search this project",
        )
    
    # Validate limit
    if not (1 <= limit <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit must be between 1 and 50",
        )
    
    # Create processing service and search
    processing_service = FileProcessingService(
        code_chunk_repo=code_chunk_repo,
        embedding_repo=embedding_repo,
        llm_provider=llm_provider,
    )
    
    results = await processing_service.search_code(
        project_id=project_id,
        query=query,
        limit=limit,
    )
    
    # Convert to response format
    search_results = [
        CodeSearchResult(
            chunk_id=UUID(r["chunk_id"]),
            file_id=UUID(r["file_id"]),
            chunk_text=r["chunk_text"],
            start_line=r["start_line"],
            end_line=r["end_line"],
            similarity_score=r["similarity_score"],
        )
        for r in results
    ]
    
    return CodeSearchResponse(
        results=search_results,
        total=len(search_results),
        query=query,
    )


@router.get("/{file_id}/content", response_model=FileContentResponse)
async def get_file_content(
    project_id: UUID,
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
    storage_service: FileStorageService = Depends(get_file_storage_service),
):
    """Retrieve the raw content of a file.

    Returns the stored text content of a file alongside its metadata.

    Args:
        project_id: Project ID
        file_id: File ID
        current_user: Authenticated user
        file_repo: File repository
        project_repo: Project repository
        storage_service: File storage service

    Returns:
        FileContentResponse: File metadata and content

    Raises:
        HTTPException: If project/file not found, unauthorized, or content missing
    """
    # Verify project ownership
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Fetch file metadata
    file = await file_repo.get_by_id(file_id)
    if not file or file.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    # Fetch content from storage
    content = await storage_service.get_file(project_id, file_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File content not found in storage",
        )

    logger.info("File content retrieved", file_id=str(file_id), project_id=str(project_id))

    return FileContentResponse(
        file_id=file.id,
        file_name=file.file_name,
        file_path=file.file_path,
        file_type=file.file_type,
        content=content,
        size_bytes=file.size_bytes,
    )


@router.post("/batch-delete", response_model=BatchDeleteResponse)
async def batch_delete_files(
    project_id: UUID,
    request: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    file_repo: FileRepository = Depends(get_file_repository),
    project_repo: ProjectRepository = Depends(get_project_repository),
    storage_service: FileStorageService = Depends(get_file_storage_service),
):
    """Delete multiple files in a single request.

    Soft-deletes all specified files that belong to the project and
    removes their content from local storage.

    Args:
        project_id: Project ID
        request: List of file IDs to delete
        current_user: Authenticated user
        file_repo: File repository
        project_repo: Project repository
        storage_service: File storage service

    Returns:
        BatchDeleteResponse: Summary of deleted and not-found files

    Raises:
        HTTPException: If project not found or unauthorized
    """
    # Verify project ownership
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    deleted: list[UUID] = []
    not_found: list[UUID] = []

    for file_id in request.file_ids:
        file = await file_repo.get_by_id(file_id)

        if not file or file.project_id != project_id:
            not_found.append(file_id)
            continue

        # Soft-delete in DB
        await file_repo.delete(file_id)

        # Remove content from storage (best-effort)
        try:
            await storage_service.delete_file(project_id, file_id)
        except Exception as e:
            logger.warning(
                "Storage delete failed during batch delete",
                file_id=str(file_id),
                error=str(e),
            )

        deleted.append(file_id)

    logger.info(
        "Batch delete completed",
        project_id=str(project_id),
        deleted=len(deleted),
        not_found=len(not_found),
    )

    return BatchDeleteResponse(
        deleted=deleted,
        not_found=not_found,
        total_deleted=len(deleted),
    )

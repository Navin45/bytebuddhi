"""Project API routes.

This module provides endpoints for project management including
creation, retrieval, updating, deletion of projects, and local
directory sync.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.output.repository.file_repository import FileRepository
from app.application.ports.output.repository.project_repository import ProjectRepository
from app.application.ports.output.storage.file_storage_service import FileStorageService
from app.domain.exceptions.project_exceptions import ProjectNotFoundException
from app.domain.models.file import File
from app.domain.models.project import Project
from app.domain.models.user import User
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings
from app.interfaces.api.dependencies import (
    get_file_repository,
    get_file_storage_service,
    get_project_repository,
)
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.common import IDResponse
from app.interfaces.api.schemas.file_schema import GitSyncResponse
from app.interfaces.api.schemas.project_schema import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """Create a new project.
    
    Creates a new project for the authenticated user. Project names
    must be unique per user.
    
    Args:
        request: Project creation data
        current_user: Authenticated user
        project_repo: Project repository instance
        
    Returns:
        ProjectResponse: Created project information
        
    Raises:
        HTTPException: If project name already exists for user
    """
    # Check if project name already exists for this user
    existing = await project_repo.get_by_name(current_user.id, request.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Project with name '{request.name}' already exists",
        )
    
    # Create project
    project = Project.create(
        user_id=current_user.id,
        name=request.name,
        description=request.description,
        repository_url=request.repository_url,
        local_path=request.local_path,
        language=request.language,
        framework=request.framework,
    )
    
    created_project = await project_repo.create(project)
    
    logger.info(
        "Project created",
        project_id=str(created_project.id),
        user_id=str(current_user.id),
        name=created_project.name,
    )
    
    return ProjectResponse.model_validate(created_project)


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """List all projects for the authenticated user.
    
    Returns all projects owned by the current user, ordered by
    creation date (most recent first).
    
    Args:
        current_user: Authenticated user
        project_repo: Project repository instance
        
    Returns:
        List[ProjectResponse]: List of user's projects
    """
    projects = await project_repo.get_by_user_id(current_user.id)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """Get a specific project by ID.
    
    Retrieves project details. User must own the project.
    
    Args:
        project_id: Project ID
        current_user: Authenticated user
        project_repo: Project repository instance
        
    Returns:
        ProjectResponse: Project information
        
    Raises:
        HTTPException: If project not found or user doesn't own it
    """
    project = await project_repo.get_by_id(project_id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Check ownership
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this project",
        )
    
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """Update a project.
    
    Updates project fields. Only provided fields are updated.
    User must own the project.
    
    Args:
        project_id: Project ID
        request: Project update data
        current_user: Authenticated user
        project_repo: Project repository instance
        
    Returns:
        ProjectResponse: Updated project information
        
    Raises:
        HTTPException: If project not found or user doesn't own it
    """
    project = await project_repo.get_by_id(project_id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Check ownership
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this project",
        )
    
    # Update fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    
    project.mark_updated()
    updated_project = await project_repo.update(project)
    
    logger.info(
        "Project updated",
        project_id=str(project_id),
        user_id=str(current_user.id),
    )
    
    return ProjectResponse.model_validate(updated_project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
):
    """Delete a project.
    
    Permanently deletes a project and all associated data (files,
    embeddings, etc.). User must own the project.
    
    Args:
        project_id: Project ID
        current_user: Authenticated user
        project_repo: Project repository instance
        
    Raises:
        HTTPException: If project not found or user doesn't own it
    """
    project = await project_repo.get_by_id(project_id)
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Check ownership
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this project",
        )
    
    await project_repo.delete(project_id)
    
    logger.info(
        "Project deleted",
        project_id=str(project_id),
        user_id=str(current_user.id),
    )


@router.post("/{project_id}/sync", response_model=GitSyncResponse)
async def sync_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    project_repo: ProjectRepository = Depends(get_project_repository),
    file_repo: FileRepository = Depends(get_file_repository),
    storage_service: FileStorageService = Depends(get_file_storage_service),
):
    """Sync a project by scanning its local directory.

    Walks the project's configured ``local_path``, reads every file
    with an allowed extension, and compares content hashes with what is
    already stored:

    - **New** files are created in the repository and saved to storage.
    - **Changed** files (different content hash) are updated.
    - **Unchanged** files are skipped.

    Args:
        project_id: Project ID to sync
        current_user: Authenticated user
        project_repo: Project repository
        file_repo: File repository
        storage_service: File storage service

    Returns:
        GitSyncResponse: Summary of the sync operation

    Raises:
        HTTPException: If project not found / not owned / no local_path set
    """
    # Verify ownership
    project = await project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    if not project.local_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no local_path configured.",
        )

    root = Path(project.local_path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"local_path '{project.local_path}' does not exist or is not a directory",
        )

    allowed = set(settings.allowed_extensions)
    excluded_dirs = {
        "node_modules", ".git", ".venv", "venv", "__pycache__",
        ".pytest_cache", "dist", "build", ".next", "target",
    }

    # Build lookup of existing files keyed by relative path
    existing_files = await file_repo.get_by_project_id(project_id)
    existing_by_path: dict[str, File] = {f.file_path: f for f in existing_files}

    files_added = 0
    files_updated = 0
    files_unchanged = 0
    files_discovered = 0

    for disk_path in root.rglob("*"):
        if not disk_path.is_file():
            continue

        # Skip excluded directories
        if set(disk_path.parts) & excluded_dirs:
            continue

        if disk_path.suffix not in allowed:
            continue

        files_discovered += 1
        relative_path = str(disk_path.relative_to(root))

        try:
            content = disk_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Could not read file during sync", path=str(disk_path), error=str(e))
            continue

        content_bytes = content.encode("utf-8")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        size_bytes = len(content_bytes)
        file_type = disk_path.suffix.lstrip(".")

        if relative_path in existing_by_path:
            existing = existing_by_path[relative_path]
            if existing.content_hash == content_hash:
                files_unchanged += 1
                continue

            # Content changed: update metadata
            existing.content_hash = content_hash
            existing.size_bytes = size_bytes
            existing.last_modified = datetime.utcnow()
            await file_repo.update(existing)
            await storage_service.save_file(
                project_id=project_id,
                file_id=existing.id,
                content=content,
                file_name=disk_path.name,
            )
            files_updated += 1
        else:
            new_file = File.create(
                project_id=project_id,
                file_path=relative_path,
                file_name=disk_path.name,
                file_type=file_type,
                size_bytes=size_bytes,
                content_hash=content_hash,
                last_modified=datetime.utcnow(),
            )
            created = await file_repo.create(new_file)
            await storage_service.save_file(
                project_id=project_id,
                file_id=created.id,
                content=content,
                file_name=disk_path.name,
            )
            files_added += 1

    # Mark project as indexed
    project.mark_as_indexed()
    await project_repo.update(project)

    logger.info(
        "Project sync completed",
        project_id=str(project_id),
        added=files_added,
        updated=files_updated,
        unchanged=files_unchanged,
    )

    return GitSyncResponse(
        project_id=project_id,
        files_discovered=files_discovered,
        files_added=files_added,
        files_updated=files_updated,
        files_unchanged=files_unchanged,
        message=(
            f"Sync complete: {files_added} added, {files_updated} updated, "
            f"{files_unchanged} unchanged out of {files_discovered} discovered."
        ),
    )

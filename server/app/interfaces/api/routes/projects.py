"""Project API routes.

This module provides endpoints for project management including
creation, retrieval, updating, and deletion of projects.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.output.repository.project_repository import ProjectRepository
from app.domain.exceptions.project_exceptions import ProjectNotFoundException
from app.domain.models.project import Project
from app.domain.models.user import User
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.dependencies import get_project_repository
from app.interfaces.api.middleware import get_current_user
from app.interfaces.api.schemas.common import IDResponse
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

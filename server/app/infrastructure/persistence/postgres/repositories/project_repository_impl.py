"""Project repository implementation for PostgreSQL.

This module provides the concrete implementation of the ProjectRepository interface
using SQLAlchemy async sessions. It handles all database operations for Project entities
including CRUD operations and project-specific queries.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.output.repository.project_repository import ProjectRepository
from app.domain.models.project import Project
from app.infrastructure.persistence.postgres.models import ProjectModel


class ProjectRepositoryImpl(ProjectRepository):
    """PostgreSQL implementation of ProjectRepository.
    
    This class implements the ProjectRepository interface defined in the application layer,
    providing concrete database operations using SQLAlchemy. It follows the repository pattern
    to abstract database access from business logic.
    
    Attributes:
        session: AsyncSession instance for database operations
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.
        
        Args:
            session: SQLAlchemy async session for database operations
        """
        self.session = session

    async def create(self, project: Project) -> Project:
        """Create a new project in the database.
        
        Args:
            project: Domain Project entity to persist
            
        Returns:
            Project: The created project with database-generated fields
        """
        project_model = ProjectModel(
            id=project.id,
            user_id=project.user_id,
            name=project.name,
            description=project.description,
            repository_url=project.repository_url,
            local_path=project.local_path,
            language=project.language,
            framework=project.framework,
            created_at=project.created_at,
            updated_at=project.updated_at,
            last_indexed_at=project.last_indexed_at,
            is_active=project.is_active,
        )
        self.session.add(project_model)
        await self.session.flush()
        return self._to_domain(project_model)

    async def get_by_id(self, project_id: UUID) -> Optional[Project]:
        """Retrieve a project by its ID.
        
        Args:
            project_id: UUID of the project to retrieve
            
        Returns:
            Optional[Project]: Project if found, None otherwise
        """
        result = await self.session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project_model = result.scalar_one_or_none()
        return self._to_domain(project_model) if project_model else None

    async def get_by_user_id(self, user_id: UUID) -> List[Project]:
        """Retrieve all projects for a specific user.
        
        Args:
            user_id: UUID of the user
            
        Returns:
            List[Project]: List of projects owned by the user
        """
        result = await self.session.execute(
            select(ProjectModel)
            .where(ProjectModel.user_id == user_id)
            .order_by(ProjectModel.created_at.desc())
        )
        project_models = result.scalars().all()
        return [self._to_domain(model) for model in project_models]

    async def get_by_name(self, user_id: UUID, name: str) -> Optional[Project]:
        """Retrieve a project by name for a specific user.
        
        Project names are unique per user, so this returns at most one project.
        
        Args:
            user_id: UUID of the user
            name: Name of the project
            
        Returns:
            Optional[Project]: Project if found, None otherwise
        """
        result = await self.session.execute(
            select(ProjectModel).where(
                ProjectModel.user_id == user_id,
                ProjectModel.name == name
            )
        )
        project_model = result.scalar_one_or_none()
        return self._to_domain(project_model) if project_model else None

    async def update(self, project: Project) -> Project:
        """Update an existing project.
        
        Args:
            project: Domain Project entity with updated values
            
        Returns:
            Project: The updated project
        """
        result = await self.session.execute(
            select(ProjectModel).where(ProjectModel.id == project.id)
        )
        project_model = result.scalar_one()
        
        # Update fields
        project_model.name = project.name
        project_model.description = project.description
        project_model.repository_url = project.repository_url
        project_model.local_path = project.local_path
        project_model.language = project.language
        project_model.framework = project.framework
        project_model.updated_at = project.updated_at
        project_model.last_indexed_at = project.last_indexed_at
        project_model.is_active = project.is_active
        
        await self.session.flush()
        return self._to_domain(project_model)

    async def delete(self, project_id: UUID) -> bool:
        """Delete a project from the database.
        
        This performs a hard delete. All related entities (files, embeddings, etc.)
        will be cascade deleted due to foreign key constraints.
        
        Args:
            project_id: UUID of the project to delete
            
        Returns:
            bool: True if project was deleted, False if not found
        """
        result = await self.session.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )
        project_model = result.scalar_one_or_none()
        if project_model:
            await self.session.delete(project_model)
            await self.session.flush()
            return True
        return False

    async def exists_by_name(self, user_id: UUID, name: str) -> bool:
        """Check if a project with the given name exists for a user.
        
        This is useful for validation before creating a new project.
        
        Args:
            user_id: UUID of the user
            name: Name to check
            
        Returns:
            bool: True if project exists, False otherwise
        """
        result = await self.session.execute(
            select(ProjectModel.id).where(
                ProjectModel.user_id == user_id,
                ProjectModel.name == name
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _to_domain(model: ProjectModel) -> Project:
        """Convert SQLAlchemy model to domain entity.
        
        This method maps the database model to the domain model, ensuring
        the domain layer remains independent of infrastructure concerns.
        
        Args:
            model: SQLAlchemy ProjectModel instance
            
        Returns:
            Project: Domain Project entity
        """
        return Project(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            description=model.description,
            repository_url=model.repository_url,
            local_path=model.local_path,
            language=model.language,
            framework=model.framework,
            created_at=model.created_at,
            updated_at=model.updated_at,
            last_indexed_at=model.last_indexed_at,
            is_active=model.is_active,
        )

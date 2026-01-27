from app.application.dto.project_dto import CreateProjectDTO, ProjectResponseDTO
from app.application.ports.output.repository.project_repository import ProjectRepository
from app.domain.exceptions.project_exceptions import ProjectAlreadyExistsException
from app.domain.models.project import Project


class CreateProjectUseCase:
    """Use case for creating a project."""

    def __init__(self, project_repository: ProjectRepository):
        self.project_repository = project_repository

    async def execute(self, dto: CreateProjectDTO) -> ProjectResponseDTO:
        """Execute the use case."""
        # Check if project already exists
        if await self.project_repository.exists_by_name(dto.user_id, dto.name):
            raise ProjectAlreadyExistsException(dto.name)

        # Create domain model
        project = Project.create(
            user_id=dto.user_id,
            name=dto.name,
            description=dto.description,
            repository_url=dto.repository_url,
            local_path=dto.local_path,
            language=dto.language,
            framework=dto.framework,
        )

        # Save to repository
        saved_project = await self.project_repository.create(project)

        # Return DTO
        return ProjectResponseDTO(
            id=saved_project.id,
            user_id=saved_project.user_id,
            name=saved_project.name,
            description=saved_project.description,
            repository_url=saved_project.repository_url,
            local_path=saved_project.local_path,
            language=saved_project.language,
            framework=saved_project.framework,
            created_at=saved_project.created_at,
            updated_at=saved_project.updated_at,
            last_indexed_at=saved_project.last_indexed_at,
            is_active=saved_project.is_active,
        )
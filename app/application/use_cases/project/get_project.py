"""Use case fetching a single project with ownership enforcement."""

from uuid import UUID

from app.application.dto.project_dto import ProjectResponseDTO
from app.application.ports.output.repository.project_repository import ProjectRepository
from app.domain.exceptions.project_exceptions import ProjectNotFoundException, ProjectOwnershipException


class GetProjectUseCase:
    """Load a project only when it belongs to the trusted user."""

    def __init__(self, project_repository: ProjectRepository) -> None:
        self.project_repository = project_repository

    async def execute(self, user_id: UUID, project_id: UUID) -> ProjectResponseDTO:
        project = await self.project_repository.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundException(str(project_id))
        if project.user_id != user_id:
            raise ProjectOwnershipException(str(project_id), str(user_id))
        return ProjectResponseDTO(
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

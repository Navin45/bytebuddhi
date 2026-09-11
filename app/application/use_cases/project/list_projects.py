"""Use case listing projects owned by a trusted user."""

from uuid import UUID

from app.application.dto.project_dto import ProjectResponseDTO
from app.application.ports.output.repository.project_repository import ProjectRepository


class ListProjectsUseCase:
    """Return projects belonging to the authenticated principal."""

    def __init__(self, project_repository: ProjectRepository) -> None:
        self.project_repository = project_repository

    async def execute(self, user_id: UUID) -> list[ProjectResponseDTO]:
        projects = await self.project_repository.get_by_user_id(user_id)
        return [
            ProjectResponseDTO(
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
            for project in projects
        ]

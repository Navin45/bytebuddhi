"""Resolve a local filesystem path to an owned project. Does not create workspaces."""

from pathlib import Path
from uuid import UUID

from app.application.ports.output.repository.project_repository import ProjectRepository
from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError


class ResolveProjectByLocalPathUseCase:
    """Map an explicit local path onto a project already bound to that path.

    Workspace containment remains WorkspaceResolutionService's responsibility.
    This use case only selects which authorized project the CLI asked for.
    """

    def __init__(self, project_repository: ProjectRepository, workspace_mode: str) -> None:
        self.project_repository = project_repository
        self.workspace_mode = workspace_mode.strip().lower()

    async def execute(self, user_id: UUID, local_path: str) -> UUID:
        if self.workspace_mode != "local":
            raise WorkspaceBoundaryError("Selecting a project by local path is only allowed when WORKSPACE_MODE=local")
        target = Path(local_path).resolve()
        projects = await self.project_repository.get_by_user_id(user_id)
        for project in projects:
            if not project.local_path:
                continue
            if Path(project.local_path).resolve() == target:
                return project.id
        raise WorkspaceBoundaryError(
            f"No project owned by this user is bound to '{target}'",
            path=str(target),
        )

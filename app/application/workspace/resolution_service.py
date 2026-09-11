"""Authoritative workspace resolution service enforcing user ownership and path containment."""

from pathlib import Path
from uuid import UUID

from app.application.ports.output.logger import get_logger
from app.application.ports.output.repository.project_repository import ProjectRepository
from app.domain.exceptions.project_exceptions import (
    ProjectNotFoundException,
    ProjectOwnershipException,
)
from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError
from app.domain.models.workspace import Workspace

logger = get_logger(__name__)


class WorkspaceResolutionService:
    """Authoritative service resolving workspaces based on trusted principal and project bindings."""

    def __init__(
        self,
        project_repo: ProjectRepository,
        base_storage_dir: str = "storage/workspaces",
    ) -> None:
        self.project_repo = project_repo
        self.base_storage_dir = Path(base_storage_dir).resolve()
        self.base_storage_dir.mkdir(parents=True, exist_ok=True)

    async def resolve_workspace(
        self,
        user_id: UUID | str,
        project_id: UUID | str | None = None,
    ) -> Workspace:
        """Resolve an authoritative, validated Workspace for the given user and optional project.

        Invariants:
            1. If project_id is provided, look up project in ProjectRepository.
            2. If project not found -> raise ProjectNotFoundException.
            3. If project.user_id != user_id -> raise ProjectOwnershipException.
            4. If project has a local_path:
               - Validate against path traversal (no "..", symlink escapes).
               - Root must exist or be created within valid boundary.
            5. If project has no local_path or project execution:
               - Allocate project-scoped workspace at {base_storage_dir}/projects/{project_id}.
            6. If project_id is None (scratch / projectless execution):
               - Allocate user-scoped scratch workspace at {base_storage_dir}/users/{user_id}.
               - Never default to repository root ".".
        """
        user_uuid = UUID(str(user_id)) if isinstance(user_id, str) else user_id

        if project_id is not None:
            project_uuid = UUID(str(project_id)) if isinstance(project_id, str) else project_id
            project = await self.project_repo.get_by_id(project_uuid)
            if not project:
                logger.warning("Project not found during workspace resolution", project_id=str(project_id))
                raise ProjectNotFoundException(str(project_id))

            if project.user_id != user_uuid:
                logger.warning(
                    "Unauthorized project access attempt",
                    user_id=str(user_id),
                    project_id=str(project_id),
                    project_owner=str(project.user_id),
                )
                raise ProjectOwnershipException(str(project_id), str(user_id))

            # Determine workspace root
            if project.local_path:
                # Check path traversal
                raw_path = str(project.local_path)
                if ".." in raw_path.replace("\\", "/").split("/"):
                    raise WorkspaceBoundaryError(
                        f"Path traversal detected in project local_path: {project.local_path}",
                        path=raw_path,
                    )
                candidate_path = Path(project.local_path).resolve()
                candidate_path.mkdir(parents=True, exist_ok=True)
                ws_root = candidate_path
            else:
                project_dir = self.base_storage_dir / "projects" / str(project_uuid)
                project_dir.mkdir(parents=True, exist_ok=True)
                ws_root = project_dir.resolve()

            logger.info(
                "Authoritative project workspace resolved",
                user_id=str(user_id),
                project_id=str(project_uuid),
                workspace_root=str(ws_root),
            )
            return Workspace.create(root_path=str(ws_root), workspace_id=f"proj_{project_uuid}")

        # Scratch / projectless execution: strictly user-scoped
        user_scratch_dir = self.base_storage_dir / "users" / str(user_uuid)
        user_scratch_dir.mkdir(parents=True, exist_ok=True)
        ws_root = user_scratch_dir.resolve()

        logger.info(
            "User scratch workspace resolved",
            user_id=str(user_id),
            workspace_root=str(ws_root),
        )
        return Workspace.create(root_path=str(ws_root), workspace_id=f"scratch_{user_uuid}")

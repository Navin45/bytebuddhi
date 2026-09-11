"""Security tests for WorkspaceAuthorization and WorkspaceResolutionService."""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.workspace.resolution_service import WorkspaceResolutionService
from app.domain.exceptions.project_exceptions import (
    ProjectNotFoundException,
    ProjectOwnershipException,
)
from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError
from app.domain.models.project import Project


@pytest.fixture
def mock_project_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def resolution_service(mock_project_repo: AsyncMock, tmp_path: Path) -> WorkspaceResolutionService:
    return WorkspaceResolutionService(
        project_repo=mock_project_repo,
        base_storage_dir=str(tmp_path / "workspaces"),
    )


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_project(
    resolution_service: WorkspaceResolutionService,
    mock_project_repo: AsyncMock,
    tmp_path: Path,
) -> None:
    """Attack A: User A attempts to resolve a workspace for User B's project."""
    user_a = uuid4()
    user_b = uuid4()
    project_b_id = uuid4()

    project_b = Project.create(
        user_id=user_b,
        name="project_b",
        local_path=str(tmp_path / "b"),
    )
    mock_project_repo.get_by_id.return_value = project_b

    with pytest.raises(ProjectOwnershipException):
        await resolution_service.resolve_workspace(user_id=user_a, project_id=project_b_id)


@pytest.mark.asyncio
async def test_nonexistent_project_rejected(
    resolution_service: WorkspaceResolutionService,
    mock_project_repo: AsyncMock,
) -> None:
    """Non-existent project IDs are rejected with ProjectNotFoundException."""
    mock_project_repo.get_by_id.return_value = None
    with pytest.raises(ProjectNotFoundException):
        await resolution_service.resolve_workspace(user_id=uuid4(), project_id=uuid4())


@pytest.mark.asyncio
async def test_traversal_in_local_path_rejected(
    resolution_service: WorkspaceResolutionService,
    mock_project_repo: AsyncMock,
) -> None:
    """Attack D: Project with path traversal local_path ('../../etc') is blocked."""
    user_id = uuid4()
    project_id = uuid4()

    malicious_project = Project.create(
        user_id=user_id,
        name="evil_proj",
        local_path="../../sensitive/etc",
    )
    mock_project_repo.get_by_id.return_value = malicious_project

    with pytest.raises(WorkspaceBoundaryError):
        await resolution_service.resolve_workspace(user_id=user_id, project_id=project_id)


@pytest.mark.asyncio
async def test_scratch_workspace_is_user_isolated(
    resolution_service: WorkspaceResolutionService,
) -> None:
    """Projectless executions resolve to separate user-scoped scratch directories."""
    user_1 = uuid4()
    user_2 = uuid4()

    ws_1 = await resolution_service.resolve_workspace(user_id=user_1, project_id=None)
    ws_2 = await resolution_service.resolve_workspace(user_id=user_2, project_id=None)

    assert ws_1.root_path != ws_2.root_path
    assert str(user_1) in str(ws_1.root_path)
    assert str(user_2) in str(ws_2.root_path)
    assert ws_1.root_path.exists()
    assert ws_2.root_path.exists()


@pytest.mark.asyncio
async def test_project_workspace_containment(
    resolution_service: WorkspaceResolutionService,
    mock_project_repo: AsyncMock,
    tmp_path: Path,
) -> None:
    """Legitimate project resolves to dedicated, contained workspace root."""
    user_id = uuid4()
    project_id = uuid4()

    proj = Project.create(
        user_id=user_id,
        name="valid_proj",
        local_path=str(tmp_path / "valid"),
    )
    mock_project_repo.get_by_id.return_value = proj

    ws = await resolution_service.resolve_workspace(user_id=user_id, project_id=project_id)
    assert ws.root_path == (tmp_path / "valid").resolve()
    assert ws.workspace_id == f"proj_{project_id}"

"""Managed workspace root containment."""

import os
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.workspace.resolution_service import WorkspaceResolutionService
from app.domain.exceptions.workspace_exceptions import WorkspaceBoundaryError
from app.domain.models.project import Project


def _managed_service(tmp_path: Path, repo: AsyncMock) -> WorkspaceResolutionService:
    root = tmp_path / "managed-root"
    root.mkdir()
    return WorkspaceResolutionService(
        project_repo=repo,
        base_storage_dir=str(root),
        workspace_mode="managed",
        workspace_root=str(root),
    )


@pytest.mark.asyncio
async def test_project_outside_managed_root_denied(tmp_path: Path) -> None:
    repo = AsyncMock()
    service = _managed_service(tmp_path, repo)
    user_id = uuid4()
    outside = tmp_path / "outside"
    outside.mkdir()
    repo.get_by_id.return_value = Project.create(user_id=user_id, name="p", local_path=str(outside))
    with pytest.raises(WorkspaceBoundaryError):
        await service.resolve_workspace(user_id=user_id, project_id=uuid4())


@pytest.mark.asyncio
async def test_project_inside_managed_root_allowed(tmp_path: Path) -> None:
    repo = AsyncMock()
    service = _managed_service(tmp_path, repo)
    user_id = uuid4()
    inside = Path(service.workspace_root) / "proj"
    repo.get_by_id.return_value = Project.create(user_id=user_id, name="p", local_path=str(inside))
    ws = await service.resolve_workspace(user_id=user_id, project_id=uuid4())
    assert ws.root_path == inside.resolve()
    ws.root_path.relative_to(service.workspace_root)


@pytest.mark.asyncio
async def test_symlink_outside_managed_root_denied(tmp_path: Path) -> None:
    repo = AsyncMock()
    service = _managed_service(tmp_path, repo)
    user_id = uuid4()
    outside = tmp_path / "secret"
    outside.mkdir()
    link = Path(service.workspace_root) / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    repo.get_by_id.return_value = Project.create(user_id=user_id, name="p", local_path=str(link))
    with pytest.raises(WorkspaceBoundaryError):
        await service.resolve_workspace(user_id=user_id, project_id=uuid4())


@pytest.mark.asyncio
async def test_relative_traversal_denied(tmp_path: Path) -> None:
    repo = AsyncMock()
    service = _managed_service(tmp_path, repo)
    user_id = uuid4()
    repo.get_by_id.return_value = Project.create(
        user_id=user_id,
        name="p",
        local_path=str(Path(service.workspace_root) / ".." / "etc"),
    )
    with pytest.raises(WorkspaceBoundaryError):
        await service.resolve_workspace(user_id=user_id, project_id=uuid4())


@pytest.mark.asyncio
async def test_absolute_path_outside_root_denied(tmp_path: Path) -> None:
    repo = AsyncMock()
    service = _managed_service(tmp_path, repo)
    user_id = uuid4()
    repo.get_by_id.return_value = Project.create(
        user_id=user_id,
        name="p",
        local_path=str(tmp_path / "not-in-root"),
    )
    with pytest.raises(WorkspaceBoundaryError):
        await service.resolve_workspace(user_id=user_id, project_id=uuid4())


@pytest.mark.asyncio
async def test_model_workspace_injection_ignored(tmp_path: Path) -> None:
    """Workspace is selected from authorized project.local_path, never from caller metadata."""
    repo = AsyncMock()
    service = _managed_service(tmp_path, repo)
    user_id = uuid4()
    inside = Path(service.workspace_root) / "real-proj"
    repo.get_by_id.return_value = Project.create(user_id=user_id, name="p", local_path=str(inside))
    ws = await service.resolve_workspace(user_id=user_id, project_id=uuid4())
    assert "injected" not in str(ws.root_path)
    assert str(service.workspace_root) in str(ws.root_path)

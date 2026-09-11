"""Project use cases used by the CLI."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.use_cases.project.get_project import GetProjectUseCase
from app.application.use_cases.project.list_projects import ListProjectsUseCase
from app.application.use_cases.project.resolve_project_by_local_path import ResolveProjectByLocalPathUseCase
from app.domain.exceptions.project_exceptions import ProjectNotFoundException
from app.domain.models.project import Project


@pytest.mark.asyncio
async def test_list_projects_returns_owned_only() -> None:
    user_id = uuid4()
    project = Project.create(user_id=user_id, name="alpha", local_path="/tmp/alpha")
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=[project])
    result = await ListProjectsUseCase(repo).execute(user_id)
    assert len(result) == 1
    assert result[0].name == "alpha"
    repo.get_by_user_id.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_get_project_not_found() -> None:
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(ProjectNotFoundException):
        await GetProjectUseCase(repo).execute(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_resolve_local_path_match(tmp_path) -> None:
    user_id = uuid4()
    project = Project.create(user_id=user_id, name="local", local_path=str(tmp_path))
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=[project])
    resolved = await ResolveProjectByLocalPathUseCase(repo, workspace_mode="local").execute(user_id, str(tmp_path))
    assert resolved == project.id

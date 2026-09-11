"""Security tests for concurrent project execution and isolation."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.workspace.resolution_service import WorkspaceResolutionService
from app.domain.models.project import Project
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


@pytest.mark.asyncio
async def test_concurrent_project_workspace_and_artifact_isolation(tmp_path: Path) -> None:
    """Run concurrent tasks across two projects and verify complete isolation."""
    mock_repo = AsyncMock()
    user_a = uuid4()
    user_b = uuid4()
    proj_a_id = uuid4()
    proj_b_id = uuid4()

    proj_a = Project.create(user_id=user_a, name="proj_a")
    proj_b = Project.create(user_id=user_b, name="proj_b")

    mock_repo.get_by_id.side_effect = lambda pid: proj_a if pid == proj_a_id else proj_b

    ws_service = WorkspaceResolutionService(
        project_repo=mock_repo,
        base_storage_dir=str(tmp_path / "workspaces"),
    )
    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts")

    async def execute_project_a():
        ws = await ws_service.resolve_workspace(user_id=user_a, project_id=proj_a_id)
        # Write file in workspace
        file_path = ws.resolve_path("data.txt")
        file_path.write_text("Data for Project A", encoding="utf-8")
        # Save artifact
        await artifact_store.save_artifact("summary.txt", "Project A summary", project_id=str(proj_a_id))
        await asyncio.sleep(0.01)
        # Verify read back
        content = file_path.read_text(encoding="utf-8")
        art = await artifact_store.get_artifact("summary.txt", project_id=str(proj_a_id))
        return ws, content, art

    async def execute_project_b():
        ws = await ws_service.resolve_workspace(user_id=user_b, project_id=proj_b_id)
        # Write file in workspace
        file_path = ws.resolve_path("data.txt")
        file_path.write_text("Data for Project B", encoding="utf-8")
        # Save artifact
        await artifact_store.save_artifact("summary.txt", "Project B summary", project_id=str(proj_b_id))
        await asyncio.sleep(0.01)
        # Verify read back
        content = file_path.read_text(encoding="utf-8")
        art = await artifact_store.get_artifact("summary.txt", project_id=str(proj_b_id))
        return ws, content, art

    (ws_a, content_a, art_a), (ws_b, content_b, art_b) = await asyncio.gather(
        execute_project_a(),
        execute_project_b(),
    )

    # Workspaces must be separate paths
    assert ws_a.root_path != ws_b.root_path
    assert content_a == "Data for Project A"
    assert content_b == "Data for Project B"

    # Artifacts must be completely separate
    assert art_a == "Project A summary"
    assert art_b == "Project B summary"

    # Cross-project artifact leakage must fail
    assert await artifact_store.get_artifact("summary.txt", project_id=str(proj_a_id)) == "Project A summary"
    assert await artifact_store.get_artifact("summary.txt", project_id=str(proj_b_id)) == "Project B summary"


@pytest.mark.asyncio
async def test_concurrent_three_project_isolation(tmp_path: Path) -> None:
    mock_repo = AsyncMock()
    users = [uuid4(), uuid4(), uuid4()]
    project_ids = [uuid4(), uuid4(), uuid4()]
    projects = [
        Project.create(user_id=users[i], name=f"proj_{i}", local_path=str(tmp_path / f"p{i}")) for i in range(3)
    ]
    id_map = dict(zip(project_ids, projects, strict=True))
    mock_repo.get_by_id.side_effect = lambda pid: id_map[pid]
    ws_service = WorkspaceResolutionService(
        project_repo=mock_repo,
        base_storage_dir=str(tmp_path / "workspaces"),
    )
    artifact_store = LocalArtifactStore(base_dir=tmp_path / "artifacts")

    async def run_one(index: int) -> str:
        ws = await ws_service.resolve_workspace(user_id=users[index], project_id=project_ids[index])
        marker = f"payload-{index}"
        ws.resolve_path("data.txt").write_text(marker, encoding="utf-8")
        await artifact_store.save_artifact("summary.txt", marker, project_id=str(project_ids[index]))
        return marker

    results = await asyncio.gather(run_one(0), run_one(1), run_one(2))
    assert results == ["payload-0", "payload-1", "payload-2"]
    for i in range(3):
        assert await artifact_store.get_artifact("summary.txt", project_id=str(project_ids[i])) == f"payload-{i}"
        for j in range(3):
            if i == j:
                continue
            assert await artifact_store.get_artifact("summary.txt", project_id=str(project_ids[i])) != (
                await artifact_store.get_artifact("summary.txt", project_id=str(project_ids[j]))
            )

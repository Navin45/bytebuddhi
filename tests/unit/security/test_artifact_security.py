"""Security tests for ArtifactStore project namespace isolation and access control."""

from pathlib import Path

import pytest

from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


@pytest.fixture
def artifact_store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(base_dir=tmp_path / "artifacts")


@pytest.mark.asyncio
async def test_project_a_cannot_read_project_b_artifact(artifact_store: LocalArtifactStore) -> None:
    """Project B cannot retrieve an artifact created by Project A."""
    proj_a = "project_alpha_123"
    proj_b = "project_beta_456"

    # Save artifact in Project A namespace
    await artifact_store.save_artifact(
        artifact_id="confidential_plan.txt",
        content="Project A confidential financial data",
        project_id=proj_a,
    )

    # Verify Project A can read it
    content_a = await artifact_store.get_artifact("confidential_plan.txt", project_id=proj_a)
    assert content_a == "Project A confidential financial data"

    # Project B querying the same artifact_id must receive None
    content_b = await artifact_store.get_artifact("confidential_plan.txt", project_id=proj_b)
    assert content_b is None

    # Global unauthenticated caller querying must also receive None
    content_global = await artifact_store.get_artifact("confidential_plan.txt")
    assert content_global is None


@pytest.mark.asyncio
async def test_artifact_id_does_not_bypass_authorization(artifact_store: LocalArtifactStore) -> None:
    """Knowing an artifact ID alone is not sufficient to access an artifact from another project."""
    secret_id = "secret_report_999.log"
    await artifact_store.save_artifact(
        artifact_id=secret_id,
        content="Secret vulnerability report",
        project_id="proj_victim",
    )

    # Attacker tries to access by ID without the correct project context
    assert await artifact_store.get_artifact(secret_id, project_id="proj_attacker") is None
    assert await artifact_store.get_artifact(secret_id, project_id=None) is None
    assert await artifact_store.artifact_exists(secret_id, project_id="proj_attacker") is False

    # Legitimate owner accesses successfully
    assert await artifact_store.get_artifact(secret_id, project_id="proj_victim") == "Secret vulnerability report"

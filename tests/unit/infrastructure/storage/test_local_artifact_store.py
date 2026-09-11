"""Unit tests for LocalArtifactStore."""

import pytest

from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


@pytest.fixture
def artifact_store(tmp_path) -> LocalArtifactStore:
    return LocalArtifactStore(base_dir=tmp_path / "artifacts")


@pytest.mark.asyncio
async def test_save_and_get_text_artifact(artifact_store: LocalArtifactStore):
    saved_path = await artifact_store.save_artifact("log_123.txt", "Execution completed successfully.")
    assert "log_123.txt" in saved_path

    exists = await artifact_store.artifact_exists("log_123.txt")
    assert exists

    content = await artifact_store.get_artifact("log_123.txt")
    assert content == "Execution completed successfully."


@pytest.mark.asyncio
async def test_save_and_get_binary_artifact(artifact_store: LocalArtifactStore):
    binary_data = b"\x00\x01\x02\xff\xfe"
    await artifact_store.save_artifact("binary.bin", binary_data)

    retrieved = await artifact_store.get_artifact("binary.bin")
    assert retrieved == binary_data


@pytest.mark.asyncio
async def test_get_nonexistent_artifact(artifact_store: LocalArtifactStore):
    retrieved = await artifact_store.get_artifact("missing.txt")
    assert retrieved is None


@pytest.mark.asyncio
async def test_delete_artifact(artifact_store: LocalArtifactStore):
    await artifact_store.save_artifact("to_delete.txt", "temp data")
    assert await artifact_store.artifact_exists("to_delete.txt")

    deleted = await artifact_store.delete_artifact("to_delete.txt")
    assert deleted
    assert not await artifact_store.artifact_exists("to_delete.txt")

    # Second delete returns False
    assert not await artifact_store.delete_artifact("to_delete.txt")

"""Unit tests for PostgresMemoryStore."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType
from app.infrastructure.persistence.postgres.models import MemoryItemModel
from app.infrastructure.persistence.postgres.repositories.postgres_memory_store import (
    PostgresMemoryStore,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_save_new_memory_item(mock_session: AsyncMock):
    # Mock scalar_one_or_none returning None (item doesn't exist)
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = exec_res

    store = PostgresMemoryStore(mock_session)
    item = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_123",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Prefer pytest over unittest",
        importance=0.9,
    )

    result = await store.save(item)
    assert result.id == item.id
    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_memory_item_found(mock_session: AsyncMock):
    now = datetime.now(UTC)
    fake_model = MemoryItemModel(
        id="mem_test1",
        scope="project",
        scope_id="proj_1",
        memory_type="project",
        content="Project uses uv package manager",
        source="system",
        importance=0.8,
        created_at=now,
        updated_at=now,
        last_accessed_at=now,
        expires_at=None,
        extra_metadata={"arch": "hex"},
        embedding=None,
    )

    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = fake_model
    mock_session.execute.return_value = exec_res

    store = PostgresMemoryStore(mock_session)
    item = await store.get("mem_test1", scope=MemoryScope.PROJECT, scope_id="proj_1")

    assert item is not None
    assert item.id == "mem_test1"
    assert item.scope == MemoryScope.PROJECT
    assert item.scope_id == "proj_1"
    assert item.content == "Project uses uv package manager"
    assert item.metadata["arch"] == "hex"


@pytest.mark.asyncio
async def test_get_memory_item_not_found(mock_session: AsyncMock):
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = exec_res

    store = PostgresMemoryStore(mock_session)
    item = await store.get("nonexistent", scope=MemoryScope.USER, scope_id="user_1")
    assert item is None


@pytest.mark.asyncio
async def test_delete_memory_item(mock_session: AsyncMock):
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = "mem_test1"
    mock_session.execute.return_value = exec_res

    store = PostgresMemoryStore(mock_session)
    deleted = await store.delete("mem_test1", scope=MemoryScope.USER, scope_id="user_1")

    assert deleted
    mock_session.flush.assert_called_once()

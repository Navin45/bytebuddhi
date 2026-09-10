"""Unit tests for SqliteMemoryStore with WAL mode, scope boundaries, and expiration."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.domain.models.memory import MemoryItem, MemoryScope, MemoryType
from app.infrastructure.persistence.sqlite.sqlite_memory_store import SqliteMemoryStore


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SqliteMemoryStore:
    db_file = tmp_path / "test_operational.db"
    return SqliteMemoryStore(db_file)


@pytest.mark.asyncio
async def test_sqlite_wal_mode_enabled(sqlite_store: SqliteMemoryStore):
    with sqlite_store._get_connection() as conn:
        cursor = conn.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"


@pytest.mark.asyncio
async def test_save_and_get_memory(sqlite_store: SqliteMemoryStore):
    item = MemoryItem.create(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_100",
        memory_type=MemoryType.WORKING,
        content="Current plan step 1",
        importance=0.7,
        metadata={"step": 1},
    )

    saved = await sqlite_store.save(item)
    assert saved.id == item.id

    retrieved = await sqlite_store.get(item.id, scope=MemoryScope.AGENT_RUN, scope_id="run_100")
    assert retrieved is not None
    assert retrieved.id == item.id
    assert retrieved.content == "Current plan step 1"
    assert retrieved.importance == 0.7
    assert retrieved.metadata["step"] == 1


@pytest.mark.asyncio
async def test_scope_isolation_in_get_and_delete(sqlite_store: SqliteMemoryStore):
    item = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_alice",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Alice private notes",
    )
    await sqlite_store.save(item)

    # Bob attempts to get Alice's memory -> None
    cross_get = await sqlite_store.get(item.id, scope=MemoryScope.USER, scope_id="user_bob")
    assert cross_get is None

    # Bob attempts to delete Alice's memory -> False
    cross_delete = await sqlite_store.delete(item.id, scope=MemoryScope.USER, scope_id="user_bob")
    assert not cross_delete

    # Alice can delete it -> True
    alice_delete = await sqlite_store.delete(item.id, scope=MemoryScope.USER, scope_id="user_alice")
    assert alice_delete


@pytest.mark.asyncio
async def test_expiration_and_cleanup(sqlite_store: SqliteMemoryStore):
    past = datetime.now(UTC) - timedelta(minutes=5)
    future = datetime.now(UTC) + timedelta(minutes=10)

    expired_item = MemoryItem.create(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_1",
        memory_type=MemoryType.WORKING,
        content="Expired scratchpad",
        expires_at=past,
    )
    active_item = MemoryItem.create(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_1",
        memory_type=MemoryType.WORKING,
        content="Active scratchpad",
        expires_at=future,
    )

    await sqlite_store.save(expired_item)
    await sqlite_store.save(active_item)

    # Search should automatically exclude expired memories
    results = await sqlite_store.search(scope=MemoryScope.AGENT_RUN, scope_id="run_1")
    assert len(results) == 1
    assert results[0].id == active_item.id

    # Cleanup expired
    cleaned = await sqlite_store.cleanup_expired()
    assert cleaned == 1


@pytest.mark.asyncio
async def test_concurrent_reads_and_writes(sqlite_store: SqliteMemoryStore):
    async def writer(idx: int):
        item = MemoryItem.create(
            scope=MemoryScope.CONVERSATION,
            scope_id="conv_shared",
            memory_type=MemoryType.WORKING,
            content=f"Observation {idx}",
            importance=0.5,
        )
        return await sqlite_store.save(item)

    async def reader():
        return await sqlite_store.search(scope=MemoryScope.CONVERSATION, scope_id="conv_shared", limit=50)

    # Concurrently write 20 items
    tasks = [writer(i) for i in range(20)]
    written = await asyncio.gather(*tasks)
    assert len(written) == 20

    # Concurrently read
    read_tasks = [reader() for _ in range(5)]
    read_results = await asyncio.gather(*read_tasks)
    for res in read_results:
        assert len(res) == 20

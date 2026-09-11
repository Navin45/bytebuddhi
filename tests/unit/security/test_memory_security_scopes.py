"""Security test suite verifying strict memory scope isolation and boundaries."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.memory.orchestrator import MemoryOrchestrator
from app.domain.models.memory import (
    ExecutionObservation,
    MemoryItem,
    MemoryScope,
    MemoryType,
)
from app.infrastructure.persistence.sqlite.sqlite_memory_store import SqliteMemoryStore
from app.infrastructure.storage.local_artifact_store import LocalArtifactStore


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(tmp_path / "security_test.db")


@pytest.mark.asyncio
async def test_user_scope_isolation(sqlite_store: SqliteMemoryStore):
    """Verify User A memory cannot be retrieved by User B under any search."""
    item_a = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_alice",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Secret credential or private prompt preference",
    )
    await sqlite_store.save(item_a)

    # Bob searches with the exact query string
    bob_results = await sqlite_store.search(
        query="Secret credential",
        scope=MemoryScope.USER,
        scope_id="user_bob",
    )
    assert len(bob_results) == 0

    # Alice searches -> gets her memory
    alice_results = await sqlite_store.search(
        query="Secret credential",
        scope=MemoryScope.USER,
        scope_id="user_alice",
    )
    assert len(alice_results) == 1
    assert alice_results[0].id == item_a.id


@pytest.mark.asyncio
async def test_project_scope_isolation(sqlite_store: SqliteMemoryStore):
    """Verify Project A memory cannot be retrieved by Project B."""
    item_proj = MemoryItem.create(
        scope=MemoryScope.PROJECT,
        scope_id="project_alpha",
        memory_type=MemoryType.PROJECT,
        content="Alpha internal architecture rule",
    )
    await sqlite_store.save(item_proj)

    # Project Beta search -> empty
    beta_results = await sqlite_store.search(
        query="architecture",
        scope=MemoryScope.PROJECT,
        scope_id="project_beta",
    )
    assert len(beta_results) == 0


@pytest.mark.asyncio
async def test_conversation_scope_isolation(sqlite_store: SqliteMemoryStore):
    """Verify Conversation A memory cannot be retrieved by Conversation B."""
    item_conv = MemoryItem.create(
        scope=MemoryScope.CONVERSATION,
        scope_id="conv_111",
        memory_type=MemoryType.WORKING,
        content="Transient conversation turn fact",
    )
    await sqlite_store.save(item_conv)

    conv2_results = await sqlite_store.search(
        scope=MemoryScope.CONVERSATION,
        scope_id="conv_222",
    )
    assert len(conv2_results) == 0


@pytest.mark.asyncio
async def test_memory_id_cannot_bypass_scope(sqlite_store: SqliteMemoryStore):
    """Verify knowledge of a memory_id does not allow retrieval under a different scope."""
    item = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_victim",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Confidential victim data",
    )
    await sqlite_store.save(item)

    # Attacker passes victim's memory_id under their own scope -> None
    retrieved = await sqlite_store.get(
        memory_id=item.id,
        scope=MemoryScope.USER,
        scope_id="user_attacker",
    )
    assert retrieved is None

    # Attacker tries to delete victim's memory -> False
    deleted = await sqlite_store.delete(
        memory_id=item.id,
        scope=MemoryScope.USER,
        scope_id="user_attacker",
    )
    assert not deleted

    # Victim's memory is still intact
    victim_get = await sqlite_store.get(
        memory_id=item.id,
        scope=MemoryScope.USER,
        scope_id="user_victim",
    )
    assert victim_get is not None


@pytest.mark.asyncio
async def test_sensitive_tool_output_never_promoted_to_durable(tmp_path: Path):
    """Verify tool observations are stored in working memory, never durable memory."""
    working_store = SqliteMemoryStore(tmp_path / "op.db")
    mock_durable_store = AsyncMock()

    orchestrator = MemoryOrchestrator(
        working_store=working_store,
        durable_store=mock_durable_store,
    )

    obs = ExecutionObservation.create(
        run_id="run_test",
        tool_name="run_command",
        tool_call_id="tc_1",
        summary="Command executed with output containing sensitive keys",
    )

    await orchestrator.record_observation(obs)

    # Durable store must NEVER be called for tool execution observations
    mock_durable_store.save.assert_not_called()

    # Working store has it recorded
    saved_items = await working_store.search(scope=MemoryScope.AGENT_RUN, scope_id="run_test")
    assert len(saved_items) == 1
    assert saved_items[0].memory_type == MemoryType.EXECUTION_OBSERVATION


@pytest.mark.asyncio
async def test_artifact_store_path_traversal_protection(tmp_path: Path):
    """Verify ArtifactStore prevents path traversal outside base directory."""
    store = LocalArtifactStore(base_dir=tmp_path / "artifacts")

    # Attempt path traversal in artifact_id
    traversal_id = "../../etc/passwd"
    saved_path = await store.save_artifact(traversal_id, "safe content")

    # The file must be contained within the artifacts directory
    path_obj = Path(saved_path).resolve()
    base_obj = (tmp_path / "artifacts").resolve()
    assert base_obj in path_obj.parents or path_obj.parent == base_obj
    assert path_obj.name == "passwd"

"""Unit tests for central MemoryOrchestrator."""

from unittest.mock import AsyncMock

import pytest

from app.application.memory.orchestrator import MemoryOrchestrator
from app.domain.models.memory import (
    ExecutionObservation,
    MemoryItem,
    MemoryScope,
    MemoryType,
)


@pytest.fixture
def mock_working_store() -> AsyncMock:
    store = AsyncMock()
    store.search.return_value = []
    store.save.side_effect = lambda m: m
    store.delete.return_value = True
    return store


@pytest.fixture
def mock_durable_store() -> AsyncMock:
    store = AsyncMock()
    store.search.return_value = []
    store.save.side_effect = lambda m: m
    store.delete.return_value = True
    return store


@pytest.mark.asyncio
async def test_record_observation(mock_working_store: AsyncMock, mock_durable_store: AsyncMock):
    events: list[tuple[str, dict]] = []
    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
        event_hook=lambda name, payload: events.append((name, payload)),
    )

    obs = ExecutionObservation.create(
        run_id="run_1",
        tool_name="read_file",
        tool_call_id="tc_1",
        summary="Read pyproject.toml",
    )

    item = await orchestrator.record_observation(obs)
    assert item.memory_type == MemoryType.EXECUTION_OBSERVATION
    mock_working_store.save.assert_called_once()
    assert len(events) == 1
    assert events[0][0] == "MEMORY_CREATED"


@pytest.mark.asyncio
async def test_save_memory_classification_routing(mock_working_store: AsyncMock, mock_durable_store: AsyncMock):
    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
    )

    # 1. User preference -> durable store
    pref = await orchestrator.save_memory(
        content="I prefer using dark mode in UI",
        scope=MemoryScope.USER,
        scope_id="user_1",
    )
    assert pref is not None
    assert pref.memory_type == MemoryType.USER_PREFERENCE
    mock_durable_store.save.assert_called_once()

    # 2. General task observation -> working store
    work = await orchestrator.save_memory(
        content="Temporary task progress step",
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_1",
    )
    assert work is not None
    assert work.memory_type == MemoryType.WORKING
    mock_working_store.save.assert_called_once()

    # 3. Discard noise -> None
    discarded = await orchestrator.save_memory(
        content="ok",
        scope=MemoryScope.USER,
        scope_id="user_1",
    )
    assert discarded is None


@pytest.mark.asyncio
async def test_retrieve_memories_best_effort_resilience(mock_working_store: AsyncMock, mock_durable_store: AsyncMock):
    # Durable store fails with an unexpected exception
    mock_durable_store.search.side_effect = RuntimeError("PostgreSQL connection timeout")

    working_item = MemoryItem.create(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_1",
        memory_type=MemoryType.WORKING,
        content="Working memory item available",
    )
    mock_working_store.search.return_value = [working_item]

    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
    )

    # Retrieval should not raise; it gracefully falls back to working_store
    results = await orchestrator.retrieve_memories(
        query="memory",
        scopes=[(MemoryScope.AGENT_RUN, "run_1")],
    )

    assert len(results) == 1
    assert results[0].id == working_item.id


@pytest.mark.asyncio
async def test_retrieve_memories_semantic_vector_passed_to_durable_store(
    mock_working_store: AsyncMock,
    mock_durable_store: AsyncMock,
):
    mock_embedding = AsyncMock()
    mock_embedding.generate_embedding.return_value = [0.1] * 1536

    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
        embedding_provider=mock_embedding,
    )

    await orchestrator.retrieve_memories(
        query="indentation preferences",
        scopes=[(MemoryScope.USER, "user_1")],
    )

    mock_embedding.generate_embedding.assert_called_once_with("indentation preferences")
    mock_durable_store.search.assert_called_once()
    call_kwargs = mock_durable_store.search.call_args.kwargs
    assert call_kwargs["scope"] == MemoryScope.USER
    assert call_kwargs["scope_id"] == "user_1"
    assert call_kwargs["query_vector"] == [0.1] * 1536


@pytest.mark.asyncio
async def test_retrieve_memories_embedding_failure_falls_back_to_text(
    mock_working_store: AsyncMock,
    mock_durable_store: AsyncMock,
):
    mock_embedding = AsyncMock()
    mock_embedding.generate_embedding.side_effect = RuntimeError("Embedding provider rate limit")

    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
        embedding_provider=mock_embedding,
    )

    # Retrieval does not crash; it falls back to text search (query_vector=None)
    results = await orchestrator.retrieve_memories(
        query="indentation preferences",
        scopes=[(MemoryScope.USER, "user_1")],
    )
    assert isinstance(results, list)

    mock_durable_store.search.assert_called_once()
    call_kwargs = mock_durable_store.search.call_args.kwargs
    assert call_kwargs["query"] == "indentation preferences"
    assert call_kwargs["query_vector"] is None


@pytest.mark.asyncio
async def test_retrieve_memories_dimension_mismatch_falls_back_to_text(
    mock_working_store: AsyncMock,
    mock_durable_store: AsyncMock,
):
    mock_embedding = AsyncMock()
    # Return 768 dimensions instead of 1536
    mock_embedding.generate_embedding.return_value = [0.1] * 768

    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
        embedding_provider=mock_embedding,
    )

    await orchestrator.retrieve_memories(
        query="test query",
        scopes=[(MemoryScope.USER, "user_1")],
    )

    mock_durable_store.search.assert_called_once()
    call_kwargs = mock_durable_store.search.call_args.kwargs
    assert call_kwargs["query_vector"] is None


@pytest.mark.asyncio
async def test_save_memory_generates_embedding_for_durable_store(
    mock_working_store: AsyncMock,
    mock_durable_store: AsyncMock,
):
    mock_embedding = AsyncMock()
    mock_embedding.generate_embedding.return_value = [0.25] * 1536

    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
        embedding_provider=mock_embedding,
    )

    saved = await orchestrator.save_memory(
        content="I prefer dark mode in all UI tools",
        scope=MemoryScope.USER,
        scope_id="user_123",
    )

    assert saved is not None
    assert saved.embedding == [0.25] * 1536
    mock_embedding.generate_embedding.assert_called_once_with("I prefer dark mode in all UI tools")
    mock_durable_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_save_memory_embedding_failure_still_saves_durable_item(
    mock_working_store: AsyncMock,
    mock_durable_store: AsyncMock,
):
    mock_embedding = AsyncMock()
    mock_embedding.generate_embedding.side_effect = RuntimeError("Embedding service unavailable")

    orchestrator = MemoryOrchestrator(
        working_store=mock_working_store,
        durable_store=mock_durable_store,
        embedding_provider=mock_embedding,
    )

    saved = await orchestrator.save_memory(
        content="I prefer dark mode in all UI tools",
        scope=MemoryScope.USER,
        scope_id="user_123",
    )

    assert saved is not None
    assert saved.embedding is None
    mock_durable_store.save.assert_called_once()

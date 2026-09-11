"""Unit tests for Memory domain models and Artifact entity."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models.artifact import Artifact
from app.domain.models.memory import (
    ExecutionObservation,
    InvalidMemoryScopeError,
    MemoryItem,
    MemoryScope,
    MemoryType,
)


def test_create_memory_item():
    item = MemoryItem.create(
        scope=MemoryScope.USER,
        scope_id="user_123",
        memory_type=MemoryType.USER_PREFERENCE,
        content="Prefer Python 3.13 and strict type annotations",
        importance=0.8,
        metadata={"category": "coding_style"},
    )

    assert item.id.startswith("mem_")
    assert item.scope == MemoryScope.USER
    assert item.scope_id == "user_123"
    assert item.memory_type == MemoryType.USER_PREFERENCE
    assert item.content == "Prefer Python 3.13 and strict type annotations"
    assert item.importance == 0.8
    assert item.metadata["category"] == "coding_style"
    assert not item.is_expired()


def test_memory_item_validation():
    with pytest.raises(ValueError, match=r"Importance must be between 0\.0 and 1\.0"):
        MemoryItem.create(
            scope=MemoryScope.PROJECT,
            scope_id="proj_1",
            memory_type=MemoryType.PROJECT,
            content="Valid content",
            importance=1.5,
        )

    with pytest.raises(ValueError, match="Memory content cannot be empty"):
        MemoryItem.create(
            scope=MemoryScope.PROJECT,
            scope_id="proj_1",
            memory_type=MemoryType.PROJECT,
            content="   ",
        )

    with pytest.raises(ValueError, match="Memory scope_id cannot be empty"):
        MemoryItem.create(
            scope=MemoryScope.PROJECT,
            scope_id="   ",
            memory_type=MemoryType.PROJECT,
            content="Valid content",
        )


def test_memory_item_scope_and_type_invariants():
    # Valid combinations
    valid_cases = [
        (MemoryType.WORKING, MemoryScope.AGENT_RUN, "run_1"),
        (MemoryType.WORKING, MemoryScope.CONVERSATION, "conv_1"),
        (MemoryType.EXECUTION_OBSERVATION, MemoryScope.AGENT_RUN, "run_1"),
        (MemoryType.EXECUTION_OBSERVATION, MemoryScope.CONVERSATION, "conv_1"),
        (MemoryType.LONG_TERM, MemoryScope.USER, "user_1"),
        (MemoryType.LONG_TERM, MemoryScope.PROJECT, "proj_1"),
        (MemoryType.PROJECT, MemoryScope.PROJECT, "proj_1"),
        (MemoryType.USER_PREFERENCE, MemoryScope.USER, "user_1"),
    ]
    for mem_type, scope, s_id in valid_cases:
        item = MemoryItem.create(
            scope=scope,
            scope_id=s_id,
            memory_type=mem_type,
            content=f"Content for {mem_type.value} in {scope.value}",
        )
        assert item.scope == scope
        assert item.memory_type == mem_type

    # Invalid combinations
    invalid_cases = [
        (MemoryType.WORKING, MemoryScope.USER),
        (MemoryType.WORKING, MemoryScope.PROJECT),
        (MemoryType.EXECUTION_OBSERVATION, MemoryScope.USER),
        (MemoryType.EXECUTION_OBSERVATION, MemoryScope.PROJECT),
        (MemoryType.LONG_TERM, MemoryScope.CONVERSATION),
        (MemoryType.LONG_TERM, MemoryScope.AGENT_RUN),
        (MemoryType.PROJECT, MemoryScope.USER),
        (MemoryType.PROJECT, MemoryScope.CONVERSATION),
        (MemoryType.PROJECT, MemoryScope.AGENT_RUN),
        (MemoryType.USER_PREFERENCE, MemoryScope.PROJECT),
        (MemoryType.USER_PREFERENCE, MemoryScope.CONVERSATION),
        (MemoryType.USER_PREFERENCE, MemoryScope.AGENT_RUN),
    ]
    for mem_type, scope in invalid_cases:
        with pytest.raises(InvalidMemoryScopeError, match=r"Invalid memory scope"):
            MemoryItem.create(
                scope=scope,
                scope_id="scope_1",
                memory_type=mem_type,
                content="Invalid combination content",
            )


def test_memory_item_expiration():
    past = datetime.now(UTC) - timedelta(minutes=10)
    future = datetime.now(UTC) + timedelta(minutes=10)

    expired_item = MemoryItem.create(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_1",
        memory_type=MemoryType.WORKING,
        content="Temporary scratchpad data",
        expires_at=past,
    )
    assert expired_item.is_expired()

    active_item = MemoryItem.create(
        scope=MemoryScope.AGENT_RUN,
        scope_id="run_1",
        memory_type=MemoryType.WORKING,
        content="Temporary scratchpad data",
        expires_at=future,
    )
    assert not active_item.is_expired()


def test_memory_item_touch():
    item = MemoryItem.create(
        scope=MemoryScope.CONVERSATION,
        scope_id="conv_1",
        memory_type=MemoryType.WORKING,
        content="Context fact",
    )
    prev_accessed = item.last_accessed_at
    item.touch()
    assert item.last_accessed_at >= prev_accessed


def test_execution_observation_creation_and_conversion():
    obs = ExecutionObservation.create(
        run_id="run_abc",
        tool_name="run_command",
        tool_call_id="tc_123",
        command="git status",
        exit_code=0,
        summary="Clean working tree",
        stdout_preview="nothing to commit, working tree clean",
        artifact_ref="storage/artifacts/run_abc_stdout.log",
        is_error=False,
    )

    assert obs.observation_id.startswith("obs_")
    assert obs.run_id == "run_abc"
    assert obs.tool_name == "run_command"
    assert obs.exit_code == 0
    assert not obs.is_error

    mem = obs.to_memory_item()
    assert mem.memory_type == MemoryType.EXECUTION_OBSERVATION
    assert mem.scope == MemoryScope.AGENT_RUN
    assert mem.scope_id == "run_abc"
    assert "Clean working tree" in mem.content
    assert mem.metadata["tool_name"] == "run_command"


def test_artifact_domain_model():
    art = Artifact.create(
        artifact_type="command_stdout",
        size_bytes=1048576,
        storage_ref="/storage/artifacts/log_1.log",
        source_execution_id="exec_999",
        summary="Build output logs",
        preview="Compiling package...",
    )

    assert art.id.startswith("art_")
    assert art.size_bytes == 1048576
    assert art.artifact_type == "command_stdout"

    ctx_dict = art.to_context_dict()
    assert ctx_dict["artifact_id"] == art.id
    assert ctx_dict["type"] == "command_stdout"
    assert ctx_dict["size_bytes"] == 1048576
    assert "Build output logs" in ctx_dict["summary"]

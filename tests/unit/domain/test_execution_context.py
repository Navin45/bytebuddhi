"""Tests for immutable trusted ExecutionContext."""

from dataclasses import FrozenInstanceError

import pytest

from app.domain.models.execution_context import ExecutionContext


def _parent() -> ExecutionContext:
    return ExecutionContext(
        user_id="alice",
        project_id="proj_a",
        conversation_id="conv_1",
        run_id="run_parent",
        workspace_id="ws_a",
    )


def test_execution_context_is_immutable() -> None:
    ctx = _parent()
    with pytest.raises(FrozenInstanceError):
        ctx.user_id = "attacker"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ctx.project_id = "proj_evil"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ctx.workspace_id = "/etc"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ctx.delegation_depth = 99  # type: ignore[misc]


def test_child_context_derives_from_parent() -> None:
    parent = _parent()
    child = parent.derive_child("run_child")
    assert child.user_id == parent.user_id
    assert child.project_id == parent.project_id
    assert child.conversation_id == parent.conversation_id
    assert child.workspace_id == parent.workspace_id
    assert child.parent_run_id == parent.run_id
    assert child.child_run_id == "run_child"
    assert child.run_id == "run_child"
    assert child.delegation_depth == parent.delegation_depth + 1


def test_child_identity_is_unique() -> None:
    parent = _parent()
    child_a = parent.derive_child("run_child_a")
    child_b = parent.derive_child("run_child_b")
    assert child_a.run_id != parent.run_id
    assert child_b.run_id != parent.run_id
    assert child_a.run_id != child_b.run_id
    with pytest.raises(ValueError, match="unique"):
        parent.derive_child(parent.run_id)


def test_child_cannot_change_parent_identity() -> None:
    parent = _parent()
    child = parent.derive_child("run_child")
    with pytest.raises(FrozenInstanceError):
        child.user_id = "mallory"  # type: ignore[misc]
    assert parent.user_id == "alice"
    assert parent.project_id == "proj_a"
    assert parent.run_id == "run_parent"
    assert parent.delegation_depth == 0

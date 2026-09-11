"""Unit tests for CorrelationContext and ContextVar propagation."""

from app.application.ports.output.observability.context import (
    CorrelationContext,
    get_correlation_context,
    with_correlation_context,
)
from app.domain.models.observability import SpanAttributes


def test_default_correlation_context() -> None:
    """Verify default correlation context returns empty or default structure."""
    ctx = get_correlation_context()
    assert isinstance(ctx, CorrelationContext)
    assert ctx.run_id is None
    assert ctx.agent_id is None


def test_with_correlation_context_lifecycle() -> None:
    """Verify with_correlation_context sets and restores context correctly."""
    assert get_correlation_context().run_id is None

    with with_correlation_context(
        run_id="run-123",
        agent_id="agent-abc",
        agent_role="coder",
        user_id="user-1",
        project_id="proj-99",
        delegation_depth=1,
    ) as ctx:
        assert ctx.run_id == "run-123"
        assert ctx.agent_role == "coder"
        assert get_correlation_context().run_id == "run-123"

        # Check attribute conversion
        attrs = ctx.to_attributes()
        assert (
            attrs[SpanAttributes.RUN_ID if hasattr(SpanAttributes, "RUN_ID") else "bytebuddhi.agent.id"] == "agent-abc"
        )
        assert attrs[SpanAttributes.AGENT_ROLE] == "coder"
        assert attrs[SpanAttributes.USER_ID] == "user-1"
        assert attrs[SpanAttributes.DELEGATION_DEPTH] == 1

    # Context restored after exit
    assert get_correlation_context().run_id is None


def test_nested_correlation_context_inheritance() -> None:
    """Verify child context overrides child fields while preserving parent boundary."""
    with with_correlation_context(
        run_id="parent-run",
        agent_role="researcher",
        user_id="user-main",
        project_id="proj-main",
        delegation_depth=0,
    ) as parent:
        assert parent.run_id == "parent-run"

        with with_correlation_context(
            run_id="child-run",
            parent_run_id="parent-run",
            agent_role="reviewer",
            user_id="user-main",
            project_id="proj-main",
            delegation_depth=1,
        ) as child:
            assert child.run_id == "child-run"
            assert child.parent_run_id == "parent-run"
            assert child.agent_role == "reviewer"
            assert child.user_id == "user-main"
            assert child.delegation_depth == 1
            assert get_correlation_context().run_id == "child-run"

        # Restored to parent
        current = get_correlation_context()
        assert current.run_id == "parent-run"
        assert current.agent_role == "researcher"
        assert current.parent_run_id is None

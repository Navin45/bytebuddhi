"""Shared trusted ExecutionContext constructors for tests."""

from app.domain.models.execution_context import ExecutionContext


def trusted_execution_context(
    *,
    user_id: str = "alice",
    project_id: str | None = "proj_test",
    conversation_id: str | None = "conv_test",
    run_id: str = "run_test",
    workspace_id: str = "ws_test",
    parent_run_id: str | None = None,
    child_run_id: str | None = None,
    delegation_depth: int = 0,
    agent_id: str | None = None,
    approved_actions: tuple[str, ...] = (),
) -> ExecutionContext:
    return ExecutionContext(
        user_id=user_id,
        project_id=project_id,
        conversation_id=conversation_id,
        run_id=run_id,
        workspace_id=workspace_id,
        parent_run_id=parent_run_id,
        child_run_id=child_run_id,
        delegation_depth=delegation_depth,
        agent_id=agent_id,
        approved_actions=approved_actions,
    )

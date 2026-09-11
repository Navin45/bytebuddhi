from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.tools.definition import ToolCall, ToolResult
from app.domain.models.conversation import Conversation
from app.domain.models.user import User
from app.domain.models.workspace import Workspace
from app.interfaces.api.dependencies import (
    get_agent_runtime,
    get_conversation_repository,
    get_message_repository,
    get_workspace_resolution_service,
)
from app.interfaces.api.main import app
from app.interfaces.api.middleware import get_current_user


@pytest.mark.asyncio
async def test_chat_endpoint_with_agent_runtime():
    user_id = uuid4()
    conv_id = uuid4()

    mock_user = User(
        id=user_id,
        email="test@bytebuddhi.com",
        username="tester",
        password_hash="hash",
        created_at=None,
        updated_at=None,
    )

    mock_conv = Conversation(
        id=conv_id,
        user_id=user_id,
        project_id=uuid4(),
        title="Test Chat",
        created_at=None,
        updated_at=None,
    )

    mock_conv_repo = AsyncMock()
    mock_conv_repo.get_by_id.return_value = mock_conv

    mock_msg_repo = AsyncMock()
    mock_msg_repo.get_by_conversation_id.return_value = []
    mock_saved_msg = MagicMock()
    mock_saved_msg.id = uuid4()
    mock_msg_repo.create.return_value = mock_saved_msg

    mock_runtime = AsyncMock()
    mock_runtime.run.return_value = AgentRunState(
        run_id="test_run",
        status=AgentStatus.COMPLETED,
        iteration=2,
        final_response="Here is the solution to your problem.",
        tool_calls=[ToolCall(id="c1", name="echo", arguments={"message": "hello"})],
        tool_results=[ToolResult(tool_call_id="c1", name="echo", content="echo: hello")],
    )

    mock_workspace_res = AsyncMock()
    mock_workspace_res.resolve_workspace.return_value = Workspace.create(
        root_path="storage/workspaces/test",
        workspace_id="ws_chat_test",
    )

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_conversation_repository] = lambda: mock_conv_repo
    app.dependency_overrides[get_message_repository] = lambda: mock_msg_repo
    app.dependency_overrides[get_agent_runtime] = lambda: mock_runtime
    app.dependency_overrides[get_workspace_resolution_service] = lambda: mock_workspace_res

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"content": "Please write a test function"},
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            body = response.text
            assert "event: tool_call" in body
            assert "echo" in body
            assert "event: content" in body
            assert "Here is the solution to your problem." in body
            assert "event: done" in body

            mock_runtime.run.assert_called_once()
            run_kwargs = mock_runtime.run.call_args.kwargs
            execution_context = run_kwargs["execution_context"]
            assert str(execution_context.user_id) == str(user_id)
            assert str(execution_context.project_id) == str(mock_conv.project_id)
            assert str(execution_context.conversation_id) == str(conv_id)
            assert execution_context.workspace_id == "ws_chat_test"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_endpoint_without_project_metadata():
    user_id = uuid4()
    conv_id = uuid4()

    mock_user = User(
        id=user_id,
        email="test@bytebuddhi.com",
        username="tester",
        password_hash="hash",
        created_at=None,
        updated_at=None,
    )

    mock_conv = Conversation(
        id=conv_id,
        user_id=user_id,
        project_id=None,  # No project
        title="Projectless Chat",
        created_at=None,
        updated_at=None,
    )

    mock_conv_repo = AsyncMock()
    mock_conv_repo.get_by_id.return_value = mock_conv

    mock_msg_repo = AsyncMock()
    mock_msg_repo.get_by_conversation_id.return_value = []
    mock_saved_msg = MagicMock()
    mock_saved_msg.id = uuid4()
    mock_msg_repo.create.return_value = mock_saved_msg

    mock_runtime = AsyncMock()
    mock_runtime.run.return_value = AgentRunState(
        run_id="test_run_2",
        status=AgentStatus.COMPLETED,
        iteration=1,
        final_response="Response without project",
        tool_calls=[],
        tool_results=[],
    )

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_conversation_repository] = lambda: mock_conv_repo
    app.dependency_overrides[get_message_repository] = lambda: mock_msg_repo
    app.dependency_overrides[get_agent_runtime] = lambda: mock_runtime

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"content": "Hello without project"},
            )

            assert response.status_code == 200
            mock_runtime.run.assert_called_once()
            run_kwargs = mock_runtime.run.call_args.kwargs
            execution_context = run_kwargs["execution_context"]
            assert str(execution_context.user_id) == str(user_id)
            assert execution_context.project_id is None
            assert str(execution_context.conversation_id) == str(conv_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_endpoint_unauthorized_user_forbidden():
    owner_id = uuid4()
    other_user_id = uuid4()
    conv_id = uuid4()

    mock_user = User(
        id=other_user_id,
        email="other@bytebuddhi.com",
        username="other",
        password_hash="hash",
        created_at=None,
        updated_at=None,
    )

    mock_conv = Conversation(
        id=conv_id,
        user_id=owner_id,
        project_id=uuid4(),
        title="Owner Chat",
        created_at=None,
        updated_at=None,
    )

    mock_conv_repo = AsyncMock()
    mock_conv_repo.get_by_id.return_value = mock_conv
    mock_msg_repo = AsyncMock()
    mock_runtime = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_conversation_repository] = lambda: mock_conv_repo
    app.dependency_overrides[get_message_repository] = lambda: mock_msg_repo
    app.dependency_overrides[get_agent_runtime] = lambda: mock_runtime

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"content": "Unauthorized attempt"},
            )

            assert response.status_code == 403
            # Runtime was never invoked
            mock_runtime.run.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_runtime_memory_scope_selection_from_metadata():
    from app.application.agent.runtime import AgentRuntime
    from app.application.tools.registry import ToolRegistry
    from app.domain.models.execution_context import ExecutionContext
    from app.domain.models.memory import MemoryScope

    mock_gateway = AsyncMock()
    mock_response = MagicMock()
    mock_response.has_tool_calls = False
    mock_response.content = "Answer with scoped memories"
    mock_gateway.generate.return_value = mock_response

    mock_orch = AsyncMock()
    mock_orch.retrieve_memories.return_value = []

    runtime = AgentRuntime(
        model_gateway=mock_gateway,
        tool_registry=ToolRegistry(),
        memory_orchestrator=mock_orch,
    )

    # 1. Run with User A and Project A
    await runtime.run(
        messages=[{"role": "user", "content": "Query"}],
        execution_context=ExecutionContext(
            user_id="user_A",
            project_id="proj_A",
            conversation_id=None,
            run_id="run_a",
            workspace_id="ws_a",
        ),
    )
    mock_orch.retrieve_memories.assert_called_once()
    scopes_passed = mock_orch.retrieve_memories.call_args.kwargs["scopes"]
    assert (MemoryScope.USER, "user_A") in scopes_passed
    assert (MemoryScope.PROJECT, "proj_A") in scopes_passed
    assert (MemoryScope.USER, "user_B") not in scopes_passed
    assert (MemoryScope.PROJECT, "proj_B") not in scopes_passed

    # 2. Run without project metadata -> no project scope queried
    mock_orch.retrieve_memories.reset_mock()
    await runtime.run(
        messages=[{"role": "user", "content": "Query 2"}],
        execution_context=ExecutionContext(
            user_id="user_A",
            project_id=None,
            conversation_id=None,
            run_id="run_a2",
            workspace_id="ws_a",
        ),
    )
    scopes_passed_2 = mock_orch.retrieve_memories.call_args.kwargs["scopes"]
    assert (MemoryScope.USER, "user_A") in scopes_passed_2
    assert not any(scope_type == MemoryScope.PROJECT for scope_type, _ in scopes_passed_2)

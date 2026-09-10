from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.application.agent.state import AgentRunState
from app.application.agent.types import AgentStatus
from app.application.tools.definition import ToolCall, ToolResult
from app.domain.models.conversation import Conversation
from app.domain.models.user import User
from app.interfaces.api.dependencies import (
    get_agent_runtime,
    get_conversation_repository,
    get_message_repository,
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

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_conversation_repository] = lambda: mock_conv_repo
    app.dependency_overrides[get_message_repository] = lambda: mock_msg_repo
    app.dependency_overrides[get_agent_runtime] = lambda: mock_runtime

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
    finally:
        app.dependency_overrides.clear()

from app.application.agent.errors import (
    AgentCancelledError,
    AgentError,
    AgentErrorCode,
    IterationLimitExceededError,
    ModelCallError,
    ToolExecutionError,
    ToolNotFoundError,
)
from app.application.agent.types import AgentMessage, AgentStatus, TokenUsage


def test_agent_status_values():
    assert AgentStatus.IDLE == "idle"
    assert AgentStatus.RUNNING == "running"
    assert AgentStatus.COMPLETED == "completed"
    assert AgentStatus.FAILED == "failed"
    assert AgentStatus.CANCELLED == "cancelled"


def test_token_usage_add():
    u1 = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    u2 = TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
    total = u1.add(u2)
    assert total.prompt_tokens == 30
    assert total.completion_tokens == 15
    assert total.total_tokens == 45


def test_agent_message_to_dict():
    msg = AgentMessage(role="user", content="hello", metadata={"source": "api"})
    d = msg.to_dict()
    assert d == {"role": "user", "content": "hello", "metadata": {"source": "api"}}


def test_agent_error_serialization():
    err = AgentError(
        code=AgentErrorCode.VALIDATION_ERROR,
        message="Invalid parameter",
        details={"field": "name"},
        is_retryable=False,
    )
    d = err.to_dict()
    assert d["code"] == "validation_error"
    assert d["message"] == "Invalid parameter"
    assert d["details"] == {"field": "name"}
    assert d["is_retryable"] is False
    assert "[validation_error]" in str(err)


def test_specific_agent_errors():
    model_err = ModelCallError("Rate limited", is_retryable=True)
    assert model_err.code == AgentErrorCode.MODEL_ERROR
    assert model_err.is_retryable is True

    tool_err = ToolExecutionError("echo", "Division by zero")
    assert tool_err.code == AgentErrorCode.TOOL_ERROR
    assert tool_err.details["tool_name"] == "echo"

    not_found = ToolNotFoundError("missing_tool")
    assert not_found.code == AgentErrorCode.TOOL_NOT_FOUND
    assert not_found.details["tool_name"] == "missing_tool"

    limit_err = IterationLimitExceededError(iterations=10, max_iterations=10)
    assert limit_err.code == AgentErrorCode.ITERATION_LIMIT

    cancel_err = AgentCancelledError()
    assert cancel_err.code == AgentErrorCode.CANCELLED

from app.application.agent.errors import AgentErrorCode
from app.application.agent.state import AgentLoopState, AgentRunState
from app.application.agent.types import AgentStatus


def test_agent_run_state_defaults():
    run_state = AgentRunState(run_id="run-1")
    assert run_state.run_id == "run-1"
    assert run_state.status == AgentStatus.IDLE
    assert run_state.iteration == 0
    assert run_state.final_response is None
    assert run_state.error is None


def test_agent_run_state_from_loop_state():
    loop_state: AgentLoopState = {
        "run_id": "run-42",
        "messages": [{"role": "user", "content": "ping"}],
        "status": "completed",
        "iteration": 2,
        "max_iterations": 10,
        "pending_tool_calls": [{"id": "c1", "name": "echo", "arguments": {"msg": "hi"}}],
        "tool_results": [{"tool_call_id": "c1", "name": "echo", "content": "hi", "is_error": False}],
        "final_response": "hi back",
        "error": None,
        "metadata": {"user": "tester"},
    }

    run_state = AgentRunState.from_loop_state(loop_state)
    assert run_state.run_id == "run-42"
    assert run_state.status == AgentStatus.COMPLETED
    assert run_state.iteration == 2
    assert run_state.final_response == "hi back"
    assert len(run_state.tool_calls) == 1
    assert run_state.tool_calls[0].name == "echo"
    assert len(run_state.tool_results) == 1
    assert run_state.tool_results[0].content == "hi"
    assert run_state.error is None


def test_agent_run_state_from_loop_state_with_error():
    loop_state = {
        "run_id": "run-err",
        "status": "failed",
        "error": {
            "code": "iteration_limit_exceeded",
            "message": "Max iterations reached",
            "details": {"max": 10},
        },
    }

    run_state = AgentRunState.from_loop_state(loop_state)
    assert run_state.status == AgentStatus.FAILED
    assert run_state.error is not None
    assert run_state.error.code == AgentErrorCode.ITERATION_LIMIT
    assert run_state.error.message == "Max iterations reached"

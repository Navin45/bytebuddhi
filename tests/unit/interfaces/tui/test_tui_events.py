"""Event reduction stays ordered and keeps one assistant message per run."""

from app.interfaces.gateway.errors import (
    AuthenticationRequired,
    AuthorizationDenied,
    GatewayServerError,
    GatewayUnavailable,
    InvalidRequest,
    RateLimited,
    ResourceNotFound,
)
from app.interfaces.tui.events import reduce_event
from app.interfaces.tui.session import human_error
from app.interfaces.tui.state import TuiState


def _event(sequence: int, event_type: str, data: dict | None = None, run_id: str = "run_1") -> dict:
    return {
        "event_id": f"evt-{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "schema_version": 1,
        "created_at": "2026-09-25T00:00:00+00:00",
        "data": data or {},
    }


def test_deltas_merge_into_one_assistant_message() -> None:
    state = TuiState()
    state = reduce_event(state, _event(1, "run_queued"))
    state = reduce_event(state, _event(2, "run_started"))
    state = reduce_event(state, _event(3, "assistant_delta", {"delta": "Hello"}))
    state = reduce_event(state, _event(4, "assistant_delta", {"delta": " world"}))
    state = reduce_event(state, _event(5, "run_completed"))
    assistants = [item for item in state.transcript if item.kind == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].body == "Hello world"
    assert assistants[0].streaming is False
    assert state.run_status == "completed"
    assert state.run_active is False
    assert state.last_sequence == 5


def test_duplicate_sequence_is_ignored() -> None:
    state = reduce_event(TuiState(), _event(1, "assistant_delta", {"delta": "Hello"}))
    again = reduce_event(state, _event(1, "assistant_delta", {"delta": " again"}))
    assert again.transcript[0].body == "Hello"
    assert again.last_sequence == 1


def test_tool_completion_updates_the_same_item() -> None:
    state = TuiState()
    state = reduce_event(state, _event(1, "tool_started", {"tool_name": "filesystem.search"}))
    state = reduce_event(state, _event(2, "tool_completed", {"tool_name": "filesystem.search", "artifact_id": "art_1"}))
    tools = [item for item in state.transcript if item.kind == "tool"]
    assert len(tools) == 1
    assert tools[0].item_id == "tool-run_1-1"
    assert tools[0].body == "completed"
    assert tools[0].tool_open is False
    assert "art_1" in tools[0].detail
    assert tools[0].title == "[tool] filesystem.search"


def test_terminal_states_unlock_and_interrupted_is_distinct() -> None:
    notices = {}
    for sequence, event_type, status in (
        (1, "run_completed", "completed"),
        (1, "run_failed", "failed"),
        (1, "run_cancelled", "cancelled"),
        (1, "run_interrupted", "interrupted"),
    ):
        state = reduce_event(
            TuiState(submitting=True, run_status="running", active_run_id="run_1"),
            _event(sequence, event_type, {"error_message": f"detail-{status}"} if status != "interrupted" else {}),
        )
        assert state.run_status == status
        assert state.submitting is False
        assert state.run_active is False
        assert state.active_run_id == "run_1"
        notices[status] = [item.body for item in state.transcript if item.kind == "notice"]
    assert notices["completed"] == []
    assert notices["failed"] == ["detail-failed"]
    assert notices["cancelled"] == ["Run cancelled"]
    assert "not replayed" in notices["interrupted"][0]


def test_cancel_requested_keeps_the_run_locked() -> None:
    state = reduce_event(TuiState(run_status="running"), _event(1, "run_cancel_requested"))
    assert state.run_status == "cancel_requested"
    assert state.run_active is True


def test_gateway_errors_are_human_readable() -> None:
    assert "bytebuddhi login" in human_error(AuthenticationRequired("expired"))
    assert "do not have access" in human_error(AuthorizationDenied("no"))
    assert "not found" in human_error(ResourceNotFound("missing"))
    assert "rate limited" in human_error(RateLimited("slow")).lower()
    assert human_error(InvalidRequest("Model is not allowed")) == "Model is not allowed"
    assert "internal error" in human_error(GatewayServerError("boom"))
    assert "Cannot connect" in human_error(GatewayUnavailable("down"))

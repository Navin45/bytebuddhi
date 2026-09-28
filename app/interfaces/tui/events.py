"""Map one run event onto TUI state. Widgets do not inspect event types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from app.interfaces.tui.state import TranscriptItem, TuiState, unlock

_TERMINAL = {
    "run_completed": "completed",
    "run_failed": "failed",
    "run_cancelled": "cancelled",
    "run_interrupted": "interrupted",
}
_PREVIEW = 180


def reduce_event(state: TuiState, event: Mapping[str, object]) -> TuiState:
    """Apply one in-order event. A duplicate sequence is ignored."""
    sequence = _as_int(event.get("sequence"))
    if sequence is None or sequence <= state.last_sequence:
        return state
    event_type = str(event.get("type") or "")
    data = event.get("data")
    payload = data if isinstance(data, dict) else {}
    run_id = str(event.get("run_id") or state.active_run_id or "")
    state = replace(state, last_sequence=sequence, active_run_id=run_id or state.active_run_id)
    if event_type == "run_queued":
        return replace(state, run_status="queued", submitting=False)
    if event_type == "run_started":
        return replace(state, run_status="running", submitting=False)
    if event_type == "assistant_delta":
        return _append_delta(state, run_id, str(payload.get("delta") or ""))
    if event_type == "tool_started":
        return _open_tool(state, run_id, sequence, str(payload.get("tool_name") or "tool"))
    if event_type == "tool_completed":
        return _close_tool(state, run_id, payload)
    if event_type == "run_cancel_requested":
        return replace(state, run_status="cancel_requested")
    if event_type == "message_created":
        return _finish_stream(state, run_id)
    if event_type == "tool_approval_required":
        action = str(payload.get("action") or "tool execution")
        risk = str(payload.get("risk_level") or "high")
        reason = str(payload.get("reason") or "Confirmation required")
        item = TranscriptItem(
            item_id=f"approval-{run_id}-{sequence}",
            kind="notice",
            title=f"[APPROVAL REQUIRED] {action} (Risk: {risk})",
            body=reason,
            run_id=run_id,
        )
        return replace(state, transcript=(*state.transcript, item))
    if event_type == "tool_approved":
        action = str(payload.get("action") or "tool execution")
        item = TranscriptItem(
            item_id=f"approved-{run_id}-{sequence}",
            kind="notice",
            title=f"[APPROVED] {action}",
            body="Approval granted.",
            run_id=run_id,
        )
        return replace(state, transcript=(*state.transcript, item))
    if event_type == "tool_rejected":
        action = str(payload.get("action") or "tool execution")
        item = TranscriptItem(
            item_id=f"rejected-{run_id}-{sequence}",
            kind="notice",
            title=f"[REJECTED] {action}",
            body="Approval denied.",
            run_id=run_id,
        )
        return replace(state, transcript=(*state.transcript, item))
    if event_type in _TERMINAL:
        return _terminal(state, run_id, _TERMINAL[event_type], payload)
    return state


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _append_delta(state: TuiState, run_id: str, delta: str) -> TuiState:
    items = list(state.transcript)
    if items and items[-1].kind == "assistant" and items[-1].streaming and items[-1].run_id == run_id:
        current = items[-1]
        items[-1] = replace(current, body=current.body + delta)
        return replace(state, transcript=tuple(items))
    items.append(
        TranscriptItem(
            item_id=f"assistant-{run_id}",
            kind="assistant",
            title="ByteBuddhi",
            body=delta,
            run_id=run_id,
            streaming=True,
        )
    )
    return replace(state, transcript=tuple(items))


def _open_tool(state: TuiState, run_id: str, sequence: int, name: str) -> TuiState:
    item = TranscriptItem(
        item_id=f"tool-{run_id}-{sequence}",
        kind="tool",
        title=f"[tool] {name}",
        body="started",
        run_id=run_id,
        tool_open=True,
    )
    return replace(state, transcript=(*state.transcript, item))


def _close_tool(state: TuiState, run_id: str, payload: Mapping[str, object]) -> TuiState:
    name = str(payload.get("tool_name") or "")
    artifact = payload.get("artifact_id")
    detail = f"artifact {artifact}" if artifact else ""
    items = list(state.transcript)
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if item.kind == "tool" and item.tool_open and item.run_id == run_id:
            title = item.title if not name else f"[tool] {name}"
            items[index] = replace(item, title=title, body="completed", detail=detail[:_PREVIEW], tool_open=False)
            break
    return replace(state, transcript=tuple(items))


def _finish_stream(state: TuiState, run_id: str) -> TuiState:
    items = [
        replace(item, streaming=False) if item.kind == "assistant" and item.run_id == run_id else item
        for item in state.transcript
    ]
    return replace(state, transcript=tuple(items))


def _terminal(state: TuiState, run_id: str, status: str, payload: Mapping[str, object]) -> TuiState:
    state = _finish_stream(state, run_id)
    notice = _notice(run_id, status, payload)
    transcript = state.transcript if notice is None else (*state.transcript, notice)
    return unlock(replace(state, transcript=transcript), status)


def _notice(run_id: str, status: str, payload: Mapping[str, object]) -> TranscriptItem | None:
    if status == "completed":
        return None
    messages = {
        "failed": str(payload.get("error_message") or "Run failed"),
        "cancelled": "Run cancelled",
        "interrupted": str(
            payload.get("error_message") or "Run interrupted. The worker stopped and the agent was not replayed."
        ),
    }
    return TranscriptItem(
        item_id=f"notice-{run_id}-{status}",
        kind="notice",
        title=status.upper(),
        body=messages[status],
        run_id=run_id,
    )

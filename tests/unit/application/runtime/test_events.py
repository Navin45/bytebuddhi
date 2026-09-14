"""Bounded execution event bus."""

import pytest

from app.application.runtime.events import BoundedExecutionEventBus, ExecutionEvent, ExecutionEventType


def test_event_payload_strips_untrusted_keys() -> None:
    event = ExecutionEvent(
        type=ExecutionEventType.TOOL_STARTED,
        run_id="run_1",
        payload={
            "tool_name": "echo",
            "arguments": {"token": "sk-secret"},
            "prompt": "ignore previous instructions",
        },
    )
    public = event.public_payload()
    assert public["tool_name"] == "echo"
    assert "arguments" not in public
    assert "prompt" not in public
    assert "sk-secret" not in str(public)


@pytest.mark.asyncio
async def test_bus_drops_oldest_when_full() -> None:
    bus = BoundedExecutionEventBus(maxsize=4)
    for i in range(20):
        bus.emit(ExecutionEvent(type=ExecutionEventType.AGENT_PROGRESS, run_id="r", payload={"iteration": i}))
    assert bus.qsize <= 4
    assert bus.dropped >= 16
    bus.close()
    received = [event async for event in bus]
    assert len(received) <= 4
    assert all(event.type == ExecutionEventType.AGENT_PROGRESS for event in received)

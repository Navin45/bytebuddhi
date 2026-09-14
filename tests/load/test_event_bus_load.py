"""Controlled load on bounded runtime queues."""

from app.application.runtime.events import BoundedExecutionEventBus, ExecutionEvent, ExecutionEventType


def test_event_bus_stays_bounded_under_flood() -> None:
    bus = BoundedExecutionEventBus(maxsize=8)
    for i in range(500):
        bus.emit(
            ExecutionEvent(
                type=ExecutionEventType.TOOL_STARTED,
                run_id="load",
                payload={"tool_name": "echo", "iteration": i},
            )
        )
    assert bus.qsize <= 8
    assert bus.dropped == 492

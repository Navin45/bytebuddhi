"""Canonical application execution events.

SSE/CLI/VS Code adapters consume these. They are not a second runtime and
must never carry secrets, prompts, tool arguments, or memory records.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ExecutionEventType(StrEnum):
    RUN_STARTED = "run_started"
    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    CHILD_AGENT_STARTED = "child_agent_started"
    CHILD_AGENT_COMPLETED = "child_agent_completed"
    ARTIFACT_CREATED = "artifact_created"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    RUN_INTERRUPTED = "run_interrupted"
    RUN_TIMED_OUT = "run_timed_out"
    RUN_QUEUED = "run_queued"
    RUN_CANCEL_REQUESTED = "run_cancel_requested"
    ASSISTANT_DELTA = "assistant_delta"
    MESSAGE_CREATED = "message_created"
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"
    TOOL_APPROVED = "tool_approved"
    TOOL_REJECTED = "tool_rejected"


_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "run_id",
        "tool_name",
        "action",
        "risk_level",
        "reason",
        "decision",
        "approved",
        "status",
        "child_run_id",
        "artifact_id",
        "iteration",
        "delta",
        "message_id",
        "conversation_id",
        "assistant_message_id",
        "error_code",
        "error_message",
        "duration_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "execution_attempt",
    }
)
ALLOWED_EXECUTION_PAYLOAD_KEYS = _ALLOWED_PAYLOAD_KEYS


@dataclass(frozen=True)
class ExecutionEvent:
    type: ExecutionEventType
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def public_payload(self) -> dict[str, Any]:
        safe: dict[str, Any] = {"run_id": self.run_id, "type": self.type.value, "ts": self.ts}
        for key, value in self.payload.items():
            if key in _ALLOWED_PAYLOAD_KEYS and not isinstance(value, (dict, list)):
                safe[key] = value
        return safe


@runtime_checkable
class ExecutionEventSink(Protocol):
    def emit(self, event: ExecutionEvent) -> None: ...

    def close(self) -> None: ...


async def publish_execution_event(sink: ExecutionEventSink | None, event: ExecutionEvent) -> None:
    """Deliver one runtime event. Durable sinks persist before this returns."""
    if sink is None:
        return
    aemit = getattr(sink, "aemit", None)
    if aemit is not None:
        await aemit(event)
        return
    sink.emit(event)


def sink_is_durable(sink: ExecutionEventSink | None) -> bool:
    return sink is not None and getattr(sink, "aemit", None) is not None


class BoundedExecutionEventBus:
    """In-process event bus with a bounded queue.

    Overflow drops the oldest event. Producers never block.
    Late clients are not replayed; this bus is not a durable event store.
    """

    def __init__(self, maxsize: int = 64) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._queue: asyncio.Queue[ExecutionEvent | None] = asyncio.Queue(maxsize=maxsize)
        self.maxsize = maxsize
        self.dropped = 0
        self._closed = False

    def emit(self, event: ExecutionEvent) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self.dropped += 1
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped += 1

    def close(self) -> None:
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self.dropped += 1
            with suppress(asyncio.QueueFull):
                self._queue.put_nowait(None)

    async def __aiter__(self) -> AsyncIterator[ExecutionEvent]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

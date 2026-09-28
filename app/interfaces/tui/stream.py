"""Follow one run. Reconnect resumes that run id and never creates another."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Protocol

from app.application.runs.sequence import SequenceGap
from app.infrastructure.config.logger import get_logger
from app.interfaces.api.schemas.run_schema import RunEventPage
from app.interfaces.gateway.errors import GatewayTimeout, GatewayUnavailable

logger = get_logger(__name__)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


TERMINAL_EVENTS = frozenset({"run_completed", "run_failed", "run_cancelled", "run_interrupted"})
MAX_RECONNECTS = 3

StatusCallback = Callable[[str, int], Awaitable[None]]
EventCallback = Callable[[Mapping[str, object]], Awaitable[None]]


class RunSocket(Protocol):
    def read_run_socket(self, run_id: str, *, after_sequence: int = 0) -> AsyncIterator[dict[str, Any]]: ...

    async def get_run_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 200) -> RunEventPage: ...


class RunStreamController:
    """Sequence, catch-up, and reconnect for a run the caller already created."""

    def __init__(
        self,
        socket: RunSocket,
        *,
        max_reconnects: int = MAX_RECONNECTS,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._socket = socket
        self._max_reconnects = max_reconnects
        self._sleep = sleep or asyncio.sleep
        self.run_id: str | None = None
        self.last_sequence = 0
        self._stop = asyncio.Event()
        self._terminal = False
        self._task: asyncio.Task[None] | None = None

    def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def follow(self, run_id: str, on_event: EventCallback, on_status: StatusCallback) -> None:
        self.run_id = run_id
        self._task = asyncio.current_task()
        failures = 0
        try:
            while not self._stop.is_set() and not self._terminal:
                try:
                    await on_status("connected", failures)
                    async for raw in self._socket.read_run_socket(run_id, after_sequence=self.last_sequence):
                        if self._stop.is_set() or await self._accept(raw, on_event):
                            return
                    raise GatewayUnavailable("Run stream closed")
                except asyncio.CancelledError:
                    raise
                except (GatewayUnavailable, GatewayTimeout, SequenceGap) as exc:
                    failures += 1
                    logger.warning(
                        "tui_stream_interrupted",
                        run_id=run_id,
                        error_type=type(exc).__name__,
                        attempt=failures,
                    )
                    if failures > self._max_reconnects or self._stop.is_set():
                        await on_status("disconnected", failures)
                        return
                    await on_status("reconnecting", failures)
                    await self._catch_up(on_event)
                    if self._terminal or self._stop.is_set():
                        return
                    await self._sleep(min(0.2 * (2 ** (failures - 1)), 2.0))
        finally:
            self._task = None

    async def _accept(self, raw: Mapping[str, object], on_event: EventCallback) -> bool:
        sequence = _as_int(raw.get("sequence"))
        if sequence is None or sequence <= self.last_sequence:
            return self._terminal
        if sequence != self.last_sequence + 1:
            await self._catch_up(on_event)
            if self._terminal or sequence <= self.last_sequence:
                return self._terminal
            if sequence != self.last_sequence + 1:
                raise SequenceGap(self.last_sequence + 1, sequence)
        self.last_sequence = sequence
        await on_event(raw)
        if str(raw.get("type")) in TERMINAL_EVENTS:
            self._terminal = True
        return self._terminal

    async def _catch_up(self, on_event: EventCallback) -> None:
        if self.run_id is None:
            return
        while not self._stop.is_set():
            page = await self._socket.get_run_events(self.run_id, after_sequence=self.last_sequence)
            if not page.events:
                return
            for event in page.events:
                if event.sequence <= self.last_sequence:
                    continue
                if event.sequence != self.last_sequence + 1:
                    return
                self.last_sequence = event.sequence
                await on_event(event.model_dump())
                if event.type in TERMINAL_EVENTS:
                    self._terminal = True
                    return
            if not page.has_more:
                return

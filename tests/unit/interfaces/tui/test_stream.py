"""Reconnect resumes the same run and fills sequence gaps from the event API."""

from __future__ import annotations

import asyncio

import pytest

from app.interfaces.api.schemas.run_schema import RunEvent, RunEventPage
from app.interfaces.gateway.errors import GatewayUnavailable
from app.interfaces.tui.stream import RunStreamController


def _event(sequence: int, event_type: str = "assistant_delta", run_id: str = "run_1") -> dict:
    return {
        "event_id": f"evt-{sequence}",
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "schema_version": 1,
        "created_at": "2026-09-25T00:00:00+00:00",
        "data": {"delta": str(sequence)},
    }


def _page(events: list[dict]) -> RunEventPage:
    parsed = [RunEvent.model_validate(item) for item in events]
    next_sequence = parsed[-1].sequence if parsed else 0
    return RunEventPage(events=parsed, next_sequence=next_sequence, has_more=False)


class _Socket:
    def __init__(self, batches: list[object], pages: dict[int, list[dict]] | None = None) -> None:
        self.batches = list(batches)
        self.pages = pages or {}
        self.reads: list[int] = []
        self.replays: list[int] = []
        self.created_runs = 0

    async def read_run_socket(self, run_id: str, *, after_sequence: int = 0):
        self.reads.append(after_sequence)
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        assert isinstance(batch, list)
        for item in batch:
            if int(item["sequence"]) > after_sequence:
                yield item

    async def get_run_events(self, run_id: str, *, after_sequence: int = 0, limit: int = 200) -> RunEventPage:
        self.replays.append(after_sequence)
        return _page(self.pages.get(after_sequence, []))

    async def create_run(self, **_kwargs: object) -> None:
        self.created_runs += 1


async def _follow(socket: _Socket) -> tuple[list[int], list[tuple[str, int]]]:
    applied: list[int] = []
    statuses: list[tuple[str, int]] = []

    async def on_event(event: object) -> None:
        assert isinstance(event, dict)
        applied.append(int(event["sequence"]))

    async def on_status(connection: str, attempt: int) -> None:
        statuses.append((connection, attempt))

    async def sleep(_seconds: float) -> None:
        return None

    controller = RunStreamController(socket, sleep=sleep)
    await controller.follow("run_1", on_event, on_status)
    return applied, statuses


@pytest.mark.asyncio
async def test_reconnect_replays_after_last_sequence_without_a_new_run() -> None:
    socket = _Socket(
        [
            [_event(1), _event(2)],
            GatewayUnavailable("socket closed"),
            [_event(3), _event(4, "run_completed")],
        ]
    )
    applied, statuses = await _follow(socket)
    assert applied == [1, 2, 3, 4]
    assert 2 in socket.replays
    assert socket.reads[1] == 2
    assert socket.created_runs == 0
    assert ("reconnecting", 1) in statuses
    assert statuses[-1][0] == "connected"


@pytest.mark.asyncio
async def test_sequence_gap_requests_the_missing_event_before_the_later_one() -> None:
    socket = _Socket([[_event(1), _event(2), _event(4, "run_completed")]], pages={2: [_event(3)]})
    applied, _statuses = await _follow(socket)
    assert socket.replays == [2]
    assert applied == [1, 2, 3, 4]
    assert socket.created_runs == 0


@pytest.mark.asyncio
async def test_reconnect_stops_after_the_attempt_limit() -> None:
    socket = _Socket([GatewayUnavailable("down")] * 4)
    slept: list[float] = []

    async def on_event(_event: object) -> None:
        return None

    statuses: list[tuple[str, int]] = []

    async def on_status(connection: str, attempt: int) -> None:
        statuses.append((connection, attempt))

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    controller = RunStreamController(socket, sleep=sleep)
    await controller.follow("run_1", on_event, on_status)
    assert [item[0] for item in statuses if item[0] == "reconnecting"] == ["reconnecting"] * 3
    assert statuses[-1] == ("disconnected", 4)
    assert len(slept) == 3
    assert socket.created_runs == 0


@pytest.mark.asyncio
async def test_stop_cancels_the_stream_task_and_does_not_cancel_the_run() -> None:
    started = asyncio.Event()

    class _Blocked(_Socket):
        async def read_run_socket(self, run_id: str, *, after_sequence: int = 0):
            self.reads.append(after_sequence)
            started.set()
            await asyncio.Event().wait()
            yield _event(1)

    socket = _Blocked([])
    controller = RunStreamController(socket)

    async def on_event(_event: object) -> None:
        return None

    async def on_status(_connection: str, _attempt: int) -> None:
        return None

    task = asyncio.create_task(controller.follow("run_1", on_event, on_status))
    await started.wait()
    controller.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert socket.created_runs == 0

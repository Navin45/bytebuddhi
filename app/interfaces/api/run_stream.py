"""WebSocket delivery for one run. Disconnect does not cancel the run."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import WebSocket, status

from app.application.runs.coordinator import RunCoordinator
from app.application.runs.errors import RunNotFound
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)

TERMINAL_EVENTS = frozenset({"run_completed", "run_failed", "run_cancelled", "run_interrupted"})
SLOW_CLIENT_CODE = 1013


async def serve_run_stream(
    websocket: WebSocket,
    coordinator: RunCoordinator,
    *,
    run_id: str,
    user_id: UUID,
    after_sequence: int,
    keepalive_seconds: float = 15.0,
) -> None:
    await websocket.accept()
    if after_sequence < 0:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        await coordinator.get_run(run_id, user_id)
    except RunNotFound:
        await websocket.close(code=4404)
        return
    subscription = coordinator.bus.subscribe(run_id)
    last = after_sequence
    logger.info("websocket_connected", run_id=run_id, user_id=str(user_id), after_sequence=after_sequence)
    try:
        logger.info("websocket_replay", run_id=run_id, user_id=str(user_id), after_sequence=after_sequence)
        last = await _replay(websocket, coordinator, run_id, user_id, last)
        if await _is_terminal(coordinator, run_id, user_id):
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            return
        while True:
            if subscription.overflowed:
                logger.warning("websocket_disconnected", run_id=run_id, user_id=str(user_id), status="slow_client")
                await websocket.close(code=SLOW_CLIENT_CODE)
                return
            try:
                event = await asyncio.wait_for(subscription.queue.get(), timeout=keepalive_seconds)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            if event.sequence <= last:
                continue
            if event.sequence > last + 1:
                logger.warning(
                    "websocket_gap_detected",
                    run_id=run_id,
                    user_id=str(user_id),
                    sequence=event.sequence,
                    after_sequence=last,
                )
                last = await _replay(websocket, coordinator, run_id, user_id, last)
            if event.sequence == last + 1:
                await websocket.send_json(event.envelope())
                last = event.sequence
            if event.event_type in TERMINAL_EVENTS or await _is_terminal(coordinator, run_id, user_id):
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
                return
    finally:
        coordinator.bus.unsubscribe(subscription)
        logger.info("websocket_disconnected", run_id=run_id, user_id=str(user_id), after_sequence=last)


async def _replay(
    websocket: WebSocket,
    coordinator: RunCoordinator,
    run_id: str,
    user_id: UUID,
    after_sequence: int,
) -> int:
    last = after_sequence
    while True:
        page = await coordinator.list_events(run_id, user_id, after_sequence=last, limit=200)
        for event in page.events:
            await websocket.send_json(event.envelope())
            last = event.sequence
            if event.event_type in TERMINAL_EVENTS:
                return last
        if not page.has_more:
            return last


async def _is_terminal(coordinator: RunCoordinator, run_id: str, user_id: UUID) -> bool:
    from app.application.runs.status import is_terminal

    run = await coordinator.get_run(run_id, user_id)
    return is_terminal(run.status)

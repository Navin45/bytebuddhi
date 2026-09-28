"""Redis live fan-out and run dispatch. PostgreSQL remains the event log."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.application.runs.bus import InProcessRunBus
from app.application.runs.records import RunEventRecord
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)

RUN_QUEUE_KEY = "bytebuddhi:run-queue"
RUN_EVENT_CHANNEL = "bytebuddhi:run-events"


class RedisLiveNotifier:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def publish(self, event: RunEventRecord) -> None:
        payload = json.dumps(event.envelope()).encode("utf-8")
        await self._client.publish(RUN_EVENT_CHANNEL, payload)


class RedisRunQueue:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def enqueue(self, run_id: str) -> None:
        await self._client.lpush(RUN_QUEUE_KEY, run_id.encode("utf-8"))

    async def poll(self, timeout: float) -> str | None:
        item = await self._client.brpop(RUN_QUEUE_KEY, timeout=max(1, int(timeout)))
        if not item:
            return None
        _key, data = item
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return str(data)

    async def claim(self, stop: Any) -> str | None:
        while not stop.is_set():
            item = await self.poll(1)
            if item is not None:
                return item
        return None


class RedisRunListener:
    """Copy another worker's committed events onto the local bus. Duplicates are skipped."""

    def __init__(self, client: Any, bus: InProcessRunBus) -> None:
        self._client = client
        self._bus = bus
        self._task: Any = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._listen(), name="bytebuddhi-run-events")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (Exception, asyncio.CancelledError):
                return

    async def _listen(self) -> None:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(RUN_EVENT_CHANNEL)
        try:
            async for message in pubsub.listen():
                if not isinstance(message, dict) or message.get("type") != "message":
                    continue
                event = _decode(message.get("data"))
                if event is None or self._bus.delivered_locally(event.run_id, event.sequence):
                    continue
                self._bus.publish(event)
        finally:
            try:
                await pubsub.unsubscribe(RUN_EVENT_CHANNEL)
                await pubsub.aclose()
            except Exception as exc:
                logger.warning("run_event_listener_closed", error_type=type(exc).__name__)


def _decode(raw: object) -> RunEventRecord | None:
    from datetime import datetime

    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    try:
        body = json.loads(text)
        created = datetime.fromisoformat(str(body["created_at"]))
    except (ValueError, KeyError, TypeError):
        return None
    data = body.get("data")
    return RunEventRecord(
        event_id=str(body["event_id"]),
        run_id=str(body["run_id"]),
        sequence=int(body["sequence"]),
        event_type=str(body["type"]),
        schema_version=int(body["schema_version"]),
        payload=data if isinstance(data, dict) else {},
        created_at=created,
    )

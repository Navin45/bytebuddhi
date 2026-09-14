"""Redis-backed cancellation fan-out for multi-worker API deployments."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)

RUN_KEY_PREFIX = "bytebuddhi:run:"
CANCEL_CHANNEL = "bytebuddhi:cancel"


class RedisCancellationStore:
    """Implements CancellationStore using Redis SET + PUBLISH/SUBSCRIBE."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def put_run(self, run_id: str, user_id: str, ttl_seconds: int) -> None:
        await self._client.set(f"{RUN_KEY_PREFIX}{run_id}", user_id.encode(), ex=ttl_seconds)

    async def get_owner(self, run_id: str) -> str | None:
        raw = await self._client.get(f"{RUN_KEY_PREFIX}{run_id}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    async def delete_run(self, run_id: str) -> None:
        await self._client.delete(f"{RUN_KEY_PREFIX}{run_id}")

    async def publish_cancel(self, run_id: str, user_id: str) -> None:
        payload = f"{run_id}\t{user_id}".encode()
        await self._client.publish(CANCEL_CHANNEL, payload)

    async def listen_cancels(self) -> AsyncIterator[tuple[str, str]]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(CANCEL_CHANNEL)
        try:
            async for message in pubsub.listen():
                if not isinstance(message, dict) or message.get("type") != "message":
                    continue
                data = message.get("data")
                text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
                if "\t" not in text:
                    continue
                run_id, user_id = text.split("\t", 1)
                yield run_id, user_id
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(CANCEL_CHANNEL)
                await pubsub.aclose()

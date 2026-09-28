"""Bounded live subscriptions. Durable events stay in the run store."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.application.runs.records import RunEventRecord


@dataclass
class RunSubscription:
    run_id: str
    queue: asyncio.Queue[RunEventRecord]
    overflowed: bool = False
    closed: bool = field(default=False)


class InProcessRunBus:
    """Fans a committed event out to local WebSocket subscribers."""

    def __init__(self, maxsize: int = 32) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.maxsize = maxsize
        self._subscribers: dict[str, list[RunSubscription]] = {}
        self._local: set[tuple[str, int]] = set()

    def subscribe(self, run_id: str) -> RunSubscription:
        subscription = RunSubscription(run_id=run_id, queue=asyncio.Queue(maxsize=self.maxsize))
        self._subscribers.setdefault(run_id, []).append(subscription)
        return subscription

    def unsubscribe(self, subscription: RunSubscription) -> None:
        subscription.closed = True
        current = self._subscribers.get(subscription.run_id, [])
        self._subscribers[subscription.run_id] = [item for item in current if item is not subscription]

    def remember(self, event: RunEventRecord) -> None:
        self._local.add((event.run_id, event.sequence))
        if len(self._local) > 5000:
            self._local.clear()

    def delivered_locally(self, run_id: str, sequence: int) -> bool:
        return (run_id, sequence) in self._local

    def publish(self, event: RunEventRecord) -> None:
        for subscription in list(self._subscribers.get(event.run_id, [])):
            if subscription.closed:
                continue
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                subscription.overflowed = True

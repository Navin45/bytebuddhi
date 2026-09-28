"""One coordinated pass over expired leases. It does not replay the agent."""

from __future__ import annotations

from typing import Protocol

from app.application.ports.output.logger import get_logger
from app.application.runs.metrics import RunMetrics
from app.application.runs.records import RunEventRecord
from app.application.runs.writer import EventWriter

logger = get_logger(__name__)


class StaleRunStore(Protocol):
    async def interrupt_stale(self, *, limit: int) -> list[RunEventRecord]: ...


class ReaperLock(Protocol):
    async def try_acquire(self) -> bool: ...

    async def release(self) -> None: ...


class AlwaysLeader:
    """In-process tests. Production uses a Postgres advisory lock."""

    async def try_acquire(self) -> bool:
        return True

    async def release(self) -> None:
        return None


class RunReaper:
    def __init__(self, store: StaleRunStore, writer: EventWriter, *, batch_size: int, metrics: RunMetrics) -> None:
        self._store = store
        self._writer = writer
        self._batch_size = batch_size
        self._metrics = metrics

    async def run_once(self) -> int:
        events = await self._store.interrupt_stale(limit=self._batch_size)
        for event in events:
            self._metrics.add("stale_runs")
            self._metrics.add("recovered_runs")
            self._metrics.add("lease_expirations")
            self._metrics.add("worker_crashes")
            await self._writer.notify(event)
            logger.info(
                "run_interrupted",
                run_id=event.run_id,
                sequence=event.sequence,
                status="interrupted",
                event_type=event.event_type,
            )
        return len(events)

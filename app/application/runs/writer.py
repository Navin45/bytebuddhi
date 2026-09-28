"""Persist an event, then notify live subscribers. Redis failure does not roll the event back."""

from __future__ import annotations

from typing import Protocol

from app.application.ports.output.logger import get_logger
from app.application.runs.bus import InProcessRunBus
from app.application.runs.records import MAX_EVENT_TEXT, RunEventRecord
from app.application.runs.store import RunStore
from app.application.runtime.events import ExecutionEvent

logger = get_logger(__name__)

_SCALAR = (str, int, float, bool)


class LiveNotifier(Protocol):
    async def publish(self, event: RunEventRecord) -> None: ...


class NullNotifier:
    async def publish(self, event: RunEventRecord) -> None:
        return None


class EventWriter:
    def __init__(self, store: RunStore, bus: InProcessRunBus, notifier: LiveNotifier | None = None) -> None:
        self._store = store
        self._bus = bus
        self._notifier = notifier or NullNotifier()

    async def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        lease_token: str | None = None,
    ) -> RunEventRecord:
        bounded = _bound_payload(payload)
        record = await self._store.append_event(run_id, event_type, bounded, lease_token=lease_token)
        logger.info(
            "run_event_persisted",
            run_id=run_id,
            sequence=record.sequence,
            event_type=event_type,
            status=event_type,
        )
        await self.notify(record)
        return record

    async def notify(self, record: RunEventRecord) -> None:
        self._bus.remember(record)
        self._bus.publish(record)
        try:
            await self._notifier.publish(record)
        except Exception as exc:
            logger.warning(
                "run_live_notify_failed",
                run_id=record.run_id,
                sequence=record.sequence,
                event_type=record.event_type,
                error_type=type(exc).__name__,
            )

    async def append_execution(self, event: ExecutionEvent, *, lease_token: str | None = None) -> list[RunEventRecord]:
        written: list[RunEventRecord] = []
        for event_type, payload in _execution_payloads(event):
            written.append(await self.append(event.run_id, event_type, payload, lease_token=lease_token))
        return written


class DurableEventSink:
    """Application sink. `aemit` commits the event before the agent continues."""

    def __init__(self, writer: EventWriter, run_id: str, lease_token: str | None = None) -> None:
        self._writer = writer
        self.run_id = run_id
        self.lease_token = lease_token
        self.delta_count = 0

    async def aemit(self, event: ExecutionEvent) -> None:
        records = await self._writer.append_execution(event, lease_token=self.lease_token)
        self.delta_count += sum(1 for item in records if item.event_type == "assistant_delta")

    def emit(self, event: ExecutionEvent) -> None:
        raise RuntimeError("DurableEventSink persists asynchronously via aemit")

    def close(self) -> None:
        return None


def _execution_payloads(event: ExecutionEvent) -> list[tuple[str, dict[str, object]]]:
    payload = _public_fields(event.payload)
    if event.type.value != "assistant_delta":
        return [(event.type.value, payload)]
    text = str(event.payload.get("delta") or "")
    if not text:
        return []
    chunks = [text[index : index + MAX_EVENT_TEXT] for index in range(0, len(text), MAX_EVENT_TEXT)]
    return [("assistant_delta", {**payload, "delta": chunk}) for chunk in chunks]


def _public_fields(payload: dict[str, object]) -> dict[str, object]:
    from app.application.runtime.events import ALLOWED_EXECUTION_PAYLOAD_KEYS

    safe: dict[str, object] = {}
    for key, value in payload.items():
        if key not in ALLOWED_EXECUTION_PAYLOAD_KEYS or key == "delta":
            continue
        if isinstance(value, str):
            safe[key] = value[:MAX_EVENT_TEXT]
        elif isinstance(value, _SCALAR) or value is None:
            safe[key] = value
    return safe


def _bound_payload(payload: dict[str, object]) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            bounded[key] = value[:MAX_EVENT_TEXT]
        elif isinstance(value, _SCALAR) or value is None:
            bounded[key] = value
    return bounded

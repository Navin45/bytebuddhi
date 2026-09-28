"""Queue a run, execute it outside the HTTP request, and record its events."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.output.logger import get_logger
from app.application.runs.admission import AdmissionDenied, AdmissionUnavailable, RunAdmission, UnlimitedAdmission
from app.application.runs.bus import InProcessRunBus
from app.application.runs.config import RunExecutionConfig
from app.application.runs.errors import (
    IdempotencyConflict,
    InvalidEventCursor,
    LeaseLost,
    RunAlreadyCompleted,
    RunNotFound,
    public_failure_message,
)
from app.application.runs.identity import WorkerIdentity
from app.application.runs.metrics import RunMetrics
from app.application.runs.reaper import AlwaysLeader, ReaperLock, RunReaper
from app.application.runs.records import EVENT_PAGE_LIMIT, EventPage, RunRecord
from app.application.runs.status import RunStatus, is_terminal
from app.application.runs.store import RunStore, utc_now
from app.application.runs.writer import DurableEventSink, EventWriter, LiveNotifier
from app.application.runtime.approval import RunApprovalRegistry
from app.application.runtime.cancellation import CancellationToken, RunCancellationRegistry
from app.application.runtime.events import ExecutionEvent, ExecutionEventType
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskResult

logger = get_logger(__name__)

CLAIM_POLL_SECONDS = 0.5


class RunQueue(Protocol):
    async def enqueue(self, run_id: str) -> None: ...

    async def poll(self, timeout: float) -> str | None: ...


class LocalRunQueue:
    """In-process queue. A Redis queue can satisfy the same protocol."""

    def __init__(self) -> None:
        self._items: asyncio.Queue[str] = asyncio.Queue()

    async def enqueue(self, run_id: str) -> None:
        await self._items.put(run_id)

    async def poll(self, timeout: float) -> str | None:
        try:
            return await asyncio.wait_for(self._items.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def claim(self, stop: asyncio.Event) -> str | None:
        while not stop.is_set():
            item = await self.poll(CLAIM_POLL_SECONDS)
            if item is not None:
                return item
        return None


class RunAuthorizer(Protocol):
    async def authorize(
        self,
        *,
        user_id: UUID,
        project_id: UUID | None,
        conversation_id: UUID | None,
    ) -> UUID | None: ...


class AllowRun:
    async def authorize(
        self,
        *,
        user_id: UUID,
        project_id: UUID | None,
        conversation_id: UUID | None,
    ) -> UUID | None:
        return project_id


ExecuteRun = Callable[[ExecuteTaskCommand], Awaitable[ExecuteTaskResult]]


class RunCoordinator:
    def __init__(
        self,
        store: RunStore,
        bus: InProcessRunBus,
        queue: RunQueue,
        execute_run: ExecuteRun,
        *,
        notifier: LiveNotifier | None = None,
        authorizer: RunAuthorizer | None = None,
        admission: RunAdmission | None = None,
        cancellation: RunCancellationRegistry | None = None,
        approval: RunApprovalRegistry | None = None,
        config: RunExecutionConfig | None = None,
        identity: WorkerIdentity | None = None,
        reaper_lock: ReaperLock | None = None,
        metrics: RunMetrics | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.queue = queue
        self._execute_run = execute_run
        self.writer = EventWriter(store, bus, notifier)
        self._authorizer = authorizer or AllowRun()
        self._admission = admission or UnlimitedAdmission()
        self._cancellation = cancellation
        self._approval = approval or RunApprovalRegistry()
        self._config = config or RunExecutionConfig()
        self._config.validate()
        self._identity = identity or WorkerIdentity.create()
        self._metrics = metrics or RunMetrics()
        self._reaper = RunReaper(store, self.writer, batch_size=self._config.reaper_batch_size, metrics=self._metrics)
        self._reaper_lock = reaper_lock or AlwaysLeader()
        self._stop = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._reaper_task: asyncio.Task[None] | None = None
        self._active: asyncio.Task[None] | None = None
        self.admission_mode = self._admission.mode

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._loop(), name="bytebuddhi-run-worker")
        self._reaper_task = asyncio.create_task(self._reap_loop(), name="bytebuddhi-run-reaper")

    async def stop(self) -> None:
        self._stop.set()
        worker = self._worker
        reaper = self._reaper_task
        self._worker = None
        self._reaper_task = None
        if worker is not None:
            try:
                await asyncio.wait_for(asyncio.shield(worker), timeout=self._config.shutdown_grace_seconds)
            except TimeoutError:
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
        if reaper is not None:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
        await self._reaper_lock.release()

    async def create_run(
        self,
        *,
        user_id: UUID,
        prompt: str,
        project_id: UUID | None,
        conversation_id: UUID | None,
        provider: str | None,
        model: str | None,
        idempotency_key: str | None,
    ) -> RunRecord:
        project_id = await self._authorizer.authorize(
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if idempotency_key:
            existing = await self.store.find_idempotent(user_id, idempotency_key)
            if existing is not None:
                if existing.prompt_sha256 != prompt_hash:
                    raise IdempotencyConflict()
                return existing
        run = RunRecord(
            id=str(uuid4()),
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
            status=RunStatus.QUEUED,
            prompt=prompt,
            prompt_sha256=prompt_hash,
            provider=provider,
            model=model,
            created_at=utc_now(),
            idempotency_key=idempotency_key,
        )
        stored = await self.store.insert(run)
        if stored.id != run.id:
            if stored.prompt_sha256 != prompt_hash:
                raise IdempotencyConflict()
            return stored
        await self.writer.append(stored.id, "run_queued", {"conversation_id": _uuid_text(conversation_id)})
        self._metrics.add("queued_runs")
        await self.queue.enqueue(stored.id)
        logger.info(
            "run_created",
            run_id=stored.id,
            user_id=str(user_id),
            project_id=str(project_id) if project_id else None,
            status=RunStatus.QUEUED.value,
        )
        logger.info("run_queued", run_id=stored.id, user_id=str(user_id), status=RunStatus.QUEUED.value)
        return await self._require(stored.id, user_id)

    async def get_run(self, run_id: str, user_id: UUID) -> RunRecord:
        return await self._require(run_id, user_id)

    async def list_events(self, run_id: str, user_id: UUID, *, after_sequence: int, limit: int) -> EventPage:
        if after_sequence < 0 or limit < 1:
            raise InvalidEventCursor()
        await self._require(run_id, user_id)
        bounded = min(limit, EVENT_PAGE_LIMIT)
        return await self.store.list_events(run_id, after_sequence=after_sequence, limit=bounded)

    async def cancel(self, run_id: str, user_id: UUID) -> RunRecord:
        run = await self._require(run_id, user_id)
        if run.status == RunStatus.COMPLETED:
            raise RunAlreadyCompleted()
        if run.status in {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.INTERRUPTED}:
            return run
        logger.info("run_cancel_requested", run_id=run_id, user_id=str(user_id), status=run.status.value)
        await self.writer.append(run_id, "run_cancel_requested", {})
        if self._cancellation is not None:
            await self._cancellation.request_cancel(run_id, user_id)
        await self._approval.cancel_run(run_id)
        current = await self._require(run_id, user_id)
        if current.status == RunStatus.QUEUED:
            await self.writer.append(run_id, "run_cancelled", {"error_code": "RUN_CANCELLED"})
            logger.info("run_cancelled", run_id=run_id, user_id=str(user_id), status=RunStatus.CANCELLED.value)
        return await self._require(run_id, user_id)

    async def resolve_approval(
        self,
        run_id: str,
        user_id: UUID,
        action: str,
        approved: bool,
    ) -> bool:
        await self._require(run_id, user_id)
        return await self._approval.resolve(
            run_id=run_id,
            user_id=user_id,
            action=action,
            approved=approved,
        )

    async def _require(self, run_id: str, user_id: UUID) -> RunRecord:
        run = await self.store.get_for_user(run_id, user_id)
        if run is None:
            raise RunNotFound()
        return run

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                hinted = await self.queue.poll(CLAIM_POLL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._metrics.add("redis_unavailable")
                logger.warning("run_queue_unavailable", error_type=type(exc).__name__)
                await asyncio.sleep(CLAIM_POLL_SECONDS)
                continue
            if self._stop.is_set():
                return
            try:
                await self._claim_and_execute(hinted)
            except asyncio.CancelledError:
                if self._stop.is_set():
                    raise
                self._metrics.add("worker_crashes")
                logger.error("worker_failed_run", run_id=hinted, error_type="CancelledError")
            except Exception as exc:
                self._metrics.add("worker_crashes")
                logger.error("worker_failed_run", run_id=hinted, error_type=type(exc).__name__)

    async def _reap_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if await self._reaper_lock.try_acquire():
                    await self._reaper.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._metrics.add("postgres_errors")
                logger.error("reaper_failed", error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._config.reaper_interval_seconds)
            except TimeoutError:
                continue

    async def _claim_and_execute(self, hinted: str | None) -> None:
        worker_id = self._identity.worker_id
        lease_seconds = self._config.lease_timeout_seconds
        if hinted:
            reserved = await self.store.claim_run(hinted, worker_id=worker_id, lease_seconds=lease_seconds)
            if reserved is None:
                self._metrics.add("run_claim_conflicts")
                return
        else:
            reserved = await self.store.claim_next(worker_id=worker_id, lease_seconds=lease_seconds)
            if reserved is None:
                return
        self._metrics.add("run_claims")
        admitted = False
        try:
            await self._admission.acquire(reserved.id, worker_id, lease_seconds)
            admitted = True
            self._metrics.add("admission_acquires")
        except AdmissionDenied:
            self._metrics.add("admission_rejections")
            await self.store.release_reservation(reserved.id, reserved.lease_token or "")
            await self.queue.enqueue(reserved.id)
            await asyncio.sleep(min(0.2, self._config.heartbeat_seconds))
            return
        except AdmissionUnavailable:
            self._metrics.add("redis_unavailable")
            logger.warning("admission_unavailable", run_id=reserved.id, status="queued")
            await self.store.release_reservation(reserved.id, reserved.lease_token or "")
            await self.queue.enqueue(reserved.id)
            await asyncio.sleep(CLAIM_POLL_SECONDS)
            return
        active = await self.store.activate(reserved.id, reserved.lease_token or "", lease_seconds=lease_seconds)
        if active is None or active.lease_token is None:
            if admitted:
                await self._admission.release(reserved.id, worker_id)
                self._metrics.add("admission_releases")
            return
        logger.info(
            "worker_claimed_run",
            run_id=active.id,
            user_id=str(active.user_id),
            project_id=_uuid_text(active.project_id),
            status=active.status.value,
        )
        self._metrics.add("active_runs")
        try:
            await self._execute(active)
        finally:
            await self._admission.release(active.id, worker_id)
            self._metrics.add("admission_releases")

    async def _execute(self, run: RunRecord) -> None:
        if run.cancellation_requested:
            await self._finish_cancelled(run)
            return
        sink = DurableEventSink(self.writer, run.id, run.lease_token)
        token = CancellationToken()
        if self._cancellation is not None:
            await self._cancellation.register(run.id, run.user_id, token)
        started = asyncio.get_running_loop().time()
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(run.id, run.lease_token or "", token, lease_lost))
        try:
            result = await self._execute_run(
                ExecuteTaskCommand(
                    prompt=run.prompt,
                    user_id=run.user_id,
                    project_id=run.project_id,
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    cancellation_token=token,
                    event_sink=sink,
                    approval_registry=self._approval,
                    model_provider=run.provider,
                    model_name=run.model,
                )
            )
            if lease_lost.is_set():
                logger.warning("worker_lost_lease", run_id=run.id, user_id=str(run.user_id), status="interrupted")
                return
            if token.is_cancelled() or self._stop.is_set():
                if self._stop.is_set():
                    await self.store.abandon_lease(run.id, run.lease_token or "")
                    return
                await self._finish_cancelled(run)
                return
            await self._finish_result(run, result, sink, started)
        except LeaseLost:
            logger.warning("worker_lost_lease", run_id=run.id, user_id=str(run.user_id), status="interrupted")
        except asyncio.CancelledError:
            if self._stop.is_set():
                await self.store.abandon_lease(run.id, run.lease_token or "")
                raise
            await self._finish_cancelled(run)
        except Exception as exc:
            logger.error(
                "worker_failed_run",
                run_id=run.id,
                user_id=str(run.user_id),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            try:
                await self._append_terminal(
                    run.id,
                    run.lease_token,
                    "run_failed",
                    {"error_code": "RUN_EXECUTION_FAILED", "error_message": public_failure_message(exc)},
                )
            except LeaseLost:
                logger.warning("worker_lost_lease", run_id=run.id, user_id=str(run.user_id), status="interrupted")
        finally:
            heartbeat.cancel()
            await self._approval.clear_run(run.id)
            if self._cancellation is not None:
                await self._cancellation.release(run.id)

    async def _finish_result(
        self,
        run: RunRecord,
        result: ExecuteTaskResult,
        sink: DurableEventSink,
        started: float,
    ) -> None:
        conversation_id = _maybe_uuid(result.conversation_id)
        try:
            await self.store.update_conversation(run.id, conversation_id, lease_token=run.lease_token)
        except LeaseLost:
            logger.warning("worker_lost_lease", run_id=run.id, user_id=str(run.user_id), status="interrupted")
            return
        if sink.delta_count == 0 and result.response:
            for chunk in _chunks(result.response):
                await sink.aemit(
                    ExecutionEvent(
                        type=ExecutionEventType.ASSISTANT_DELTA,
                        run_id=run.id,
                        payload={"delta": chunk},
                    )
                )
        status = result.run_state.status.value if result.run_state.status else "failed"
        duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        usage = result.run_state.token_usage
        payload: dict[str, object] = {
            "conversation_id": str(conversation_id or run.conversation_id or ""),
            "duration_ms": duration_ms,
        }
        if result.assistant_message_id is not None:
            payload["assistant_message_id"] = str(result.assistant_message_id)
        if usage is not None:
            payload["prompt_tokens"] = usage.prompt_tokens
            payload["completion_tokens"] = usage.completion_tokens
            payload["total_tokens"] = usage.total_tokens
        if status == "cancelled" or run.cancellation_requested:
            await self._append_terminal(
                run.id, run.lease_token, "run_cancelled", {"error_code": "RUN_CANCELLED", **payload}
            )
            logger.info("run_cancelled", run_id=run.id, user_id=str(run.user_id), duration_ms=duration_ms)
            return
        if status == "completed":
            await self._append_terminal(run.id, run.lease_token, "run_completed", payload)
            logger.info(
                "run_completed",
                run_id=run.id,
                user_id=str(run.user_id),
                project_id=_uuid_text(run.project_id),
                duration_ms=duration_ms,
                status="completed",
            )
            return
        message = result.run_state.error.message if result.run_state.error is not None else "Run execution failed"
        await self._append_terminal(
            run.id,
            run.lease_token,
            "run_failed",
            {
                "error_code": "RUN_EXECUTION_FAILED",
                "error_message": public_failure_message(RuntimeError(message)),
                **payload,
            },
        )
        logger.info("run_failed", run_id=run.id, user_id=str(run.user_id), status="failed", duration_ms=duration_ms)

    async def _finish_cancelled(self, run: RunRecord) -> None:
        current = await self.store.get(run.id)
        if current is None or is_terminal(current.status):
            return
        try:
            await self._append_terminal(run.id, run.lease_token, "run_cancelled", {"error_code": "RUN_CANCELLED"})
        except LeaseLost:
            logger.warning("worker_lost_lease", run_id=run.id, user_id=str(run.user_id), status="interrupted")
            return
        logger.info("run_cancelled", run_id=run.id, user_id=str(run.user_id), status="cancelled")

    async def _append_terminal(
        self,
        run_id: str,
        lease_token: str | None,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        current = await self.store.get(run_id)
        if current is None or is_terminal(current.status):
            return
        if current.status == RunStatus.QUEUED and event_type in {"run_completed", "run_failed", "run_cancelled"}:
            await self.writer.append(run_id, "run_started", {}, lease_token=lease_token)
        await self.writer.append(run_id, event_type, payload, lease_token=lease_token)

    async def _heartbeat(
        self,
        run_id: str,
        lease_token: str,
        token: CancellationToken,
        lease_lost: asyncio.Event,
    ) -> None:
        failures = 0
        while not token.is_cancelled() and not self._stop.is_set() and not lease_lost.is_set():
            await asyncio.sleep(self._config.heartbeat_seconds)
            if token.is_cancelled() or self._stop.is_set():
                return
            try:
                owned = await self.store.renew_lease(
                    run_id,
                    lease_token,
                    lease_seconds=self._config.lease_timeout_seconds,
                )
                if not owned:
                    self._lose_lease(lease_lost, token)
                    return
                renewed = await self._admission.renew(
                    run_id,
                    self._identity.worker_id,
                    self._config.lease_timeout_seconds,
                )
                if not renewed:
                    self._lose_lease(lease_lost, token)
                    return
                failures = 0
                self._metrics.add("lease_renewals")
            except AdmissionUnavailable:
                failures += 1
                self._metrics.add("redis_unavailable")
                logger.warning(
                    "lease_renew_failed",
                    run_id=run_id,
                    error_type="AdmissionUnavailable",
                    status="running",
                )
                if failures >= self._config.heartbeat_retries:
                    self._lose_lease(lease_lost, token)
                    return
                await asyncio.sleep(min(0.2 * (2 ** (failures - 1)), 2.0))
            except Exception as exc:
                failures += 1
                self._metrics.add("postgres_errors")
                logger.warning(
                    "lease_renew_failed",
                    run_id=run_id,
                    error_type=type(exc).__name__,
                    status="running",
                )
                if failures >= self._config.heartbeat_retries:
                    self._lose_lease(lease_lost, token)
                    return
                await asyncio.sleep(min(0.2 * (2 ** (failures - 1)), 2.0))

    def _lose_lease(self, lease_lost: asyncio.Event, token: CancellationToken) -> None:
        """Stop agent work without writing a terminal event the worker no longer owns."""
        lease_lost.set()
        token.cancel()


def _chunks(text: str, size: int = 2000) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or []


def _uuid_text(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _maybe_uuid(value: UUID | str | None) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None

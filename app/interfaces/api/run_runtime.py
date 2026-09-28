"""Process-wide run worker. The HTTP request does not execute the agent."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.application.runs.admission import LocalAdmission, RunAdmission
from app.application.runs.bus import InProcessRunBus
from app.application.runs.config import RunExecutionConfig
from app.application.runs.coordinator import LocalRunQueue, RunCoordinator
from app.application.runs.identity import WorkerIdentity
from app.application.runs.metrics import RunMetrics
from app.application.runtime.cancellation import get_run_cancellation_registry
from app.application.use_cases.agent.execute_task import ExecuteTaskCommand, ExecuteTaskResult
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings
from app.infrastructure.observability import get_meter

logger = get_logger(__name__)

_coordinator: RunCoordinator | None = None
_listener: Any = None


async def execute_persisted_run(command: ExecuteTaskCommand) -> ExecuteTaskResult:
    """Open a session and run the existing application graph. Not a second runtime."""
    from app.infrastructure.config.profile import is_standalone
    from app.interfaces.composition import compose_application_graph

    if is_standalone():
        from app.infrastructure.persistence.sqlite.database import open_session

        graph = compose_application_graph(open_session())
        use_case = graph.execute_task
        if use_case is None:
            raise RuntimeError("ExecuteTaskUseCase is not configured")
        return await use_case.execute(command)

    from app.infrastructure.persistence.postgres.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        graph = compose_application_graph(session)
        use_case = graph.execute_task
        if use_case is None:
            raise RuntimeError("ExecuteTaskUseCase is not configured")
        try:
            result = await use_case.execute(command)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def start_run_worker(redis_client: Any | None) -> RunCoordinator:
    global _coordinator, _listener
    from app.infrastructure.config.profile import is_standalone

    bus = InProcessRunBus()
    config = _execution_config()
    if is_standalone():
        from app.application.runs.reaper import AlwaysLeader
        from app.infrastructure.config.profile import sqlite_database_path
        from app.infrastructure.persistence.sqlite.database import initialize
        from app.infrastructure.persistence.sqlite.run_store import SqliteRunStore, recover_standalone_runs

        initialize(sqlite_database_path())
        store: Any = SqliteRunStore(sqlite_database_path())
        await recover_standalone_runs(store)
        queue: Any = LocalRunQueue()
        notifier = None
        admission: RunAdmission = LocalAdmission(config.max_active_runs)
        reaper_lock = AlwaysLeader()
        _coordinator = RunCoordinator(
            store,
            bus,
            queue,
            execute_persisted_run,
            notifier=notifier,
            admission=admission,
            cancellation=get_run_cancellation_registry(),
            config=config,
            identity=WorkerIdentity.create(),
            reaper_lock=reaper_lock,
            metrics=RunMetrics(get_meter()),
        )
        await _coordinator.start()
        logger.info("run_worker_started", status="running", profile="standalone")
        return _coordinator

    from app.infrastructure.persistence.postgres.database import AsyncSessionLocal
    from app.infrastructure.persistence.postgres.reaper_lock import PostgresReaperLock
    from app.infrastructure.persistence.postgres.run_store import SqlRunStore

    store = SqlRunStore(AsyncSessionLocal)
    if redis_client is not None:
        from app.infrastructure.persistence.redis.run_admission import RedisRunAdmission
        from app.infrastructure.persistence.redis.run_fanout import RedisLiveNotifier, RedisRunListener, RedisRunQueue

        queue = RedisRunQueue(redis_client)
        notifier = RedisLiveNotifier(redis_client)
        admission = RedisRunAdmission(redis_client, config.max_active_runs)
        _listener = RedisRunListener(redis_client, bus)
        await _listener.start()
    else:
        queue = LocalRunQueue()
        notifier = None
        admission = LocalAdmission(config.max_active_runs)
        logger.warning("run_admission_local", status="degraded")
    _coordinator = RunCoordinator(
        store,
        bus,
        queue,
        execute_persisted_run,
        notifier=notifier,
        admission=admission,
        cancellation=get_run_cancellation_registry(),
        config=config,
        identity=WorkerIdentity.create(),
        reaper_lock=PostgresReaperLock(AsyncSessionLocal),
        metrics=RunMetrics(get_meter()),
    )
    await _coordinator.start()
    logger.info("run_worker_started", status="running")
    return _coordinator


async def stop_run_worker() -> None:
    global _coordinator, _listener
    if _listener is not None:
        await _listener.stop()
        _listener = None
    if _coordinator is not None:
        await _coordinator.stop()
        _coordinator = None


def get_run_coordinator() -> RunCoordinator:
    if _coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "GATEWAY_UNAVAILABLE", "message": "Run worker is not running"},
        )
    return _coordinator


def execution_health() -> dict[str, str]:
    if _coordinator is None:
        return {"worker": "unavailable", "admission": "unavailable", "execution": "unavailable"}
    from app.infrastructure.config.profile import is_standalone

    mode = _coordinator.admission_mode
    if is_standalone():
        execution = "ready"
    elif mode == "local":
        execution = "degraded"
    else:
        execution = "ok"
    return {"worker": "ok", "admission": mode, "execution": execution}


def _execution_config() -> RunExecutionConfig:
    config = RunExecutionConfig(
        max_active_runs=settings.max_active_runs,
        heartbeat_seconds=settings.run_heartbeat_seconds,
        lease_timeout_seconds=settings.run_lease_timeout_seconds,
        reaper_interval_seconds=settings.reaper_interval_seconds,
        shutdown_grace_seconds=settings.worker_shutdown_grace_seconds,
    )
    config.validate()
    return config

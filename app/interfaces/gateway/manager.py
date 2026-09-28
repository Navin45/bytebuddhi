"""Local gateway lifecycle. Starts the existing FastAPI app in a child process."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app import __version__
from app.infrastructure.config.log_rotation import rotate_log_file
from app.infrastructure.config.logger import get_logger
from app.interfaces.gateway.client import probe_gateway
from app.interfaces.gateway.config import BindAddress, config_dir, start_timeout_seconds
from app.interfaces.gateway.errors import GatewayPortConflict, GatewayStartFailed, GatewayStartTimeout
from app.interfaces.gateway.models import GatewayStatus, ProbeResult
from app.interfaces.gateway.process import (
    GatewayLock,
    port_is_open,
    process_exists,
    request_terminate_signal,
    terminate_process,
)
from app.interfaces.gateway.server import gateway_server_command
from app.interfaces.gateway.state import (
    GatewayState,
    claim_path,
    clear_shutdown,
    clear_state,
    load_state,
    lock_path,
    log_path,
    request_shutdown,
    save_state,
    utc_now,
)

logger = get_logger(__name__)

STOP_GRACE_SECONDS = 10.0
POLL_SECONDS = 0.2

PopenFactory = Callable[..., subprocess.Popen[bytes]]
ProbeFunc = Callable[[str], Awaitable[ProbeResult]]


class GatewayManager:
    """Discover, start, stop, and report the local gateway.

    Stop signals only the process that holds this manager's lock. A PID that
    no longer holds the lock is treated as stale and is not killed.
    """

    def __init__(
        self,
        bind: BindAddress,
        *,
        directory: Path | None = None,
        popen: PopenFactory | None = None,
        process_exists_fn: Callable[[int], bool] | None = None,
        port_open_fn: Callable[[str, int], bool] | None = None,
        probe: ProbeFunc | None = None,
        terminate_fn: Callable[[int], None] | None = None,
        signal_fn: Callable[[int], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        start_timeout: float | None = None,
    ) -> None:
        self.bind = bind
        self.directory = directory if directory is not None else Path(config_dir())
        self._popen = popen or subprocess.Popen
        self._process_exists = process_exists_fn or process_exists
        self._port_open = port_open_fn or port_is_open
        self._probe = probe or probe_gateway
        self._terminate = terminate_fn or terminate_process
        self._signal = signal_fn or request_terminate_signal
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or _asyncio_sleep
        self.start_timeout = start_timeout if start_timeout is not None else start_timeout_seconds()

    async def status(self) -> GatewayStatus:
        self._recover_stale_state()
        return await self._status(message="")

    async def ensure_running(self) -> GatewayStatus:
        current = await self.status()
        if current.ready and current.process_running:
            return current
        if current.process_running or current.managed:
            return await self._wait_until_ready(current.pid)
        return await self.start()

    async def start(self) -> GatewayStatus:
        logger.info(
            "gateway_start_requested",
            command="gateway start",
            host=self.bind.host,
            port=self.bind.port,
            url=self.bind.url,
        )
        self._recover_stale_state()
        if not self._lock_is_free():
            state = load_state(self.directory)
            if state is not None and (state.port != self.bind.port or state.url != self.bind.url):
                raise GatewayPortConflict(
                    f"A local gateway is already running at {state.url}. Stop it before starting {self.bind.url}."
                )
            return await self._wait_until_ready(self._pid())
        if self._port_open(self.bind.host, self.bind.port):
            probe = await self._safe_probe()
            if probe.bytebuddhi:
                return self._status_from_probe(
                    probe, managed=False, message="A ByteBuddhi gateway is already listening"
                )
            raise GatewayPortConflict(
                f"Port {self.bind.port} on {self.bind.host} is already in use by another process. "
                "ByteBuddhi will not stop that process. Choose a different BYTEBUDDHI_GATEWAY_PORT."
            )
        if not self._try_claim():
            return await self._wait_until_ready(self._pid())
        clear_shutdown(self.directory)
        started = self._monotonic()
        process: subprocess.Popen[bytes] | None = None
        try:
            process = self._spawn()
            self._write_state(process.pid)
            logger.info(
                "gateway_process_started",
                command="gateway start",
                host=self.bind.host,
                port=self.bind.port,
                pid=process.pid,
                url=self.bind.url,
            )
            ready = await self._wait_until_ready(process.pid, managed=True)
            logger.info(
                "gateway_ready",
                command="gateway start",
                host=self.bind.host,
                port=self.bind.port,
                pid=process.pid,
                url=self.bind.url,
                version=ready.version,
                duration_ms=int((self._monotonic() - started) * 1000),
            )
            return ready
        except Exception as exc:
            logger.error(
                "gateway_start_failed",
                command="gateway start",
                host=self.bind.host,
                port=self.bind.port,
                url=self.bind.url,
                error_type=type(exc).__name__,
                duration_ms=int((self._monotonic() - started) * 1000),
            )
            if process is not None and process.pid:
                await self._stop_pid(process.pid, spawned_here=True)
            raise
        finally:
            self._release_claim()

    async def stop(self) -> GatewayStatus:
        state = load_state(self.directory)
        pid = state.pid if state is not None else None
        logger.info(
            "gateway_stop_requested",
            command="gateway stop",
            host=self.bind.host,
            port=self.bind.port,
            url=self.bind.url,
            pid=pid,
        )
        if self._lock_is_free():
            self._recover_stale_state()
            clear_shutdown(self.directory)
            status = await self._status(message="Gateway is not running")
            return status
        if pid is None or not self._process_exists(pid):
            return await self._status(
                message="Gateway lock is held, but the recorded process is gone. Refusing to stop an unknown process."
            )
        started = self._monotonic()
        await self._stop_pid(pid)
        logger.info(
            "gateway_stopped",
            command="gateway stop",
            host=self.bind.host,
            port=self.bind.port,
            pid=pid,
            url=self.bind.url,
            duration_ms=int((self._monotonic() - started) * 1000),
        )
        clear_state(self.directory)
        clear_shutdown(self.directory)
        return await self._status(message="Gateway stopped")

    async def restart(self) -> GatewayStatus:
        current = await self.status()
        if current.process_running and not current.managed:
            raise GatewayPortConflict(
                "A ByteBuddhi gateway is already listening, but this CLI did not start it. "
                "Refusing to stop that process."
            )
        if current.managed:
            await self.stop()
        return await self.start()

    async def _wait_until_ready(self, pid: int | None, *, managed: bool | None = None) -> GatewayStatus:
        deadline = self._monotonic() + self.start_timeout
        last = ProbeResult(False, False, False, False, detail="not_started")
        while True:
            if pid is not None and not self._process_exists(pid):
                raise GatewayStartFailed(
                    f"Gateway process {pid} exited before it was ready. See {log_path(self.directory)}."
                )
            last = await self._safe_probe()
            if last.ready and last.bytebuddhi:
                owns_lock = (not self._lock_is_free()) if managed is None else managed
                return self._status_from_probe(last, managed=owns_lock, message="ready")
            if self._monotonic() >= deadline:
                raise GatewayStartTimeout(
                    f"Gateway at {self.bind.url} was not ready within {self.start_timeout:g}s. "
                    f"See {log_path(self.directory)}."
                )
            await self._sleep(POLL_SECONDS)

    async def _stop_pid(self, pid: int, *, spawned_here: bool = False) -> None:
        if not spawned_here and self._lock_is_free():
            return
        if not self._process_exists(pid):
            return
        request_shutdown(self.directory)
        self._signal(pid)
        if await self._wait_until_stopped(pid, STOP_GRACE_SECONDS, spawned_here=spawned_here):
            return
        if not spawned_here and self._lock_is_free():
            return
        if not self._process_exists(pid):
            return
        self._terminate(pid)
        await self._wait_until_stopped(pid, STOP_GRACE_SECONDS, spawned_here=spawned_here)

    async def _wait_until_stopped(self, pid: int, timeout: float, *, spawned_here: bool = False) -> bool:
        deadline = self._monotonic() + timeout
        while self._monotonic() < deadline:
            if not self._process_exists(pid):
                return True
            if not spawned_here and self._lock_is_free():
                return True
            await self._sleep(POLL_SECONDS)
        if not self._process_exists(pid):
            return True
        return not spawned_here and self._lock_is_free()

    async def _safe_probe(self) -> ProbeResult:
        try:
            return await self._probe(self._target_url())
        except Exception as exc:
            return ProbeResult(False, False, False, False, detail=type(exc).__name__)

    def _target_url(self) -> str:
        state = load_state(self.directory)
        if state is not None and state.url:
            return state.url
        return self.bind.url

    async def _status(self, *, message: str) -> GatewayStatus:
        state = load_state(self.directory)
        managed = not self._lock_is_free()
        pid = state.pid if state is not None else None
        process_running = bool(managed and (pid is None or self._process_exists(pid or 0)))
        listen_host, listen_port = self._listen_target(state)
        probe = ProbeResult(False, False, False, False)
        if process_running or self._port_open(listen_host, listen_port):
            probe = await self._safe_probe()
            if probe.bytebuddhi and probe.live:
                process_running = True
        if not message:
            if probe.ready:
                message = "ready"
            elif process_running:
                message = "process running, not ready"
            else:
                message = "stopped"
        version = probe.version or (state.version if state is not None else None)
        started_at = state.started_at if state is not None else None
        return GatewayStatus(
            process_running=process_running,
            ready=bool(probe.ready and probe.bytebuddhi),
            live=bool(probe.live and probe.bytebuddhi),
            managed=managed,
            pid=pid if process_running else None,
            url=state.url if state is not None else self.bind.url,
            version=version,
            started_at=started_at,
            uptime_seconds=_uptime(started_at) if process_running else None,
            message=message,
        )

    def _status_from_probe(self, probe: ProbeResult, *, managed: bool, message: str) -> GatewayStatus:
        state = load_state(self.directory)
        pid = state.pid if state is not None else None
        running = bool(probe.bytebuddhi and (probe.live or probe.ready or managed))
        return GatewayStatus(
            process_running=running,
            ready=bool(probe.ready and probe.bytebuddhi),
            live=bool(probe.live and probe.bytebuddhi),
            managed=managed,
            pid=pid if running else None,
            url=state.url if state is not None else self.bind.url,
            version=probe.version or (state.version if state else None),
            started_at=state.started_at if state else None,
            uptime_seconds=_uptime(state.started_at) if state and running else None,
            message=message,
        )

    def _spawn(self) -> subprocess.Popen[bytes]:
        self.directory.mkdir(parents=True, exist_ok=True)
        command = gateway_server_command(self.bind.host, self.bind.port)
        target_log = log_path(self.directory)
        rotate_log_file(target_log)
        with open(target_log, "ab") as log_file:
            kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "shell": False,
                "env": os.environ.copy(),
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kwargs["start_new_session"] = True
            # Parent closes its copy when the with-block ends. The child keeps the inherited handle.
            return self._popen(command, **cast(Any, kwargs))

    def _write_state(self, pid: int) -> None:
        save_state(
            self.directory,
            GatewayState(
                pid=pid,
                bind_host=self.bind.host,
                port=self.bind.port,
                url=self.bind.url,
                started_at=utc_now(),
                version=__version__,
            ),
        )

    def _recover_stale_state(self) -> None:
        state = load_state(self.directory)
        if state is None or state.pid is None:
            return
        if self._process_exists(state.pid):
            return
        if not self._lock_is_free():
            return
        logger.warning(
            "gateway_stale_state_recovered",
            command="gateway status",
            host=self.bind.host,
            port=self.bind.port,
            pid=state.pid,
            url=state.url,
        )
        clear_state(self.directory)
        clear_shutdown(self.directory)

    def _lock_is_free(self) -> bool:
        lock = GatewayLock(lock_path(self.directory))
        if lock.try_acquire():
            lock.release()
            return True
        return False

    def _listen_target(self, state: GatewayState | None) -> tuple[str, int]:
        if state is not None:
            return state.bind_host, state.port
        return self.bind.host, self.bind.port

    def _pid(self) -> int | None:
        state = load_state(self.directory)
        return state.pid if state is not None else None

    def _try_claim(self) -> bool:
        path = claim_path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if path.exists() and self._claim_is_stale() and self._lock_is_free():
            logger.warning(
                "gateway_stale_state_recovered",
                command="gateway start",
                host=self.bind.host,
                port=self.bind.port,
                url=self.bind.url,
                detail="stale_claim",
            )
            path.unlink(missing_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, utc_now().encode("ascii"))
        finally:
            os.close(fd)
        return True

    def _claim_is_stale(self) -> bool:
        path = claim_path(self.directory)
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return True
        return age > self.start_timeout

    def _release_claim(self) -> None:
        claim_path(self.directory).unlink(missing_ok=True)


def _uptime(started_at: str | None) -> int | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - started).total_seconds()))


async def _asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)

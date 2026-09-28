"""Local gateway manager lifecycle without starting the real API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.interfaces.gateway.config import BindAddress
from app.interfaces.gateway.errors import GatewayPortConflict, GatewayStartTimeout
from app.interfaces.gateway.manager import GatewayManager
from app.interfaces.gateway.models import ProbeResult
from app.interfaces.gateway.process import GatewayLock, process_exists, terminate_process
from app.interfaces.gateway.state import GatewayState, load_state, lock_path, save_state, utc_now


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _bind() -> BindAddress:
    return BindAddress(host="127.0.0.1", port=8765, url="http://127.0.0.1:8765", exposed=False)


def _ready(_url: str) -> ProbeResult:
    return ProbeResult(True, True, True, True, version="0.1.3")


async def _ready_async(url: str) -> ProbeResult:
    return _ready(url)


def _manager(tmp_path: Path, **kwargs: object) -> GatewayManager:
    clock = kwargs.pop("clock", None)
    if not isinstance(clock, _Clock):
        clock = _Clock()
    return GatewayManager(
        _bind(),
        directory=tmp_path,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        start_timeout=30.0,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_start_waits_for_readiness_and_second_start_does_not_duplicate(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    holder: list[GatewayLock] = []

    def popen(command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        assert kwargs.get("shell") is False
        assert isinstance(command, list)
        assert command[1:3] == ["-m", "app.interfaces.gateway.server"]
        assert "creationflags" in kwargs or kwargs.get("start_new_session") is True
        lock = GatewayLock(lock_path(tmp_path))
        assert lock.try_acquire()
        holder.append(lock)
        calls.append(command)
        return _FakeProcess(43210)  # type: ignore[return-value]

    manager = _manager(
        tmp_path,
        popen=popen,
        process_exists_fn=lambda pid: pid == 43210,
        port_open_fn=lambda _host, _port: False,
        probe=_ready_async,
    )
    try:
        first = await manager.start()
        second = await manager.start()
    finally:
        if holder:
            holder[0].release()
    assert first.ready is True
    assert first.process_running is True
    assert first.pid == 43210
    assert second.pid == 43210
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_startup_timeout_stops_the_spawned_process(tmp_path: Path) -> None:
    clock = _Clock()
    alive = {"on": True}
    terminated: list[int] = []

    def popen(_command: list[str], **_kwargs: object) -> subprocess.Popen[bytes]:
        return _FakeProcess(51515)  # type: ignore[return-value]

    async def probe(_url: str) -> ProbeResult:
        return ProbeResult(False, False, False, False, detail="starting")

    manager = GatewayManager(
        _bind(),
        directory=tmp_path,
        popen=popen,  # type: ignore[arg-type]
        process_exists_fn=lambda _pid: alive["on"],
        port_open_fn=lambda _host, _port: False,
        probe=probe,
        terminate_fn=lambda pid: terminated.append(pid) or alive.update(on=False),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        start_timeout=0.4,
    )
    with pytest.raises(GatewayStartTimeout):
        await manager.start()
    assert terminated == [51515]


@pytest.mark.asyncio
async def test_stale_pid_is_recovered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_state(
        tmp_path,
        GatewayState(
            pid=999001,
            bind_host="127.0.0.1",
            port=8765,
            url="http://127.0.0.1:8765",
            started_at=utc_now(),
            version="0",
        ),
    )
    events: list[str] = []

    class _Logger:
        def warning(self, event: str, **_kwargs: object) -> None:
            events.append(str(event))

        def info(self, *_args: object, **_kwargs: object) -> None:
            return None

        def error(self, *_args: object, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr("app.interfaces.gateway.manager.logger", _Logger())
    holder: list[GatewayLock] = []

    def popen(_command: list[str], **_kwargs: object) -> subprocess.Popen[bytes]:
        lock = GatewayLock(lock_path(tmp_path))
        assert lock.try_acquire()
        holder.append(lock)
        return _FakeProcess(42)  # type: ignore[return-value]

    manager = _manager(
        tmp_path,
        popen=popen,
        process_exists_fn=lambda pid: pid == 42,
        port_open_fn=lambda _host, _port: False,
        probe=_ready_async,
    )
    try:
        status = await manager.start()
    finally:
        if holder:
            holder[0].release()
    assert status.pid == 42
    assert "gateway_stale_state_recovered" in events
    saved = load_state(tmp_path)
    assert saved is not None
    assert saved.pid == 42


@pytest.mark.asyncio
async def test_foreign_listener_is_not_killed_or_replaced(tmp_path: Path) -> None:
    async def probe(_url: str) -> ProbeResult:
        return ProbeResult(True, False, False, False, detail="other")

    def popen(*_args: object, **_kwargs: object) -> subprocess.Popen[bytes]:
        raise AssertionError("must not spawn")

    manager = _manager(
        tmp_path,
        popen=popen,
        process_exists_fn=lambda _pid: False,
        port_open_fn=lambda _host, _port: True,
        probe=probe,
    )
    with pytest.raises(GatewayPortConflict) as exc:
        await manager.start()
    assert "will not stop" in str(exc.value)


@pytest.mark.asyncio
async def test_stop_only_targets_the_recorded_process_and_status_reports_readiness(tmp_path: Path) -> None:
    lock = GatewayLock(lock_path(tmp_path))
    assert lock.try_acquire()
    save_state(
        tmp_path,
        GatewayState(
            pid=77,
            bind_host="127.0.0.1",
            port=8765,
            url="http://127.0.0.1:8765",
            started_at=utc_now(),
            version="0.1.3",
        ),
    )
    alive = {"on": True}

    def terminate(pid: int) -> None:
        assert pid == 77
        alive["on"] = False
        lock.release()

    manager = _manager(
        tmp_path,
        process_exists_fn=lambda pid: alive["on"] and pid == 77,
        port_open_fn=lambda _host, _port: alive["on"],
        probe=_ready_async,
        terminate_fn=terminate,
        signal_fn=lambda _pid: None,
    )
    current = await manager.status()
    assert current.process_running is True
    assert current.ready is True
    assert current.pid == 77
    assert current.version == "0.1.3"
    stopped = await manager.stop()
    assert stopped.process_running is False
    assert alive["on"] is False


def test_process_exists_and_terminate_are_cross_platform() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process_exists(proc.pid)
        terminate_process(proc.pid)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    assert process_exists(proc.pid) is False


def test_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "gateway.lock"
    first = GatewayLock(path)
    second = GatewayLock(path)
    assert first.try_acquire() is True
    assert second.try_acquire() is False
    first.release()
    assert second.try_acquire() is True
    second.release()


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode = None

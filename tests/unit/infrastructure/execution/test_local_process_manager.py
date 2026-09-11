"""Unit tests for LocalProcessManager, streaming, bounded buffering, and descendant cleanup."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

from app.application.ports.output.execution.process_manager import (
    ProcessEventType,
    ProcessStatus,
)
from app.infrastructure.execution.local_process_manager import LocalProcessManager


@pytest.fixture
def process_manager() -> LocalProcessManager:
    return LocalProcessManager()


@pytest.fixture
def default_env() -> dict[str, str]:
    return dict(os.environ)


@pytest.mark.asyncio
async def test_run_successful_command(
    process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]
):
    cmd = [sys.executable, "-c", "print('hello from process manager')"]
    result = await process_manager.run(command=cmd, cwd=tmp_path, env=default_env)

    assert result.exit_code == 0
    assert result.status == ProcessStatus.COMPLETED
    assert "hello from process manager" in result.stdout_preview
    assert result.stderr_preview == ""
    assert result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_run_failing_command(process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]):
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('fatal runtime failure\\n'); sys.exit(3)",
    ]
    result = await process_manager.run(command=cmd, cwd=tmp_path, env=default_env)

    assert result.exit_code == 3
    assert result.status == ProcessStatus.FAILED
    assert "fatal runtime failure" in result.stderr_preview


@pytest.mark.asyncio
async def test_process_timeout_enforcement(
    process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]
):
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    result = await process_manager.run(command=cmd, cwd=tmp_path, env=default_env, timeout=0.3)

    assert result.status == ProcessStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_process_cancellation(process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]):
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    handle = await process_manager.start(command=cmd, cwd=tmp_path, env=default_env)

    assert handle.status == ProcessStatus.RUNNING
    await asyncio.sleep(0.1)

    cancelled = await process_manager.cancel(handle.execution_id)
    assert cancelled

    result = await handle.wait()
    assert result.status == ProcessStatus.CANCELLED


@pytest.mark.asyncio
async def test_bounded_output_buffering(
    process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]
):
    # Produce ~50 KB of output, with buffer capped at 1 KB (1024 bytes)
    cmd = [sys.executable, "-c", "print('x' * 50000)"]
    result = await process_manager.run(
        command=cmd,
        cwd=tmp_path,
        env=default_env,
        max_buffer_bytes=1024,
    )

    assert result.exit_code == 0
    assert result.is_truncated
    assert result.stdout_bytes >= 50000
    assert len(result.stdout_preview.encode("utf-8")) <= 1024


@pytest.mark.asyncio
async def test_async_event_streaming(process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]):
    cmd = [sys.executable, "-c", "print('line 1'); print('line 2')"]
    handle = await process_manager.start(command=cmd, cwd=tmp_path, env=default_env)

    events = []
    async for event in handle.events():
        events.append(event)

    result = await handle.wait()
    assert result.exit_code == 0

    output_events = [e for e in events if e.event_type == ProcessEventType.PROCESS_OUTPUT]
    assert len(output_events) >= 1
    combined_data = "".join(e.data for e in output_events)
    assert "line 1" in combined_data
    assert "line 2" in combined_data

    terminal_events = [e for e in events if e.event_type == ProcessEventType.PROCESS_EXITED]
    assert len(terminal_events) == 1


@pytest.mark.asyncio
async def test_write_stdin(process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]):
    cmd = [sys.executable, "-c", "line = input(); print(f'REPLY:{line}')"]
    handle = await process_manager.start(command=cmd, cwd=tmp_path, env=default_env)

    await handle.write_stdin("sample_stdin_input\n")
    result = await handle.wait()

    assert result.exit_code == 0
    assert "REPLY:sample_stdin_input" in result.stdout_preview


@pytest.mark.asyncio
async def test_descendant_process_tree_cleanup(
    process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]
):
    """Test that cancelling a parent process also terminates its background children."""
    child_marker = tmp_path / "child_alive.txt"
    child_script = tmp_path / "child_runner.py"
    child_script.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "pid_file = Path(sys.argv[1])\n"
        "pid_file.write_text(str(os.getpid()))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    parent_script = tmp_path / "parent_runner.py"
    parent_script.write_text(
        f"import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, r'{child_script}', r'{child_marker}'])\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )

    cmd = [sys.executable, str(parent_script)]
    handle = await process_manager.start(command=cmd, cwd=tmp_path, env=default_env)

    # Wait until child has written its marker
    for _ in range(50):
        if child_marker.exists():
            break
        await asyncio.sleep(0.1)

    assert child_marker.exists()
    child_pid = int(child_marker.read_text().strip())

    # Cancel parent
    await handle.cancel()
    await handle.wait()

    # Give OS a brief moment to finish kill
    await asyncio.sleep(0.3)

    # Check if child_pid is dead
    def is_pid_alive(pid: int) -> bool:
        if sys.platform == "win32":
            try:
                # OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION
                import ctypes

                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if h == 0:
                    return False
                exit_code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
                kernel32.CloseHandle(h)
                STILL_ACTIVE = 259
                return exit_code.value == STILL_ACTIVE
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    assert not is_pid_alive(child_pid), f"Child process {child_pid} was not cleaned up!"


@pytest.mark.asyncio
async def test_event_queue_bounded_under_output_flood(
    process_manager: LocalProcessManager, tmp_path: Path, default_env: dict[str, str]
) -> None:
    """More output events than queue capacity must not prevent process termination."""
    cmd = [
        sys.executable,
        "-c",
        "import sys,time\n"
        "for i in range(40):\n"
        "    sys.stdout.write(f'line-{i}\\n')\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.02)\n",
    ]
    handle = await process_manager.start(
        command=cmd,
        cwd=tmp_path,
        env=default_env,
        max_event_queue=4,
    )
    await asyncio.sleep(1.0)
    result = await handle.wait()
    assert result.exit_code == 0
    assert result.status == ProcessStatus.COMPLETED
    assert handle._event_queue.maxsize == 4
    assert handle._events_dropped > 0 or result.is_truncated

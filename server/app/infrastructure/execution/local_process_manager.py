"""Local OS process manager with async streaming, bounded buffers, and process tree cleanup."""

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.application.ports.output.execution.process_manager import (
    ProcessEvent,
    ProcessEventType,
    ProcessExecution,
    ProcessHandle,
    ProcessManager,
    ProcessResult,
    ProcessStatus,
)
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class LocalProcessHandle(ProcessHandle):
    """Handle for a local OS subprocess with streaming events and lifecycle control."""

    def __init__(
        self,
        execution_id: str,
        proc: asyncio.subprocess.Process,
        command: list[str] | str,
        cwd: Path,
        max_buffer_bytes: int = 512 * 1024,
    ):
        self._execution_id = execution_id
        self._proc = proc
        self._command = command
        self._cwd = cwd
        self._max_buffer_bytes = max_buffer_bytes

        self._status = ProcessStatus.RUNNING
        self._started_at = datetime.now(UTC)
        self._finished_at: datetime | None = None
        self._exit_code: int | None = None

        self._event_queue: asyncio.Queue[ProcessEvent | None] = asyncio.Queue()

        self._stdout_chunks: list[str] = []
        self._stderr_chunks: list[str] = []
        self._stdout_bytes_total: int = 0
        self._stderr_bytes_total: int = 0
        self._stdout_bytes_buffered: int = 0
        self._stderr_bytes_buffered: int = 0
        self._is_truncated: bool = False

        self._start_time = time.monotonic()
        self._end_time: float | None = None

        # Background stream reading tasks
        self._stdout_task = asyncio.create_task(self._read_stream(self._proc.stdout, "stdout"))
        self._stderr_task = asyncio.create_task(self._read_stream(self._proc.stderr, "stderr"))
        # Automatic background monitor task ensures events() never deadlocks
        self._monitor_task = asyncio.create_task(self._monitor())

    @property
    def execution_id(self) -> str:
        return self._execution_id

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    @property
    def status(self) -> ProcessStatus:
        return self._status

    async def _read_stream(self, stream_reader: asyncio.StreamReader | None, stream_name: str) -> None:
        """Asynchronously read stream chunks without blocking the event loop."""
        if not stream_reader:
            return

        try:
            while not stream_reader.at_eof():
                chunk_bytes = await stream_reader.read(4096)
                if not chunk_bytes:
                    break

                text = chunk_bytes.decode("utf-8", errors="replace")
                chunk_len = len(chunk_bytes)

                # Track buffers and byte bounds
                if stream_name == "stdout":
                    self._stdout_bytes_total += chunk_len
                    if self._stdout_bytes_buffered + chunk_len <= self._max_buffer_bytes:
                        self._stdout_chunks.append(text)
                        self._stdout_bytes_buffered += chunk_len
                    else:
                        self._is_truncated = True
                else:
                    self._stderr_bytes_total += chunk_len
                    if self._stderr_bytes_buffered + chunk_len <= self._max_buffer_bytes:
                        self._stderr_chunks.append(text)
                        self._stderr_bytes_buffered += chunk_len
                    else:
                        self._is_truncated = True

                # Emit output event
                await self._event_queue.put(
                    ProcessEvent(
                        execution_id=self._execution_id,
                        event_type=ProcessEventType.PROCESS_OUTPUT,
                        stream=stream_name,
                        data=text,
                    )
                )

        except Exception as e:
            logger.error("Error reading process stream", stream=stream_name, error=str(e))
        finally:
            logger.debug("Process stream reader finished", stream=stream_name)

    async def _monitor(self) -> None:
        """Monitor process lifecycle automatically in background."""
        try:
            returncode = await self._proc.wait()
            self._exit_code = returncode
        except Exception as e:
            logger.error("Error waiting for process", execution_id=self._execution_id, error=str(e))
        finally:
            self._end_time = time.monotonic()
            self._finished_at = datetime.now(UTC)

            # Wait for stdout and stderr readers to finish draining
            await asyncio.gather(self._stdout_task, self._stderr_task, return_exceptions=True)

            if self._status == ProcessStatus.RUNNING:
                self._status = ProcessStatus.COMPLETED if self._exit_code == 0 else ProcessStatus.FAILED

            event_type = (
                ProcessEventType.PROCESS_EXITED
                if self._status == ProcessStatus.COMPLETED
                else (
                    ProcessEventType.PROCESS_CANCELLED
                    if self._status == ProcessStatus.CANCELLED
                    else ProcessEventType.PROCESS_FAILED
                )
            )

            await self._event_queue.put(
                ProcessEvent(
                    execution_id=self._execution_id,
                    event_type=event_type,
                    stream="system",
                    data=f"Process exited with code {self._exit_code}",
                )
            )
            # Sentinel to close any active events() iterator
            await self._event_queue.put(None)

    async def cancel(self) -> None:
        """Cancel process and terminate all child descendants."""
        if self._status != ProcessStatus.RUNNING:
            return

        self._status = ProcessStatus.CANCELLED
        self._terminate_process_tree()

        await self._event_queue.put(
            ProcessEvent(
                execution_id=self._execution_id,
                event_type=ProcessEventType.PROCESS_CANCELLED,
                stream="system",
                data="Process cancelled by user or runtime",
            )
        )

    def _terminate_process_tree(self) -> None:
        """Terminate the process and all descendant processes across Windows and POSIX."""
        pid = self._proc.pid
        if not pid:
            return

        logger.info("Terminating process tree", pid=pid, execution_id=self._execution_id)

        if sys.platform == "win32":
            try:
                # Use taskkill /F /T to forcefully terminate process and all child trees
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception as e:
                logger.warning("taskkill failed, falling back to proc.kill()", error=str(e))
                with contextlib.suppress(Exception):
                    self._proc.kill()
        else:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(0.05)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                with contextlib.suppress(Exception):
                    self._proc.kill()

    async def wait(self, timeout: float | None = None) -> ProcessResult:
        """Wait for the process to exit and return structured outcome."""
        if timeout is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._monitor_task), timeout=timeout)
            except TimeoutError:
                logger.warning("Process timed out", execution_id=self._execution_id, timeout=timeout)
                self._status = ProcessStatus.TIMED_OUT
                self._terminate_process_tree()
                await self._monitor_task
        else:
            await self._monitor_task

        duration = (self._end_time or time.monotonic()) - self._start_time
        return ProcessResult(
            execution_id=self._execution_id,
            exit_code=self._exit_code or 0,
            status=self._status,
            duration_seconds=round(duration, 3),
            stdout_preview="".join(self._stdout_chunks),
            stderr_preview="".join(self._stderr_chunks),
            stdout_bytes=self._stdout_bytes_total,
            stderr_bytes=self._stderr_bytes_total,
            is_truncated=self._is_truncated,
        )

    async def events(self) -> AsyncIterator[ProcessEvent]:
        """Stream output events asynchronously until process termination."""
        while True:
            event = await self._event_queue.get()
            if event is None:
                break
            yield event

    async def write_stdin(self, data: str | bytes) -> None:
        """Send data to standard input."""
        if not self._proc.stdin or self._proc.stdin.is_closing():
            return
        payload = data.encode("utf-8") if isinstance(data, str) else data
        self._proc.stdin.write(payload)
        await self._proc.stdin.drain()


class LocalProcessManager(ProcessManager):
    """Local OS process manager independent of HTTP, DB, or UI frameworks."""

    def __init__(self) -> None:
        self._executions: dict[str, ProcessExecution] = {}
        self._active_handles: dict[str, LocalProcessHandle] = {}

    async def start(
        self,
        command: list[str] | str,
        cwd: Path,
        env: dict[str, str],
        timeout: float | None = None,
        max_buffer_bytes: int = 512 * 1024,
    ) -> ProcessHandle:
        """Spawn a process and return an active ProcessHandle."""
        execution_id = f"exec_{uuid4().hex[:12]}"
        cwd_path = Path(cwd).resolve()

        kwargs: dict[str, Any] = {
            "cwd": str(cwd_path),
            "env": env,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "stdin": asyncio.subprocess.PIPE,
        }

        # On POSIX, use start_new_session to create a process group for clean tree termination
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        if isinstance(command, list):
            proc = await asyncio.create_subprocess_exec(*command, **kwargs)
        else:
            proc = await asyncio.create_subprocess_shell(command, **kwargs)

        handle = LocalProcessHandle(
            execution_id=execution_id,
            proc=proc,
            command=command,
            cwd=cwd_path,
            max_buffer_bytes=max_buffer_bytes,
        )

        exec_record = ProcessExecution(
            execution_id=execution_id,
            pid=proc.pid,
            command=command,
            cwd=cwd_path,
            status=ProcessStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

        self._executions[execution_id] = exec_record
        self._active_handles[execution_id] = handle

        logger.info(
            "Process spawned",
            execution_id=execution_id,
            pid=proc.pid,
            command=command,
            cwd=str(cwd_path),
        )

        return handle

    async def run(
        self,
        command: list[str] | str,
        cwd: Path,
        env: dict[str, str],
        timeout: float | None = None,
        max_buffer_bytes: int = 512 * 1024,
    ) -> ProcessResult:
        """Run process to completion with optional timeout."""
        handle = await self.start(
            command=command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            max_buffer_bytes=max_buffer_bytes,
        )

        result = await handle.wait(timeout=timeout)

        # Update record
        if handle.execution_id in self._executions:
            record = self._executions[handle.execution_id]
            record.status = result.status
            record.exit_code = result.exit_code
            record.finished_at = datetime.now(UTC)

        self._active_handles.pop(handle.execution_id, None)
        return result

    async def cancel(self, execution_id: str) -> bool:
        """Cancel a running process."""
        handle = self._active_handles.get(execution_id)
        if not handle:
            return False
        await handle.cancel()
        return True

    def get_execution(self, execution_id: str) -> ProcessExecution | None:
        """Retrieve execution record by execution ID."""
        return self._executions.get(execution_id)

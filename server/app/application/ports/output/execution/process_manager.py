"""Process manager contracts and execution models for local OS process control."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class ProcessStatus(StrEnum):
    """Execution status of an OS process."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ProcessEventType(StrEnum):
    """Lifecycle and output event types emitted during process execution."""

    PROCESS_STARTED = "process_started"
    PROCESS_OUTPUT = "process_output"
    PROCESS_EXITED = "process_exited"
    PROCESS_FAILED = "process_failed"
    PROCESS_CANCELLED = "process_cancelled"
    PROCESS_TIMEOUT = "process_timeout"


@dataclass
class ProcessEvent:
    """An event emitted during process lifecycle or output streaming."""

    execution_id: str
    event_type: ProcessEventType
    stream: str  # "stdout", "stderr", or "system"
    data: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ProcessExecution:
    """Complete tracking record for an OS process execution."""

    execution_id: str
    pid: int | None
    command: list[str] | str
    cwd: Path
    status: ProcessStatus = ProcessStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    stdout_ref: str | None = None
    stderr_ref: str | None = None


@dataclass
class ProcessResult:
    """Structured execution outcome for a finished or terminated process."""

    execution_id: str
    exit_code: int
    status: ProcessStatus
    duration_seconds: float
    stdout_preview: str
    stderr_preview: str
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    is_truncated: bool = False


@runtime_checkable
class ProcessHandle(Protocol):
    """Active process handle supporting async event streaming and lifecycle control."""

    @property
    def execution_id(self) -> str: ...

    @property
    def pid(self) -> int | None: ...

    @property
    def status(self) -> ProcessStatus: ...

    async def cancel(self) -> None:
        """Cancel and terminate the process and its descendants."""
        ...

    async def wait(self, timeout: float | None = None) -> ProcessResult:
        """Wait for process termination and return structured ProcessResult."""
        ...

    def events(self) -> AsyncIterator[ProcessEvent]:
        """Stream output and lifecycle events asynchronously."""
        ...

    async def write_stdin(self, data: str | bytes) -> None:
        """Write input data to process standard input stream."""
        ...


@runtime_checkable
class ProcessManager(Protocol):
    """Protocol for managing OS process execution without coupling to web or DB layers."""

    async def start(
        self,
        command: list[str] | str,
        cwd: Path,
        env: dict[str, str],
        timeout: float | None = None,
        max_buffer_bytes: int = 512 * 1024,
    ) -> ProcessHandle:
        """Start an OS process and return an active ProcessHandle."""
        ...

    async def run(
        self,
        command: list[str] | str,
        cwd: Path,
        env: dict[str, str],
        timeout: float | None = None,
        max_buffer_bytes: int = 512 * 1024,
    ) -> ProcessResult:
        """Run an OS process to completion and return structured ProcessResult."""
        ...

    async def cancel(self, execution_id: str) -> bool:
        """Cancel a running process by its execution ID."""
        ...

    def get_execution(self, execution_id: str) -> ProcessExecution | None:
        """Retrieve tracking record for an execution ID."""
        ...

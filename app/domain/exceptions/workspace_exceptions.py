"""Workspace and local execution domain exceptions."""

from typing import Any

from app.domain.exceptions.base import DomainException


class WorkspaceError(DomainException):
    """Base exception for workspace-related domain errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class WorkspaceBoundaryError(WorkspaceError):
    """Raised when an operation attempts to escape the configured workspace boundary."""

    def __init__(self, message: str, path: str | None = None, root_path: str | None = None):
        details = {}
        if path:
            details["path"] = str(path)
        if root_path:
            details["root_path"] = str(root_path)
        super().__init__(message, details=details)


class FileNotFoundWorkspaceError(WorkspaceError):
    """Raised when a required file is not found within the workspace."""

    def __init__(self, path: str):
        super().__init__(f"File not found: {path}", details={"path": str(path)})


class FileAlreadyExistsWorkspaceError(WorkspaceError):
    """Raised when attempting to write to a file that already exists without overwrite enabled."""

    def __init__(self, path: str):
        super().__init__(f"File already exists: {path}", details={"path": str(path)})


class ExecutionTimeoutError(WorkspaceError):
    """Raised when a command or process execution exceeds the configured timeout."""

    def __init__(self, timeout_seconds: float, execution_id: str | None = None):
        details: dict[str, Any] = {"timeout_seconds": timeout_seconds}
        if execution_id:
            details["execution_id"] = execution_id
        super().__init__(f"Execution timed out after {timeout_seconds} seconds", details=details)


class ExecutionCancelledError(WorkspaceError):
    """Raised when a command or process execution is explicitly cancelled."""

    def __init__(self, execution_id: str | None = None):
        details: dict[str, Any] = {}
        if execution_id:
            details["execution_id"] = execution_id
        super().__init__("Execution was cancelled", details=details)


class CommandBlockedError(WorkspaceError):
    """Raised when a command is rejected by the command safety policy."""

    def __init__(self, command: str, reason: str):
        super().__init__(f"Command blocked by policy: {reason}", details={"command": command, "reason": reason})

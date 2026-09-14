"""CLI error type mapping onto stable exit codes."""

import asyncio

from app.application.agent.errors import AgentError, AgentErrorCode
from app.domain.exceptions.base import DomainException
from app.domain.exceptions.project_exceptions import (
    ProjectNotFoundException,
    ProjectOwnershipException,
)
from app.domain.exceptions.workspace_exceptions import (
    ExecutionCancelledError,
    ExecutionTimeoutError,
    WorkspaceBoundaryError,
    WorkspaceError,
)
from app.interfaces.cli.exit_codes import ExitCode

_SECRET_MARKERS = ("password", "secret", "api_key", "apikey", "token", "jwt", "authorization")


class CliError(Exception):
    """User-facing CLI failure with a stable exit code."""

    def __init__(self, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.message = message


def sanitize_message(message: str) -> str:
    """Drop likely secret material from error text."""
    lowered = message.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return "An internal error occurred. Re-run with --debug for diagnostics if it is safe to do so."
    return message


def map_exception(exc: BaseException) -> CliError:
    if isinstance(exc, CliError):
        return exc
    if isinstance(exc, ProjectOwnershipException):
        return CliError(sanitize_message(str(exc)), ExitCode.AUTH_FAILURE)
    if isinstance(exc, ProjectNotFoundException):
        return CliError(sanitize_message(str(exc)), ExitCode.WORKSPACE_FAILURE)
    if isinstance(exc, WorkspaceBoundaryError):
        return CliError(sanitize_message(str(exc)), ExitCode.WORKSPACE_FAILURE)
    if isinstance(exc, ExecutionTimeoutError):
        return CliError("Execution timed out", ExitCode.TIMEOUT_CANCELLED)
    if isinstance(exc, ExecutionCancelledError):
        return CliError("Execution cancelled", ExitCode.TIMEOUT_CANCELLED)
    if isinstance(exc, WorkspaceError):
        return CliError(sanitize_message(str(exc)), ExitCode.WORKSPACE_FAILURE)
    if isinstance(exc, AgentError):
        if exc.code in {AgentErrorCode.TIMEOUT, AgentErrorCode.CANCELLED}:
            return CliError(sanitize_message(exc.message), ExitCode.TIMEOUT_CANCELLED)
        if exc.code == AgentErrorCode.VALIDATION_ERROR:
            return CliError(sanitize_message(exc.message), ExitCode.USAGE_ERROR)
        return CliError(sanitize_message(exc.message), ExitCode.EXECUTION_FAILURE)
    if isinstance(exc, TimeoutError):
        return CliError("Execution timed out", ExitCode.TIMEOUT_CANCELLED)
    if isinstance(exc, asyncio.CancelledError):
        return CliError("Execution cancelled", ExitCode.TIMEOUT_CANCELLED)
    if isinstance(exc, DomainException):
        return CliError(sanitize_message(str(exc)), ExitCode.EXECUTION_FAILURE)
    if isinstance(exc, RuntimeError) and "Production" in str(exc):
        return CliError(sanitize_message(str(exc)), ExitCode.CONFIG_FAILURE)
    return CliError(sanitize_message(str(exc)), ExitCode.EXECUTION_FAILURE)

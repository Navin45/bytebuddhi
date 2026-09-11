"""Stable CLI process exit codes."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    EXECUTION_FAILURE = 1
    USAGE_ERROR = 2
    AUTH_FAILURE = 3
    WORKSPACE_FAILURE = 4
    TIMEOUT_CANCELLED = 5
    CONFIG_FAILURE = 6

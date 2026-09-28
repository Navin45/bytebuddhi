"""Persistent run states. Transitions are explicit."""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED})

_ALLOWED: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.CANCELLING, RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.CANCELLING: frozenset({RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.INTERRUPTED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class InvalidRunTransition(Exception):
    """Raised when a run status change is not in the state machine."""

    def __init__(self, current: RunStatus, target: RunStatus) -> None:
        super().__init__(f"Cannot move a run from {current.value} to {target.value}")
        self.current = current
        self.target = target


def assert_transition(current: RunStatus, target: RunStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidRunTransition(current, target)


def is_terminal(status: RunStatus) -> bool:
    return status in TERMINAL_STATUSES

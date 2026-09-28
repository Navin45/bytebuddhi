"""Public run errors. Messages are safe to return to clients."""

from __future__ import annotations

import re

_SECRET_RE = re.compile(r"(?i)(bearer\s+\S+|sk-[A-Za-z0-9]|eyJ[A-Za-z0-9_\-]{8,}\.)")


class RunError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class RunNotFound(RunError):
    def __init__(self) -> None:
        super().__init__("RUN_NOT_FOUND", "Run not found", http_status=404)


class RunAlreadyCompleted(RunError):
    def __init__(self) -> None:
        super().__init__("RUN_ALREADY_COMPLETED", "The run has already finished", http_status=409)


class IdempotencyConflict(RunError):
    def __init__(self) -> None:
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            "This idempotency key was already used for a different request",
            http_status=409,
        )


class LeaseLost(Exception):
    """This worker no longer owns the run. It must not write further state."""


class InvalidEventCursor(RunError):
    def __init__(self) -> None:
        super().__init__("EVENT_CURSOR_INVALID", "after_sequence must be an integer >= 0", http_status=422)


def public_failure_message(exc: BaseException) -> str:
    """One safe line for a client-visible failure. Tracebacks stay in logs."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else "Run execution failed"
    if _SECRET_RE.search(text) or "traceback" in text.lower():
        return "Run execution failed"
    return text[:300] or "Run execution failed"

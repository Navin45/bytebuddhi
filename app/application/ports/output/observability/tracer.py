"""Application ports for tracing and span lifecycle management."""

from collections.abc import Generator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class SpanStatus(StrEnum):
    """Normalized span status codes matching OpenTelemetry semantics."""

    OK = "OK"
    ERROR = "ERROR"
    UNSET = "UNSET"


@runtime_checkable
class SpanContext(Protocol):
    """Context identifying a span across process/task boundaries."""

    @property
    def trace_id(self) -> str: ...

    @property
    def span_id(self) -> str: ...

    @property
    def is_valid(self) -> bool: ...


@runtime_checkable
class Span(Protocol):
    """An individual operation span within a trace."""

    @property
    def span_id(self) -> str: ...

    @property
    def trace_id(self) -> str: ...

    @property
    def is_recording(self) -> bool: ...

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a single attribute on the span."""
        ...

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        """Set multiple attributes on the span."""
        ...

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        """Set the execution status of the span."""
        ...

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add an event to the span."""
        ...

    def get_span_context(self) -> SpanContext:
        """Get the SpanContext for this span."""
        ...

    def record_exception(self, exception: BaseException, attributes: dict[str, Any] | None = None) -> None:
        """Record an exception on the span."""
        ...

    def end(self) -> None:
        """End the span."""
        ...

    def __enter__(self) -> "Span": ...

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    """Application port for creating spans and propagating trace context."""

    def start_span(
        self,
        name: str,
        parent: Span | SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """Start a new span, optionally as a child of parent."""
        ...

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        parent: Span | SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Generator[Span]:
        """Context manager that starts a span and activates it as the current span."""
        ...

    def get_current_span(self) -> Span | None:
        """Retrieve the active span in the current context, if any."""
        ...

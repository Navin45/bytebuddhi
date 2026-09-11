"""No-Op observability implementations for disabled telemetry or fallback mode."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from app.application.ports.output.observability.meter import Counter, Histogram, UpDownCounter
from app.application.ports.output.observability.tracer import Span, SpanContext, SpanStatus


class NoOpSpanContext:
    """Null-object span context."""

    @property
    def trace_id(self) -> str:
        return "0" * 32

    @property
    def span_id(self) -> str:
        return "0" * 16

    @property
    def is_valid(self) -> bool:
        return False


class NoOpSpan:
    """Null-object span that safely absorbs all operations without side effects."""

    def __init__(self, trace_id: str | None = None, span_id: str | None = None) -> None:
        self._trace_id = trace_id or ("0" * 32)
        self._span_id = span_id or ("0" * 16)

    @property
    def span_id(self) -> str:
        return self._span_id

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def is_recording(self) -> bool:
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        pass

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def get_span_context(self) -> SpanContext:
        return NoOpSpanContext()

    def record_exception(self, exception: BaseException, attributes: dict[str, Any] | None = None) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class NoOpTracer:
    """Null-object tracer that returns NoOpSpans."""

    def start_span(
        self,
        name: str,
        parent: Span | SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        parent_trace_id = getattr(parent, "trace_id", None) if parent else None
        return NoOpSpan(trace_id=parent_trace_id)

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        parent: Span | SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Generator[Span]:
        span = self.start_span(name, parent, attributes)
        yield span

    def get_current_span(self) -> Span | None:
        return None


class NoOpCounter:
    """Null-object counter."""

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        pass


class NoOpUpDownCounter:
    """Null-object up-down counter."""

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        pass


class NoOpHistogram:
    """Null-object histogram."""

    def record(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        pass


class NoOpMeter:
    """Null-object meter returning no-op instruments."""

    def create_counter(self, name: str, unit: str = "", description: str = "") -> Counter:
        return NoOpCounter()

    def create_up_down_counter(self, name: str, unit: str = "", description: str = "") -> UpDownCounter:
        return NoOpUpDownCounter()

    def create_histogram(self, name: str, unit: str = "", description: str = "") -> Histogram:
        return NoOpHistogram()

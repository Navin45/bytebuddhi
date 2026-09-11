"""OpenTelemetry implementation of application tracing ports with zero-crash guarantee."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import StatusCode

from app.application.ports.output.observability.tracer import (
    Span,
    SpanContext,
    SpanStatus,
)
from app.domain.models.observability import DataBoundingPolicy, RedactionPolicy
from app.infrastructure.config.logger import get_logger
from app.infrastructure.observability.noop import NoOpSpan

logger = get_logger(__name__)


class OpenTelemetrySpanContext:
    """Wraps an OpenTelemetry SpanContext with formatted string IDs."""

    def __init__(self, otel_context: trace.SpanContext) -> None:
        self._otel_context = otel_context

    @property
    def trace_id(self) -> str:
        tid = self._otel_context.trace_id
        return format(tid, "032x") if isinstance(tid, int) else str(tid)

    @property
    def span_id(self) -> str:
        sid = self._otel_context.span_id
        return format(sid, "016x") if isinstance(sid, int) else str(sid)

    @property
    def is_valid(self) -> bool:
        return self._otel_context.is_valid

    @property
    def raw_context(self) -> trace.SpanContext:
        return self._otel_context


class OpenTelemetrySpan:
    """Wraps an OpenTelemetry Span with automatic redaction, bounding, and error containment."""

    def __init__(self, otel_span: trace.Span) -> None:
        self._otel_span = otel_span

    @property
    def span_id(self) -> str:
        try:
            sid = self._otel_span.get_span_context().span_id
            return format(sid, "016x") if isinstance(sid, int) else str(sid)
        except Exception:
            return "0" * 16

    @property
    def trace_id(self) -> str:
        try:
            tid = self._otel_span.get_span_context().trace_id
            return format(tid, "032x") if isinstance(tid, int) else str(tid)
        except Exception:
            return "0" * 32

    @property
    def is_recording(self) -> bool:
        try:
            return self._otel_span.is_recording()
        except Exception:
            return False

    def set_attribute(self, key: str, value: Any) -> None:
        """Set an attribute with centralized redaction and bounding."""
        try:
            if RedactionPolicy.is_sensitive_key(key):
                self._otel_span.set_attribute(key, RedactionPolicy.REDACTED_TEXT)
                return

            bounded_val = DataBoundingPolicy.bound_attribute_value(value)
            if isinstance(bounded_val, str):
                bounded_val = RedactionPolicy.sanitize_string(bounded_val)

            self._otel_span.set_attribute(key, bounded_val)
        except Exception as e:
            logger.debug("Failed to set telemetry attribute safely", key=key, error=str(e))

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        """Set multiple attributes with centralized redaction and bounding."""
        try:
            sanitized = RedactionPolicy.sanitize_attributes(attributes)
            for k, v in sanitized.items():
                bounded = DataBoundingPolicy.bound_attribute_value(v)
                self._otel_span.set_attribute(k, bounded)
        except Exception as e:
            logger.debug("Failed to set telemetry attributes safely", error=str(e))

    def set_status(self, status: SpanStatus, description: str | None = None) -> None:
        """Set span execution status safely."""
        try:
            otel_status = StatusCode.UNSET
            if status == SpanStatus.OK:
                otel_status = StatusCode.OK
            elif status == SpanStatus.ERROR:
                otel_status = StatusCode.ERROR

            sanitized_desc = RedactionPolicy.sanitize_exception_message(description) if description else None
            self._otel_span.set_status(otel_status, description=sanitized_desc)
        except Exception as e:
            logger.debug("Failed to set telemetry status safely", error=str(e))

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add an event to the span with sanitized attributes."""
        try:
            safe_attrs = RedactionPolicy.sanitize_attributes(attributes or {})
            self._otel_span.add_event(name, safe_attrs)
        except Exception as e:
            logger.debug("Failed to add telemetry event safely", name=name, error=str(e))

    def get_span_context(self) -> SpanContext:
        """Get the SpanContext for this span."""
        try:
            return OpenTelemetrySpanContext(self._otel_span.get_span_context())
        except Exception:
            return OpenTelemetrySpanContext(trace.INVALID_SPAN_CONTEXT)

    def record_exception(self, exception: BaseException, attributes: dict[str, Any] | None = None) -> None:
        """Record an exception with sanitized error message."""
        try:
            safe_attrs = RedactionPolicy.sanitize_attributes(attributes or {})
            self._otel_span.record_exception(exception, attributes=safe_attrs)
            self.set_status(SpanStatus.ERROR, description=str(exception))
        except Exception as e:
            logger.debug("Failed to record telemetry exception safely", error=str(e))

    def end(self) -> None:
        """End the span."""
        try:
            self._otel_span.end()
        except Exception as e:
            logger.debug("Failed to end telemetry span safely", error=str(e))

    def __enter__(self) -> "OpenTelemetrySpan":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_val is not None:
                self.record_exception(exc_val)
            self.end()
        except Exception as e:
            logger.debug("Error in span exit handler", error=str(e))


class OpenTelemetryTracer:
    """Wraps OpenTelemetry Tracer with parent-child linkage and telemetry failure isolation."""

    def __init__(self, otel_tracer: trace.Tracer) -> None:
        self._otel_tracer = otel_tracer

    def _extract_parent_context(self, parent: Span | SpanContext | None) -> Any:
        """Resolve parent context from custom application span/context or active context."""
        if parent is None:
            return None

        if isinstance(parent, OpenTelemetrySpan):
            return trace.set_span_in_context(parent._otel_span)

        if isinstance(parent, OpenTelemetrySpanContext):
            return trace.set_span_in_context(trace.NonRecordingSpan(parent.raw_context))

        return None

    def start_span(
        self,
        name: str,
        parent: Span | SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """Start a new span, linking to parent if provided, falling back to NoOp on failure."""
        try:
            sanitized_attrs = RedactionPolicy.sanitize_attributes(attributes or {})
            bounded_attrs = {k: DataBoundingPolicy.bound_attribute_value(v) for k, v in sanitized_attrs.items()}

            parent_ctx = self._extract_parent_context(parent)
            otel_span = self._otel_tracer.start_span(
                name=name,
                context=parent_ctx,
                attributes=bounded_attrs,
            )
            return OpenTelemetrySpan(otel_span)
        except Exception as e:
            logger.warning("Failed to start OpenTelemetry span, degrading to NoOp", name=name, error=str(e))
            parent_trace_id = getattr(parent, "trace_id", None) if parent else None
            return NoOpSpan(trace_id=parent_trace_id)

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        parent: Span | SpanContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Generator[Span]:
        """Context manager creating and activating a span as current in OpenTelemetry context."""
        span = self.start_span(name, parent=parent, attributes=attributes)
        if isinstance(span, OpenTelemetrySpan):
            with trace.use_span(span._otel_span, end_on_exit=True, record_exception=True):
                yield span
        else:
            with span:
                yield span

    def get_current_span(self) -> Span | None:
        """Get the current active span, if recording."""
        try:
            current = trace.get_current_span()
            if current and current.is_recording():
                return OpenTelemetrySpan(current)
            return None
        except Exception:
            return None

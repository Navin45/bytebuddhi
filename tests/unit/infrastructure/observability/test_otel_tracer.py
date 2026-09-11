"""Unit tests for OpenTelemetryTracer and NoOpTracer implementations."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.application.ports.output.observability.tracer import SpanStatus
from app.infrastructure.observability.noop import NoOpTracer
from app.infrastructure.observability.otel_tracer import OpenTelemetryTracer


@pytest.fixture
def memory_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def otel_tracer(memory_exporter: InMemorySpanExporter) -> OpenTelemetryTracer:
    provider = TracerProvider()
    processor = SimpleSpanProcessor(memory_exporter)
    provider.add_span_processor(processor)
    raw_tracer = provider.get_tracer("test-tracer")
    return OpenTelemetryTracer(raw_tracer)


def test_noop_tracer_lifecycle() -> None:
    """Ensure NoOpTracer performs all operations gracefully with zero side effects."""
    tracer = NoOpTracer()
    with tracer.start_as_current_span("noop.test", attributes={"key": "val"}) as span:
        span.set_attribute("extra", "value")
        span.set_attributes({"another": 123})
        span.add_event("an_event", {"meta": "data"})
        span.set_status(SpanStatus.OK)
        span.record_exception(ValueError("sample error"))
        ctx = span.get_span_context()
        assert ctx.trace_id == "0" * 32
        assert ctx.span_id == "0" * 16


def test_otel_tracer_basic_span(otel_tracer: OpenTelemetryTracer, memory_exporter: InMemorySpanExporter) -> None:
    """Verify OpenTelemetryTracer starts, attributes, events, and ends spans correctly."""
    with otel_tracer.start_as_current_span(
        "test.operation",
        attributes={"bytebuddhi.test": "value1"},
    ) as span:
        span.set_attribute("extra.key", "value2")
        span.add_event("checkpoint_reached", {"step": 1})
        span.set_status(SpanStatus.OK)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    finished = spans[0]
    assert finished.name == "test.operation"
    assert finished.attributes is not None
    assert finished.attributes["bytebuddhi.test"] == "value1"
    assert finished.attributes["extra.key"] == "value2"
    assert len(finished.events) == 1
    assert finished.events[0].name == "checkpoint_reached"
    assert finished.status.is_ok


def test_otel_tracer_nested_spans(otel_tracer: OpenTelemetryTracer, memory_exporter: InMemorySpanExporter) -> None:
    """Verify nested spans correctly link parent and child span IDs."""
    with otel_tracer.start_as_current_span("parent.span") as parent:
        parent_ctx = parent.get_span_context()
        with otel_tracer.start_as_current_span("child.span") as child:
            child_ctx = child.get_span_context()
            assert child_ctx.trace_id == parent_ctx.trace_id
            assert child_ctx.span_id != parent_ctx.span_id

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2
    # Inner finished first
    child_span = next(s for s in spans if s.name == "child.span")
    parent_span = next(s for s in spans if s.name == "parent.span")

    assert child_span.parent is not None
    assert child_span.parent.span_id == parent_span.context.span_id
    assert child_span.context.trace_id == parent_span.context.trace_id


def test_otel_tracer_exception_recording(
    otel_tracer: OpenTelemetryTracer, memory_exporter: InMemorySpanExporter
) -> None:
    """Verify exceptions are recorded on spans and set status to ERROR."""
    with (
        pytest.raises(RuntimeError, match="Failure occurred"),
        otel_tracer.start_as_current_span("failing.span") as span,
    ):
        try:
            raise RuntimeError("Failure occurred")
        except RuntimeError as exc:
            span.record_exception(exc)
            span.set_status(SpanStatus.ERROR, str(exc))
            raise

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    finished = spans[0]
    assert not finished.status.is_ok
    assert any(e.name == "exception" for e in finished.events)

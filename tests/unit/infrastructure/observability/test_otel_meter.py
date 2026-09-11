"""Unit tests for OpenTelemetryMeter and NoOpMeter implementations."""

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.infrastructure.observability.noop import NoOpMeter
from app.infrastructure.observability.otel_meter import OpenTelemetryMeter


@pytest.fixture
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def otel_meter(metric_reader: InMemoryMetricReader) -> OpenTelemetryMeter:
    provider = MeterProvider(metric_readers=[metric_reader])
    raw_meter = provider.get_meter("test-meter")
    return OpenTelemetryMeter(raw_meter)


def test_noop_meter_lifecycle() -> None:
    """Ensure NoOpMeter implements all meter methods safely without errors."""
    meter = NoOpMeter()
    counter = meter.create_counter("test.counter", unit="1", description="test counter")
    counter.add(5, {"label": "value"})

    updown = meter.create_up_down_counter("test.updown", unit="1", description="test updown")
    updown.add(2, {"label": "value"})
    updown.add(-1, {"label": "value"})

    histogram = meter.create_histogram("test.histogram", unit="ms", description="test histogram")
    histogram.record(123.4, {"label": "value"})


def test_otel_meter_counter(otel_meter: OpenTelemetryMeter, metric_reader: InMemoryMetricReader) -> None:
    """Verify OpenTelemetry counter accumulates correctly."""
    counter = otel_meter.create_counter("bytebuddhi.test_runs_total", unit="1", description="Runs")
    counter.add(1, {"agent_role": "coder"})
    counter.add(2, {"agent_role": "coder"})

    metric_data = metric_reader.get_metrics_data()
    assert metric_data is not None
    resource_metrics = metric_data.resource_metrics
    assert len(resource_metrics) > 0
    scope_metrics = resource_metrics[0].scope_metrics
    assert len(scope_metrics) > 0
    metrics = scope_metrics[0].metrics
    matched = [m for m in metrics if m.name == "bytebuddhi.test_runs_total"]
    assert len(matched) == 1
    data_points = list(matched[0].data.data_points)
    assert len(data_points) == 1
    assert data_points[0].value == 3
    assert data_points[0].attributes["agent_role"] == "coder"


def test_otel_meter_histogram(otel_meter: OpenTelemetryMeter, metric_reader: InMemoryMetricReader) -> None:
    """Verify OpenTelemetry histogram records values."""
    hist = otel_meter.create_histogram("bytebuddhi.test_duration", unit="s", description="Duration")
    hist.record(0.125, {"tool_name": "read_file"})
    hist.record(0.250, {"tool_name": "read_file"})

    metric_data = metric_reader.get_metrics_data()
    assert metric_data is not None
    metrics = metric_data.resource_metrics[0].scope_metrics[0].metrics
    matched = [m for m in metrics if m.name == "bytebuddhi.test_duration"]
    assert len(matched) == 1
    data_points = list(matched[0].data.data_points)
    assert len(data_points) == 1
    assert data_points[0].count == 2
    assert data_points[0].sum == pytest.approx(0.375)

"""OpenTelemetry implementation of application metrics ports with bounded cardinality guarantee."""

from typing import Any

from opentelemetry import metrics

from app.application.ports.output.observability.meter import (
    Counter,
    Histogram,
    UpDownCounter,
)
from app.domain.models.observability import DataBoundingPolicy
from app.infrastructure.config.logger import get_logger
from app.infrastructure.observability.noop import (
    NoOpCounter,
    NoOpHistogram,
    NoOpUpDownCounter,
)

logger = get_logger(__name__)


class OpenTelemetryCounter:
    """Wraps an OpenTelemetry Counter instrument with cardinality enforcement."""

    def __init__(self, otel_counter: metrics.Counter) -> None:
        self._otel_counter = otel_counter

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        try:
            bounded_attrs = DataBoundingPolicy.sanitize_and_bound_metric_attributes(attributes or {})
            self._otel_counter.add(amount, attributes=bounded_attrs)
        except Exception as e:
            logger.debug("Failed to record metric counter", error=str(e))


class OpenTelemetryUpDownCounter:
    """Wraps an OpenTelemetry UpDownCounter instrument with cardinality enforcement."""

    def __init__(self, otel_counter: metrics.UpDownCounter) -> None:
        self._otel_counter = otel_counter

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        try:
            bounded_attrs = DataBoundingPolicy.sanitize_and_bound_metric_attributes(attributes or {})
            self._otel_counter.add(amount, attributes=bounded_attrs)
        except Exception as e:
            logger.debug("Failed to record metric up_down_counter", error=str(e))


class OpenTelemetryHistogram:
    """Wraps an OpenTelemetry Histogram instrument with cardinality enforcement."""

    def __init__(self, otel_histogram: metrics.Histogram) -> None:
        self._otel_histogram = otel_histogram

    def record(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        try:
            bounded_attrs = DataBoundingPolicy.sanitize_and_bound_metric_attributes(attributes or {})
            self._otel_histogram.record(amount, attributes=bounded_attrs)
        except Exception as e:
            logger.debug("Failed to record metric histogram", error=str(e))


class OpenTelemetryMeter:
    """Wraps an OpenTelemetry Meter with error containment and fallback."""

    def __init__(self, otel_meter: metrics.Meter) -> None:
        self._otel_meter = otel_meter

    def create_counter(self, name: str, unit: str = "", description: str = "") -> Counter:
        try:
            counter = self._otel_meter.create_counter(name=name, unit=unit, description=description)
            return OpenTelemetryCounter(counter)
        except Exception as e:
            logger.warning("Failed to create OpenTelemetry counter, using NoOp", name=name, error=str(e))
            return NoOpCounter()

    def create_up_down_counter(self, name: str, unit: str = "", description: str = "") -> UpDownCounter:
        try:
            counter = self._otel_meter.create_up_down_counter(name=name, unit=unit, description=description)
            return OpenTelemetryUpDownCounter(counter)
        except Exception as e:
            logger.warning("Failed to create OpenTelemetry up_down_counter, using NoOp", name=name, error=str(e))
            return NoOpUpDownCounter()

    def create_histogram(self, name: str, unit: str = "", description: str = "") -> Histogram:
        try:
            histogram = self._otel_meter.create_histogram(name=name, unit=unit, description=description)
            return OpenTelemetryHistogram(histogram)
        except Exception as e:
            logger.warning("Failed to create OpenTelemetry histogram, using NoOp", name=name, error=str(e))
            return NoOpHistogram()

"""OpenTelemetry SDK provider initialization and configuration."""

from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    Sampler,
    TraceIdRatioBased,
)

from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.tracer import Tracer
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import Settings
from app.infrastructure.observability.noop import NoOpMeter, NoOpTracer
from app.infrastructure.observability.otel_meter import OpenTelemetryMeter
from app.infrastructure.observability.otel_tracer import OpenTelemetryTracer

logger = get_logger(__name__)


def setup_telemetry(settings: Settings) -> tuple[Tracer, Meter]:
    """Initialize OpenTelemetry tracer and meter providers with defensive fallback to NoOp."""
    if not settings.telemetry_enabled:
        logger.info("Telemetry disabled via configuration, using NoOp implementation")
        return NoOpTracer(), NoOpMeter()

    try:
        # 1. Define telemetry resource attributes
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "environment": settings.app_env,
                "service.version": "0.1.0",
            }
        )

        # 2. Configure Trace Sampling
        sampler: Sampler
        if settings.otel_sampling_rate <= 0.0:
            sampler = ALWAYS_OFF
        elif settings.otel_sampling_rate >= 1.0:
            sampler = ALWAYS_ON
        else:
            sampler = TraceIdRatioBased(settings.otel_sampling_rate)

        # 3. Configure TracerProvider and Exporters
        tracer_provider = TracerProvider(resource=resource, sampler=sampler)

        if settings.otel_tracing_enabled:
            exporter_type = settings.otel_exporter.lower()
            if exporter_type == "console":
                # Local development console exporter
                tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            elif exporter_type == "otlp":
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

                    tracer_provider.add_span_processor(
                        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_otlp_endpoint))
                    )
                except Exception as otlp_err:
                    logger.warning(
                        "Failed to initialize OTLP trace exporter, falling back to console",
                        error=str(otlp_err),
                    )
                    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        # 4. Configure MeterProvider and Metric Exporters
        metric_readers: list[Any] = []
        if settings.otel_metrics_enabled:
            exporter_type = settings.otel_exporter.lower()
            if exporter_type == "console":
                metric_readers.append(
                    PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60000)
                )
            elif exporter_type == "otlp":
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

                    metric_readers.append(
                        PeriodicExportingMetricReader(
                            OTLPMetricExporter(endpoint=settings.otel_otlp_endpoint),
                            export_interval_millis=15000,
                        )
                    )
                except Exception as otlp_m_err:
                    logger.warning(
                        "Failed to initialize OTLP metric exporter",
                        error=str(otlp_m_err),
                    )

        meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)

        raw_tracer = tracer_provider.get_tracer(settings.otel_service_name)
        raw_meter = meter_provider.get_meter(settings.otel_service_name)

        logger.info(
            "Telemetry initialized successfully",
            service_name=settings.otel_service_name,
            exporter=settings.otel_exporter,
            sampling_rate=settings.otel_sampling_rate,
        )

        return OpenTelemetryTracer(raw_tracer), OpenTelemetryMeter(raw_meter)

    except Exception as e:
        logger.error("Failed to initialize OpenTelemetry SDK, degrading to NoOp safely", error=str(e))
        return NoOpTracer(), NoOpMeter()


_global_tracer: Tracer | None = None
_global_meter: Meter | None = None


def get_tracer() -> Tracer:
    """Get or initialize global tracer."""
    global _global_tracer, _global_meter
    if _global_tracer is None:
        from app.infrastructure.config.settings import settings

        _global_tracer, _global_meter = setup_telemetry(settings)
    return _global_tracer


def get_meter() -> Meter:
    """Get or initialize global meter."""
    global _global_tracer, _global_meter
    if _global_meter is None:
        from app.infrastructure.config.settings import settings

        _global_tracer, _global_meter = setup_telemetry(settings)
    return _global_meter

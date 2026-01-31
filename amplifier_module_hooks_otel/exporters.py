"""Exporter configuration for OTel hook module.

Supports multiple exporter backends:
- console: Print spans to stdout (development)
- otlp-http: Send to OTLP collector via HTTP (production)
- otlp-grpc: Send to OTLP collector via gRPC (production)
- file: Write spans to JSONL file (debugging)

Based on robotdad/amplifier-module-hooks-otel exporters.py.
"""

import json
import os
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan

from .config import OTelConfig


class FileSpanExporter(SpanExporter):
    """Simple file-based span exporter for debugging.

    Writes spans as JSONL (one JSON object per line) for easy inspection.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        # Ensure file exists
        open(file_path, "a").close()

    def export(self, spans: list["ReadableSpan"]) -> SpanExportResult:
        """Export spans to file."""
        try:
            with open(self.file_path, "a") as f:
                for span in spans:
                    record = {
                        "name": span.name,
                        "trace_id": format(span.context.trace_id, "032x"),
                        "span_id": format(span.context.span_id, "016x"),
                        "parent_span_id": (
                            format(span.parent.span_id, "016x") if span.parent else None
                        ),
                        "start_time": span.start_time,
                        "end_time": span.end_time,
                        "attributes": dict(span.attributes) if span.attributes else {},
                        "status": span.status.status_code.name,
                        "events": [
                            {
                                "name": e.name,
                                "timestamp": e.timestamp,
                                "attributes": dict(e.attributes) if e.attributes else {},
                            }
                            for e in span.events
                        ],
                    }
                    f.write(json.dumps(record) + "\n")
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        """Shutdown the exporter."""
        pass


def _build_resource(config: OTelConfig) -> Resource:
    """Build OTel resource with service and user attributes."""
    return Resource.create(
        {
            "service.name": config.service_name,
            "service.version": config.service_version,
            "amplifier.user.id": config.user_id or os.environ.get("USER", "unknown"),
            "amplifier.team.id": config.team_id,
        }
    )


def setup_tracing(config: OTelConfig) -> None:
    """Configure OpenTelemetry tracing with the specified exporter.

    Args:
        config: OTelConfig with exporter settings.

    Raises:
        ValueError: If exporter type is unknown.
    """
    resource = _build_resource(config)
    provider = TracerProvider(resource=resource)

    # Configure exporter based on config
    if config.exporter == "console":
        # Console exporter - immediate output, good for development
        exporter = ConsoleSpanExporter()
        processor = SimpleSpanProcessor(exporter)

    elif config.exporter == "otlp-http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=f"{config.endpoint}/v1/traces",
            headers=config.headers or None,
        )
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=config.max_batch_size,
            schedule_delay_millis=config.batch_delay_ms,
        )

    elif config.exporter == "otlp-grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=config.endpoint,
            headers=config.headers or None,
        )
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=config.max_batch_size,
            schedule_delay_millis=config.batch_delay_ms,
        )

    elif config.exporter == "file":
        exporter = FileSpanExporter(config.file_path)
        processor = SimpleSpanProcessor(exporter)

    else:
        raise ValueError(f"Unknown exporter type: {config.exporter}")

    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    if config.debug:
        print(f"[otel] Configured {config.exporter} trace exporter")
        if config.exporter in ("otlp-http", "otlp-grpc"):
            print(f"[otel] Endpoint: {config.endpoint}")
        elif config.exporter == "file":
            print(f"[otel] File: {config.file_path}")


def setup_metrics(config: OTelConfig) -> None:
    """Configure OpenTelemetry metrics with the specified exporter.

    Args:
        config: OTelConfig with exporter settings.
    """
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )

    resource = _build_resource(config)

    if config.exporter == "console":
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(),
            export_interval_millis=config.batch_delay_ms,
        )
    elif config.exporter in ("otlp-http", "otlp-grpc"):
        if config.exporter == "otlp-http":
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

            exporter = OTLPMetricExporter(
                endpoint=f"{config.endpoint}/v1/metrics",
                headers=config.headers or None,
            )
        else:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )

            exporter = OTLPMetricExporter(
                endpoint=config.endpoint,
                headers=config.headers or None,
            )

        reader = PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=config.batch_delay_ms,
        )
    else:
        # File exporter doesn't support metrics yet, use console
        reader = PeriodicExportingMetricReader(
            ConsoleMetricExporter(),
            export_interval_millis=config.batch_delay_ms,
        )

    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    if config.debug:
        print(f"[otel] Configured {config.exporter} metrics exporter")

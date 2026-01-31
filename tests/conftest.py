"""Pytest configuration and fixtures for OTel hook tests."""

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Global providers - set once at module import
_tracer_provider = None
_meter_provider = None
_span_exporter = None
_metric_reader = None


def _setup_global_providers():
    """Set up global OTel providers once."""
    global _tracer_provider, _meter_provider, _span_exporter, _metric_reader

    if _tracer_provider is None:
        _span_exporter = InMemorySpanExporter()
        _tracer_provider = TracerProvider()
        _tracer_provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
        trace.set_tracer_provider(_tracer_provider)

        _metric_reader = InMemoryMetricReader()
        _meter_provider = MeterProvider(metric_readers=[_metric_reader])
        metrics.set_meter_provider(_meter_provider)


# Set up providers at import time
_setup_global_providers()


@pytest.fixture
def span_exporter():
    """Get the global span exporter and clear it before each test."""
    assert _span_exporter is not None
    _span_exporter.clear()
    return _span_exporter


@pytest.fixture
def metric_reader():
    """Get the global metric reader."""
    return _metric_reader


@pytest.fixture
def tracer():
    """Get a tracer from the global provider."""
    return trace.get_tracer("test-tracer")


@pytest.fixture
def meter():
    """Get a meter from the global provider."""
    return metrics.get_meter("test-meter")

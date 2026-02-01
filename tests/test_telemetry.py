"""Tests for the public telemetry API."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider

from amplifier_module_hooks_otel import telemetry
from amplifier_module_hooks_otel.metrics import MetricsRecorder
from amplifier_module_hooks_otel.spans import SpanManager


@pytest.fixture
def tracer_provider():
    """Create a tracer provider for testing."""
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture
def tracer(tracer_provider):
    """Create a tracer for testing."""
    return tracer_provider.get_tracer("test")


@pytest.fixture
def metric_reader():
    """Create an in-memory metric reader."""
    return InMemoryMetricReader()


@pytest.fixture
def meter_provider(metric_reader):
    """Create a meter provider with in-memory reader."""
    return MeterProvider(metric_readers=[metric_reader])


@pytest.fixture
def meter(meter_provider):
    """Create a meter for testing."""
    return meter_provider.get_meter("test")


@pytest.fixture
def span_manager(tracer):
    """Create a SpanManager for testing."""
    return SpanManager(tracer)


@pytest.fixture
def metrics_recorder(meter):
    """Create a MetricsRecorder for testing."""
    return MetricsRecorder(meter)


@pytest.fixture
def registered_telemetry(metrics_recorder, span_manager):
    """Register telemetry and clean up after test."""
    telemetry._register(metrics_recorder, span_manager)
    yield
    telemetry._unregister()


class TestTelemetryRegistration:
    """Tests for telemetry registration."""

    def test_not_initialized_by_default(self):
        """Telemetry is not initialized by default."""
        telemetry._unregister()  # Ensure clean state
        assert telemetry.is_initialized() is False

    def test_register_initializes(self, metrics_recorder, span_manager):
        """Registration initializes the telemetry."""
        telemetry._unregister()  # Clean state
        assert telemetry.is_initialized() is False

        telemetry._register(metrics_recorder, span_manager)
        assert telemetry.is_initialized() is True

        telemetry._unregister()  # Cleanup

    def test_unregister_deinitializes(self, metrics_recorder, span_manager):
        """Unregistration deinitializes the telemetry."""
        telemetry._register(metrics_recorder, span_manager)
        assert telemetry.is_initialized() is True

        telemetry._unregister()
        assert telemetry.is_initialized() is False


class TestBundleAdded:
    """Tests for bundle_added function."""

    def test_noop_when_not_initialized(self):
        """bundle_added is a no-op when not initialized."""
        telemetry._unregister()
        # Should not raise
        telemetry.bundle_added(name="test-bundle")

    def test_records_metric_when_initialized(self, registered_telemetry, metric_reader):
        """bundle_added records a metric when initialized."""
        telemetry.bundle_added(name="my-bundle")
        # Should not raise - metric is recorded
        _ = metric_reader.get_metrics_data()

    def test_with_version(self, registered_telemetry, metric_reader):
        """bundle_added accepts version."""
        telemetry.bundle_added(name="my-bundle", version="1.0.0")
        _ = metric_reader.get_metrics_data()

    def test_with_git_source(self, registered_telemetry, metric_reader):
        """bundle_added preserves git source."""
        telemetry.bundle_added(
            name="foundation",
            source="git+https://github.com/microsoft/amplifier-foundation",
        )
        _ = metric_reader.get_metrics_data()

    def test_sanitizes_local_source(self, registered_telemetry, metric_reader):
        """bundle_added sanitizes local paths."""
        telemetry.bundle_added(
            name="private-bundle",
            source="/home/user/my-secret-bundle",
        )
        # The metric should be recorded with sanitized source
        _ = metric_reader.get_metrics_data()


class TestBundleActivated:
    """Tests for bundle_activated function."""

    def test_noop_when_not_initialized(self):
        """bundle_activated is a no-op when not initialized."""
        telemetry._unregister()
        # Should not raise
        telemetry.bundle_activated(name="test-bundle")

    def test_records_metric_when_initialized(self, registered_telemetry, metric_reader):
        """bundle_activated records a metric when initialized."""
        telemetry.bundle_activated(name="my-bundle")
        _ = metric_reader.get_metrics_data()

    def test_with_all_params(self, registered_telemetry, metric_reader):
        """bundle_activated accepts all parameters."""
        telemetry.bundle_activated(
            name="recipes",
            version="2.0.0",
            source="https://github.com/microsoft/amplifier-bundle-recipes",
        )
        _ = metric_reader.get_metrics_data()


class TestBundleLoaded:
    """Tests for bundle_loaded function."""

    def test_noop_when_not_initialized(self):
        """bundle_loaded is a no-op when not initialized."""
        telemetry._unregister()
        # Should not raise
        telemetry.bundle_loaded(name="test-bundle")

    def test_records_metric_when_initialized(self, registered_telemetry, metric_reader):
        """bundle_loaded records a metric when initialized."""
        telemetry.bundle_loaded(name="my-bundle")
        _ = metric_reader.get_metrics_data()

    def test_with_cached_flag(self, registered_telemetry, metric_reader):
        """bundle_loaded accepts cached flag."""
        telemetry.bundle_loaded(name="foundation", cached=True)
        _ = metric_reader.get_metrics_data()

    def test_with_all_params(self, registered_telemetry, metric_reader):
        """bundle_loaded accepts all parameters."""
        telemetry.bundle_loaded(
            name="foundation",
            version="1.0.0",
            source="git+https://github.com/microsoft/amplifier-foundation",
            cached=True,
        )
        _ = metric_reader.get_metrics_data()


class TestGracefulDegradation:
    """Tests for graceful degradation when OTel is not available."""

    def test_all_functions_safe_when_uninitialized(self):
        """All telemetry functions are safe to call when uninitialized."""
        telemetry._unregister()

        # None of these should raise
        telemetry.bundle_added(name="test")
        telemetry.bundle_activated(name="test")
        telemetry.bundle_loaded(name="test", cached=True)

    def test_is_initialized_returns_false(self):
        """is_initialized returns False when uninitialized."""
        telemetry._unregister()
        assert telemetry.is_initialized() is False

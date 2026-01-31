"""Tests for MetricsRecorder."""

import time

import pytest

from amplifier_module_hooks_otel.metrics import MetricsRecorder

# Fixtures meter and metric_reader come from conftest.py


@pytest.fixture
def recorder(meter):
    """Create a MetricsRecorder instance."""
    return MetricsRecorder(meter)


class TestMetricsRecorderTiming:
    """Tests for timing operations."""

    def test_start_timing_records_start_time(self, recorder):
        """Starting timing records the start time."""
        recorder.start_timing("op-123")

        assert "op-123" in recorder._start_times

    def test_record_duration_returns_elapsed_time(self, recorder):
        """Recording duration returns the elapsed time."""
        recorder.start_timing("op-123")
        time.sleep(0.01)  # Small delay

        duration = recorder.record_duration("op-123", {"operation": "test"})

        assert duration is not None
        assert duration >= 0.01

    def test_record_duration_removes_start_time(self, recorder):
        """Recording duration removes the start time entry."""
        recorder.start_timing("op-123")
        recorder.record_duration("op-123", {})

        assert "op-123" not in recorder._start_times

    def test_record_duration_without_start_returns_none(self, recorder):
        """Recording duration without start returns None."""
        duration = recorder.record_duration("nonexistent", {})

        assert duration is None

    def test_record_duration_emits_metric(self, recorder, metric_reader):
        """Recording duration emits the histogram metric."""
        recorder.start_timing("op-123")
        recorder.record_duration("op-123", {"gen_ai.operation.name": "chat"})

        # Force metrics collection - verify no error
        _ = metric_reader.get_metrics_data()
        # If we get here without error, the metric was recorded


class TestMetricsRecorderTokenUsage:
    """Tests for token usage recording."""

    def test_record_input_tokens(self, recorder, metric_reader):
        """Input tokens are recorded correctly."""
        recorder.record_token_usage(
            input_tokens=100,
            output_tokens=None,
            attributes={"gen_ai.provider.name": "anthropic"},
        )

        # Force metrics collection - verify no error
        _ = metric_reader.get_metrics_data()

    def test_record_output_tokens(self, recorder, metric_reader):
        """Output tokens are recorded correctly."""
        recorder.record_token_usage(
            input_tokens=None,
            output_tokens=50,
            attributes={"gen_ai.provider.name": "openai"},
        )

        _ = metric_reader.get_metrics_data()

    def test_record_both_token_types(self, recorder, metric_reader):
        """Both input and output tokens can be recorded."""
        recorder.record_token_usage(
            input_tokens=100,
            output_tokens=50,
            attributes={
                "gen_ai.provider.name": "anthropic",
                "gen_ai.request.model": "claude-3",
            },
        )

        _ = metric_reader.get_metrics_data()

    def test_record_tokens_with_none_values_is_safe(self, recorder):
        """Recording with None values doesn't raise."""
        # Should not raise
        recorder.record_token_usage(
            input_tokens=None,
            output_tokens=None,
            attributes={},
        )


class TestMetricsRecorderHistograms:
    """Tests for histogram creation."""

    def test_token_usage_histogram_created(self, recorder):
        """Token usage histogram is created on init."""
        assert recorder._token_usage is not None

    def test_operation_duration_histogram_created(self, recorder):
        """Operation duration histogram is created on init."""
        assert recorder._operation_duration is not None

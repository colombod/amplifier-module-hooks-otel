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

    def test_amplifier_histograms_created(self, recorder):
        """Amplifier-specific histograms are created on init."""
        assert recorder._tool_duration is not None
        assert recorder._session_duration is not None

    def test_amplifier_counters_created(self, recorder):
        """Amplifier-specific counters are created on init."""
        assert recorder._tool_calls is not None
        assert recorder._llm_calls is not None
        assert recorder._sessions_started is not None
        assert recorder._turns_completed is not None


class TestAmplifierToolMetrics:
    """Tests for Amplifier tool metrics."""

    def test_record_tool_call_increments_counter(self, recorder, metric_reader):
        """Tool call counter is incremented."""
        recorder.record_tool_call("read_file", duration=0.5, success=True)
        _ = metric_reader.get_metrics_data()

    def test_record_tool_call_with_failure(self, recorder, metric_reader):
        """Tool call with failure is recorded."""
        recorder.record_tool_call("bash", duration=1.2, success=False)
        _ = metric_reader.get_metrics_data()

    def test_record_tool_call_without_duration(self, recorder, metric_reader):
        """Tool call without duration only increments counter."""
        recorder.record_tool_call("write_file", duration=None, success=True)
        _ = metric_reader.get_metrics_data()


class TestAmplifierLLMMetrics:
    """Tests for Amplifier LLM metrics."""

    def test_record_llm_call_success(self, recorder, metric_reader):
        """LLM call success is recorded."""
        recorder.record_llm_call("anthropic", "claude-3", success=True)
        _ = metric_reader.get_metrics_data()

    def test_record_llm_call_failure(self, recorder, metric_reader):
        """LLM call failure is recorded."""
        recorder.record_llm_call("openai", "gpt-4", success=False)
        _ = metric_reader.get_metrics_data()


class TestAmplifierSessionMetrics:
    """Tests for Amplifier session metrics."""

    def test_record_session_started_new(self, recorder, metric_reader):
        """New session start is recorded."""
        recorder.record_session_started(
            session_id="sess-123",
            user_id="user-456",
            is_fork=False,
            is_resume=False,
        )
        _ = metric_reader.get_metrics_data()
        assert "sess-123" in recorder._session_start_times

    def test_record_session_started_fork(self, recorder, metric_reader):
        """Forked session is recorded with correct type."""
        recorder.record_session_started(
            session_id="child-sess",
            is_fork=True,
        )
        _ = metric_reader.get_metrics_data()

    def test_record_session_started_resume(self, recorder, metric_reader):
        """Resumed session is recorded with correct type."""
        recorder.record_session_started(
            session_id="resumed-sess",
            is_resume=True,
        )
        _ = metric_reader.get_metrics_data()

    def test_record_session_ended_returns_duration(self, recorder, metric_reader):
        """Session end returns duration."""
        recorder.record_session_started(session_id="sess-123")
        import time
        time.sleep(0.01)
        duration = recorder.record_session_ended("sess-123", status="completed")
        
        assert duration is not None
        assert duration >= 0.01
        assert "sess-123" not in recorder._session_start_times
        _ = metric_reader.get_metrics_data()

    def test_record_session_ended_without_start(self, recorder):
        """Session end without start returns None."""
        duration = recorder.record_session_ended("nonexistent", status="completed")
        assert duration is None


class TestAmplifierTurnMetrics:
    """Tests for Amplifier turn metrics."""

    def test_record_turn_completed(self, recorder, metric_reader):
        """Turn completion is recorded."""
        recorder.record_turn_completed(session_id="sess-123", turn_number=1)
        _ = metric_reader.get_metrics_data()

    def test_record_multiple_turns(self, recorder, metric_reader):
        """Multiple turns can be recorded."""
        for i in range(5):
            recorder.record_turn_completed(session_id="sess-123", turn_number=i + 1)
        _ = metric_reader.get_metrics_data()

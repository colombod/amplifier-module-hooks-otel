"""Tests for SpanManager."""

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from amplifier_module_hooks_otel.spans import SpanManager

# Fixtures tracer and span_exporter come from conftest.py


@pytest.fixture
def span_manager(tracer):
    """Create a SpanManager instance."""
    return SpanManager(tracer)


class TestSpanManagerSessionSpans:
    """Tests for session span lifecycle."""

    def test_start_session_span_creates_span(self, span_manager, span_exporter):
        """Starting a session creates a root span."""
        span = span_manager.start_session_span(
            "session-123", {"amplifier.session.id": "session-123"}
        )

        assert span is not None
        assert "session-123" in span_manager._session_spans

    def test_end_session_span_closes_span(self, span_manager, span_exporter):
        """Ending a session closes and removes the span."""
        span_manager.start_session_span("session-123", {})
        span_manager.end_session_span("session-123")

        assert "session-123" not in span_manager._session_spans

        # Verify span was exported
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "amplifier.session"

    def test_end_session_span_with_turn_cleans_up_turn(self, span_manager, span_exporter):
        """Ending session also cleans up any active turn span."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_turn_span("session-123")
        span_manager.end_session_span("session-123")

        assert "session-123" not in span_manager._session_spans
        assert "session-123" not in span_manager._turn_spans

    def test_end_nonexistent_session_is_safe(self, span_manager):
        """Ending a non-existent session doesn't raise."""
        span_manager.end_session_span("nonexistent")  # Should not raise


class TestSpanManagerTurnSpans:
    """Tests for turn span lifecycle."""

    def test_start_turn_span_requires_session(self, span_manager):
        """Turn span requires an active session."""
        result = span_manager.start_turn_span("nonexistent-session")
        assert result is None

    def test_start_turn_span_creates_child_span(self, span_manager, span_exporter):
        """Turn span is created as child of session."""
        span_manager.start_session_span("session-123", {})
        turn_span = span_manager.start_turn_span("session-123")

        assert turn_span is not None
        assert "session-123" in span_manager._turn_spans

    def test_start_turn_span_increments_counter(self, span_manager):
        """Each turn increments the turn counter."""
        span_manager.start_session_span("session-123", {})

        span_manager.start_turn_span("session-123")
        assert span_manager._turn_counters["session-123"] == 1

        span_manager.start_turn_span("session-123")
        assert span_manager._turn_counters["session-123"] == 2

    def test_start_turn_span_ends_previous_turn(self, span_manager, span_exporter):
        """Starting a new turn ends the previous turn span."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_turn_span("session-123")
        span_manager.start_turn_span("session-123")

        # End everything to export spans
        span_manager.end_session_span("session-123")

        spans = span_exporter.get_finished_spans()
        turn_spans = [s for s in spans if s.name == "amplifier.turn"]
        assert len(turn_spans) == 2

    def test_end_turn_span_closes_span(self, span_manager, span_exporter):
        """Ending a turn closes the span."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_turn_span("session-123")
        span_manager.end_turn_span("session-123")

        assert "session-123" not in span_manager._turn_spans


class TestSpanManagerChildSpans:
    """Tests for child spans (LLM, tool calls)."""

    def test_start_child_span_with_turn_parent(self, span_manager, span_exporter):
        """Child span is created under turn span when available."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_turn_span("session-123")

        child = span_manager.start_child_span(
            "session-123",
            "chat gpt-4",
            SpanKind.CLIENT,
            {"gen_ai.operation.name": "chat"},
            correlation_key="llm:123",
        )

        assert child is not None
        assert "llm:123" in span_manager._active_spans

    def test_start_child_span_with_session_fallback(self, span_manager, span_exporter):
        """Child span falls back to session when no turn."""
        span_manager.start_session_span("session-123", {})

        child = span_manager.start_child_span(
            "session-123",
            "execute_tool bash",
            SpanKind.INTERNAL,
            {"amplifier.tool.name": "bash"},
        )

        assert child is not None

    def test_start_child_span_requires_parent(self, span_manager):
        """Child span returns None without parent."""
        result = span_manager.start_child_span("nonexistent", "test", SpanKind.INTERNAL, {})
        assert result is None

    def test_end_child_span_by_correlation_key(self, span_manager, span_exporter):
        """Child span can be ended by correlation key."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_child_span(
            "session-123",
            "test-span",
            SpanKind.INTERNAL,
            {},
            correlation_key="test-key",
        )

        span_manager.end_child_span("test-key", StatusCode.OK)

        assert "test-key" not in span_manager._active_spans

    def test_end_child_span_with_error(self, span_manager, span_exporter):
        """Child span can be ended with error status."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_child_span(
            "session-123",
            "test-span",
            SpanKind.INTERNAL,
            {},
            correlation_key="error-key",
        )

        span_manager.end_child_span("error-key", StatusCode.ERROR, "Test error message")

        # End session to export
        span_manager.end_session_span("session-123")

        spans = span_exporter.get_finished_spans()
        child_span = [s for s in spans if s.name == "test-span"][0]
        assert child_span.status.status_code == StatusCode.ERROR

    def test_get_active_span(self, span_manager):
        """Active span can be retrieved by correlation key."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_child_span(
            "session-123",
            "test-span",
            SpanKind.INTERNAL,
            {},
            correlation_key="active-key",
        )

        span = span_manager.get_active_span("active-key")
        assert span is not None

        nonexistent = span_manager.get_active_span("nonexistent")
        assert nonexistent is None


class TestSpanManagerTraceId:
    """Tests for trace ID generation."""

    def test_session_to_trace_id_is_deterministic(self):
        """Same session ID produces same trace ID."""
        trace_id_1 = SpanManager.session_to_trace_id("session-123")
        trace_id_2 = SpanManager.session_to_trace_id("session-123")

        assert trace_id_1 == trace_id_2

    def test_different_sessions_produce_different_trace_ids(self):
        """Different session IDs produce different trace IDs."""
        trace_id_1 = SpanManager.session_to_trace_id("session-123")
        trace_id_2 = SpanManager.session_to_trace_id("session-456")

        assert trace_id_1 != trace_id_2

    def test_trace_id_is_128_bit_int(self):
        """Trace ID is a valid 128-bit integer."""
        trace_id = SpanManager.session_to_trace_id("session-123")

        assert isinstance(trace_id, int)
        assert trace_id >= 0
        assert trace_id < 2**128

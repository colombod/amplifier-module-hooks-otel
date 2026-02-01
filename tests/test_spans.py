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
        assert "session-123" in span_manager._sessions
        assert span_manager.get_session_span("session-123") is not None

    def test_end_session_span_closes_span(self, span_manager, span_exporter):
        """Ending a session closes and removes the span."""
        span_manager.start_session_span("session-123", {})
        span_manager.end_session_span("session-123")

        assert "session-123" not in span_manager._sessions
        assert span_manager.get_session_span("session-123") is None

        # Verify span was exported
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "amplifier.session"

    def test_end_session_span_with_turn_cleans_up_turn(self, span_manager, span_exporter):
        """Ending session also cleans up any active turn span."""
        span_manager.start_session_span("session-123", {})
        span_manager.start_turn_span("session-123")
        span_manager.end_session_span("session-123")

        assert "session-123" not in span_manager._sessions

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
        ctx = span_manager._sessions.get("session-123")
        assert ctx is not None
        assert ctx.current_turn is not None

    def test_start_turn_span_increments_counter(self, span_manager):
        """Each turn increments the turn counter."""
        span_manager.start_session_span("session-123", {})

        span_manager.start_turn_span("session-123")
        ctx = span_manager._sessions.get("session-123")
        assert ctx.turn_count == 1

        span_manager.start_turn_span("session-123")
        assert ctx.turn_count == 2

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

        ctx = span_manager._sessions.get("session-123")
        assert ctx is not None
        assert ctx.current_turn is None


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


class TestSpanManagerTraceContextPropagation:
    """Tests for W3C Trace Context propagation across parent-child sessions."""

    def test_child_session_inherits_parent_trace_id(self, span_manager, span_exporter):
        """Child session span should have the same trace_id as parent."""
        # Start parent session
        parent_span = span_manager.start_session_span(
            "parent-session", {"amplifier.session.id": "parent-session"}
        )
        parent_trace_id = parent_span.get_span_context().trace_id

        # Start child session with parent linkage
        child_span = span_manager.start_session_span(
            "child-session",
            {"amplifier.session.id": "child-session"},
            parent_session_id="parent-session",
        )
        child_trace_id = child_span.get_span_context().trace_id

        # Same trace_id = same distributed trace
        assert child_trace_id == parent_trace_id

    def test_child_session_has_parent_as_parent_span(self, span_manager, span_exporter):
        """Child session's parent_id should be the parent session's span_id."""
        # Start parent session
        parent_span = span_manager.start_session_span(
            "parent-session", {"amplifier.session.id": "parent-session"}
        )
        parent_span_id = parent_span.get_span_context().span_id

        # Start child session with parent linkage
        # We need to create the span but verify via exported spans
        span_manager.start_session_span(
            "child-session",
            {"amplifier.session.id": "child-session"},
            parent_session_id="parent-session",
        )

        # End both to export
        span_manager.end_session_span("child-session")
        span_manager.end_session_span("parent-session")

        # Verify parent-child relationship in exported spans
        spans = span_exporter.get_finished_spans()
        child_exported = next(s for s in spans if "child-session" in str(s.attributes))

        # Child's parent should be the parent session's span
        assert child_exported.parent is not None
        assert child_exported.parent.span_id == parent_span_id

    def test_child_without_valid_parent_starts_new_trace(self, span_manager, span_exporter):
        """Child session with non-existent parent starts a new trace (graceful fallback)."""
        # Start child with non-existent parent
        child_span = span_manager.start_session_span(
            "orphan-session",
            {"amplifier.session.id": "orphan-session"},
            parent_session_id="nonexistent-parent",
        )

        # Should still create a span (new trace)
        assert child_span is not None
        assert child_span.get_span_context().is_valid

        # End and export
        span_manager.end_session_span("orphan-session")
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        # No parent = root span
        assert spans[0].parent is None

    def test_get_span_context_returns_valid_context(self, span_manager):
        """get_span_context should return valid SpanContext for active sessions."""
        span_manager.start_session_span("session-123", {})

        context = span_manager.get_span_context("session-123")
        assert context is not None
        assert context.is_valid
        assert context.trace_id != 0
        assert context.span_id != 0

    def test_get_span_context_returns_none_for_unknown_session(self, span_manager):
        """get_span_context should return None for non-existent sessions."""
        context = span_manager.get_span_context("unknown-session")
        assert context is None

    def test_nested_agent_spawning_maintains_trace_hierarchy(self, span_manager, span_exporter):
        """Multiple levels of agent spawning should maintain full trace hierarchy."""
        # Root session
        root_span = span_manager.start_session_span("root", {})
        root_trace_id = root_span.get_span_context().trace_id

        # Child session (agent spawn)
        child_span = span_manager.start_session_span("child", {}, parent_session_id="root")

        # Grandchild session (nested agent spawn)
        grandchild_span = span_manager.start_session_span(
            "grandchild", {}, parent_session_id="child"
        )

        # All should share the same trace_id (W3C Trace Context propagation)
        assert child_span.get_span_context().trace_id == root_trace_id
        assert grandchild_span.get_span_context().trace_id == root_trace_id

        # End all spans
        span_manager.end_session_span("grandchild")
        span_manager.end_session_span("child")
        span_manager.end_session_span("root")

        # Verify hierarchy in exported spans
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 3

        # Find each span
        root_exported = next(s for s in spans if s.parent is None)
        child_exported = next(
            s for s in spans if s.parent and s.parent.span_id == root_exported.context.span_id
        )
        grandchild_exported = next(
            s for s in spans if s.parent and s.parent.span_id == child_exported.context.span_id
        )

        # Verify chain
        assert grandchild_exported.parent.span_id == child_exported.context.span_id
        assert child_exported.parent.span_id == root_exported.context.span_id

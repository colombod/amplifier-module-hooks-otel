"""Span lifecycle management for OpenTelemetry tracing.

Based on colombod's W3C Trace Context implementation with nested tool stack
from robotdad/amplifier-module-hooks-otel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, StatusCode, Tracer

if TYPE_CHECKING:
    from .config import OTelConfig

logger = logging.getLogger(__name__)

# Placeholder value used when sensitive data is filtered
FILTERED_PLACEHOLDER = "[FILTERED]"


@dataclass
class SessionSpanContext:
    """Tracks spans for a single session.

    Supports nested tool execution (e.g., task tool spawning child agents)
    via a tool stack.
    """

    session_id: str
    root_span: Span | None = None
    current_turn: Span | None = None
    current_tool: Span | None = None
    tool_stack: list[Span] = field(default_factory=list)  # For nested tools
    turn_count: int = 0


class SpanManager:
    """Manage OpenTelemetry span lifecycle for Amplifier sessions.

    This class tracks the hierarchy of spans:
    - Session span (root): One per session
    - Turn span: One per execution turn, child of session
    - Child spans: LLM calls, tool executions, etc.

    Spans are correlated using session_id and correlation_key for matching
    start/end events.

    Supports nested tool execution via tool_stack for scenarios like
    the task tool spawning child agent sessions.

    Sensitive Data Filtering:
        When a config with filter_sensitive_data=True is provided (default),
        tool inputs and results are NOT captured in span attributes.
        Only safe metadata (tool name, success status, duration) is recorded.
    """

    def __init__(self, tracer: Tracer, config: OTelConfig | None = None) -> None:
        """Initialize SpanManager with a tracer and optional config.

        Args:
            tracer: OpenTelemetry Tracer instance.
            config: Optional OTelConfig for sensitive data filtering.
        """
        self._tracer = tracer
        self._config = config
        self._sessions: dict[str, SessionSpanContext] = {}
        self._active_spans: dict[str, Span] = {}  # correlation_key → span

    def _should_filter(self, data_type: str) -> bool:
        """Check if a specific type of sensitive data should be filtered.

        Args:
            data_type: One of "tool_parameters", "tool_results", etc.

        Returns:
            True if this data type should be filtered out.
        """
        if self._config is None:
            # Default to filtering when no config provided (safe by default)
            return True
        return self._config.should_filter(data_type)

    def _process_payload(
        self, content: str, payload_type: str = "default"
    ) -> tuple[str, dict[str, Any]]:
        """Process a payload, applying size limits if configured.

        Args:
            content: The payload content to process.
            payload_type: Type of payload for size limit lookup.

        Returns:
            Tuple of (processed_content, metadata_dict).
        """
        if self._config is None:
            # No config - return as-is with basic truncation
            if len(content) > 1000:
                return content[:1000] + "...[truncated]", {}
            return content, {}
        return self._config.process_payload(content, payload_type)

    def create_standalone_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """Create a standalone span not attached to any session.

        Use for one-off events like bundle operations that don't occur
        within a session context.

        Args:
            name: Span name (e.g., "bundle.add").
            attributes: Optional span attributes.

        Returns:
            The created span. Caller is responsible for calling span.end().
        """
        return self._tracer.start_span(name, attributes=attributes or {})

    def _get_context(self, session_id: str) -> SessionSpanContext:
        """Get or create span context for session."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionSpanContext(session_id=session_id)
        return self._sessions[session_id]

    def get_session_span(self, session_id: str) -> Span | None:
        """Get the root span for a session.

        Args:
            session_id: The session identifier.

        Returns:
            The session's root span if it exists, None otherwise.
        """
        ctx = self._sessions.get(session_id)
        return ctx.root_span if ctx else None

    def start_session_span(
        self,
        session_id: str,
        attributes: dict[str, Any],
        parent_session_id: str | None = None,
    ) -> Span:
        """Start root span for session, optionally as child of another session.

        For child sessions (spawned via session:fork), the parent_session_id
        links this span to the parent's trace. This ensures:
        - Same trace_id across parent and child sessions
        - Proper parent_id (span_id) linking in W3C Trace Context
        - Distributed trace continuity for agent spawning

        Args:
            session_id: The session identifier.
            attributes: Span attributes to set.
            parent_session_id: Optional parent session ID for trace linking.

        Returns:
            The created session span.
        """
        ctx = self._get_context(session_id)
        trace_context = None

        # If this is a child session, link to parent's span for trace continuity
        if parent_session_id:
            parent_ctx = self._sessions.get(parent_session_id)
            parent_span = parent_ctx.root_span if parent_ctx else None
            if parent_span:
                # Create context with parent span - this propagates trace_id
                # and sets parent_id to the parent span's span_id
                trace_context = trace.set_span_in_context(parent_span)
                logger.debug(f"Linking child session {session_id} to parent {parent_session_id}")
            else:
                logger.warning(
                    f"Parent session span not found for {parent_session_id}, "
                    f"child {session_id} will start new trace"
                )

        span = self._tracer.start_span(
            "amplifier.session",
            kind=SpanKind.SERVER,
            attributes=attributes,
            context=trace_context,
        )
        ctx.root_span = span
        ctx.turn_count = 0

        logger.debug(f"Started session span for {session_id}")
        return span

    def get_span_context(self, session_id: str) -> trace.SpanContext | None:
        """Get the SpanContext for a session's span.

        This can be used to extract trace_id and span_id for propagation
        or correlation purposes.

        Args:
            session_id: The session identifier.

        Returns:
            The SpanContext if the session span exists, None otherwise.
        """
        ctx = self._sessions.get(session_id)
        if ctx and ctx.root_span:
            return ctx.root_span.get_span_context()
        return None

    def end_session_span(
        self, session_id: str, status: str = "completed", error: str | None = None
    ) -> None:
        """End session span.

        Args:
            session_id: The session identifier.
            status: Session completion status.
            error: Optional error message.
        """
        ctx = self._sessions.pop(session_id, None)
        if not ctx:
            logger.debug(f"No session context found for {session_id}")
            return

        if ctx.root_span:
            ctx.root_span.set_attribute("session.status", status)
            ctx.root_span.set_attribute("session.turns", ctx.turn_count)
            if error:
                ctx.root_span.set_status(StatusCode.ERROR, error)
            else:
                ctx.root_span.set_status(StatusCode.OK)
            ctx.root_span.end()

        # Clean up any remaining turn span
        if ctx.current_turn:
            ctx.current_turn.end()

        # Clean up any remaining tool spans
        for tool_span in ctx.tool_stack:
            tool_span.end()
        if ctx.current_tool:
            ctx.current_tool.end()

        logger.debug(f"Ended session span for {session_id}")

    def start_turn_span(self, session_id: str) -> Span | None:
        """Start turn span as child of session.

        Args:
            session_id: The session identifier.

        Returns:
            The created turn span, or None if no session span exists.
        """
        ctx = self._get_context(session_id)
        parent_span = ctx.root_span
        if not parent_span:
            logger.warning(f"No session span for turn: {session_id}")
            return None

        # End previous turn span if exists
        if ctx.current_turn:
            ctx.current_turn.end()

        # Increment turn counter
        ctx.turn_count += 1

        # Start new turn span as child of session span
        with trace.use_span(parent_span, end_on_exit=False):
            span = self._tracer.start_span(
                "amplifier.turn",
                kind=SpanKind.INTERNAL,
                attributes={"amplifier.turn.number": ctx.turn_count},
            )
        ctx.current_turn = span
        logger.debug(f"Started turn {ctx.turn_count} span for {session_id}")
        return span

    def end_turn_span(self, session_id: str) -> None:
        """End current turn span.

        Args:
            session_id: The session identifier.
        """
        ctx = self._sessions.get(session_id)
        if ctx and ctx.current_turn:
            ctx.current_turn.end()
            ctx.current_turn = None
            logger.debug(f"Ended turn span for {session_id}")

    def start_tool_span(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict | None = None,
        correlation_key: str | None = None,
        max_attribute_length: int = 1000,
    ) -> Span | None:
        """Start a span for tool execution with nested tool support.

        Supports nested tools (e.g., task tool calling another tool) by
        maintaining a tool stack per session.

        Sensitive Data Filtering:
            When filter_sensitive_data is enabled (default), tool_input is NOT
            captured. Only tool.name and tool.has_input are recorded.

        Args:
            session_id: The session identifier.
            tool_name: Name of the tool being executed.
            tool_input: Optional tool input data (filtered if sensitive data filtering on).
            correlation_key: Optional key for later retrieval/ending.
            max_attribute_length: Max length for attribute values.

        Returns:
            The created tool span, or None if no parent span exists.
        """
        ctx = self._get_context(session_id)

        # Parent is current tool (nested), turn, or session
        parent = ctx.current_tool or ctx.current_turn or ctx.root_span
        if not parent:
            logger.warning(f"No parent span for tool: {session_id}")
            return None

        # Push current tool onto stack before creating new one (for nesting)
        if ctx.current_tool:
            ctx.tool_stack.append(ctx.current_tool)

        # Build attributes - always include tool name
        attributes: dict[str, Any] = {
            "tool.name": tool_name,
        }

        # Only include tool input if NOT filtering sensitive data
        if tool_input is not None:
            if self._should_filter("tool_parameters"):
                # Record that input exists but don't capture content
                attributes["tool.has_input"] = True
                attributes["tool.input"] = FILTERED_PLACEHOLDER
            else:
                # Capture input - apply payload size limits
                input_str = str(tool_input)
                processed_input, input_metadata = self._process_payload(input_str, "tool_payload")
                attributes["tool.input"] = processed_input
                # Add size metadata if available
                for key, value in input_metadata.items():
                    attributes[f"tool.input.{key.split('.')[-1]}"] = value

        with trace.use_span(parent, end_on_exit=False):
            span = self._tracer.start_span(
                "amplifier.tool",
                kind=SpanKind.INTERNAL,
                attributes=attributes,
            )

        ctx.current_tool = span
        if correlation_key:
            self._active_spans[correlation_key] = span

        logger.debug(
            f"Started tool span '{tool_name}' for {session_id} (stack depth: {len(ctx.tool_stack)})"
        )
        return span

    def end_tool_span(
        self,
        session_id: str,
        tool_name: str,
        correlation_key: str | None = None,
        success: bool = True,
        result: Any = None,
        error: str | None = None,
        max_attribute_length: int = 1000,
    ) -> None:
        """End current tool span with nested tool support.

        Sensitive Data Filtering:
            When filter_sensitive_data is enabled (default), tool results and
            error messages are NOT captured. Only tool.success status and
            tool.has_result are recorded.

        Args:
            session_id: The session identifier.
            tool_name: Name of the tool (for logging).
            correlation_key: Optional key used when starting.
            success: Whether tool execution succeeded.
            result: Optional tool result (filtered if sensitive data filtering on).
            error: Optional error message (filtered if sensitive data filtering on).
            max_attribute_length: Max length for attribute values.
        """
        ctx = self._sessions.get(session_id)
        span = None

        # Try correlation key first, then current tool
        if correlation_key:
            span = self._active_spans.pop(correlation_key, None)
        if not span and ctx:
            span = ctx.current_tool

        if span:
            span.set_attribute("tool.success", success)

            # Handle result - filter if sensitive data filtering enabled
            if result is not None:
                if self._should_filter("tool_results"):
                    # Record that result exists but don't capture content
                    span.set_attribute("tool.has_result", True)
                    span.set_attribute("tool.result", FILTERED_PLACEHOLDER)
                else:
                    # Capture result - apply payload size limits
                    result_str = str(result)
                    processed_result, result_metadata = self._process_payload(
                        result_str, "tool_payload"
                    )
                    span.set_attribute("tool.result", processed_result)
                    # Add size metadata if available
                    for key, value in result_metadata.items():
                        span.set_attribute(f"tool.result.{key.split('.')[-1]}", value)

            # Handle error - filter detailed message if sensitive data filtering enabled
            if error:
                if self._should_filter("error_messages"):
                    # Set error status but filter the detailed message
                    span.set_status(StatusCode.ERROR, FILTERED_PLACEHOLDER)
                else:
                    # Apply payload size limits to error messages
                    processed_error, _ = self._process_payload(error, "error")
                    span.set_status(StatusCode.ERROR, processed_error)
            else:
                span.set_status(StatusCode.OK)

            span.end()

            # Pop previous tool from stack (restore parent tool context)
            if ctx:
                ctx.current_tool = ctx.tool_stack.pop() if ctx.tool_stack else None

            logger.debug(f"Ended tool span '{tool_name}' for {session_id}")

    def start_child_span(
        self,
        session_id: str,
        name: str,
        kind: SpanKind,
        attributes: dict[str, Any],
        correlation_key: str | None = None,
    ) -> Span | None:
        """Start a child span under current turn (or session if no turn).

        Args:
            session_id: The session identifier.
            name: Name for the span.
            kind: SpanKind (CLIENT, INTERNAL, etc.).
            attributes: Span attributes to set.
            correlation_key: Optional key for later retrieval/ending.

        Returns:
            The created child span, or None if no parent span exists.
        """
        ctx = self._sessions.get(session_id)
        if not ctx:
            logger.warning(f"No session context for child span: {session_id}")
            return None

        # Try turn span first, fall back to session span
        parent = ctx.current_turn or ctx.root_span
        if not parent:
            logger.warning(f"No parent span for child: {session_id}")
            return None

        with trace.use_span(parent, end_on_exit=False):
            span = self._tracer.start_span(name, kind=kind, attributes=attributes)

        if correlation_key:
            self._active_spans[correlation_key] = span

        logger.debug(f"Started child span '{name}' for {session_id}")
        return span

    def end_child_span(
        self,
        correlation_key: str,
        status: StatusCode = StatusCode.OK,
        error_message: str | None = None,
    ) -> None:
        """End a child span by correlation key.

        Args:
            correlation_key: Key used when starting the span.
            status: Status code to set (OK or ERROR).
            error_message: Optional error message if status is ERROR.
        """
        span = self._active_spans.pop(correlation_key, None)
        if span:
            if status == StatusCode.ERROR:
                span.set_status(status, error_message or "Error")
            span.end()
            logger.debug(f"Ended child span: {correlation_key}")

    def get_active_span(self, correlation_key: str) -> Span | None:
        """Get active span by correlation key.

        Args:
            correlation_key: Key used when starting the span.

        Returns:
            The span if found, None otherwise.
        """
        return self._active_spans.get(correlation_key)

    def add_event(
        self,
        session_id: str,
        event_name: str,
        attributes: dict[str, Any] | None = None,
        span_type: str = "current",
    ) -> None:
        """Add an event to the appropriate span.

        Args:
            session_id: The session identifier.
            event_name: Name of the event.
            attributes: Optional event attributes.
            span_type: Which span to add to: "current", "tool", "turn", "session".
        """
        ctx = self._sessions.get(session_id)
        if not ctx:
            return

        # Select target span
        span = None
        if span_type == "tool" and ctx.current_tool:
            span = ctx.current_tool
        elif span_type == "turn" and ctx.current_turn:
            span = ctx.current_turn
        elif span_type == "session" and ctx.root_span:
            span = ctx.root_span
        else:
            # "current" - pick most specific active span
            span = ctx.current_tool or ctx.current_turn or ctx.root_span

        if span:
            span.add_event(event_name, attributes=attributes or {})

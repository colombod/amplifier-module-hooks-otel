"""Span lifecycle management for OpenTelemetry tracing."""

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, StatusCode, Tracer

logger = logging.getLogger(__name__)


class SpanManager:
    """Manage OpenTelemetry span lifecycle for Amplifier sessions.

    This class tracks the hierarchy of spans:
    - Session span (root): One per session
    - Turn span: One per execution turn, child of session
    - Child spans: LLM calls, tool executions, etc.

    Spans are correlated using session_id and correlation_key for matching
    start/end events.
    """

    def __init__(self, tracer: Tracer) -> None:
        """Initialize SpanManager with a tracer.

        Args:
            tracer: OpenTelemetry Tracer instance.
        """
        self._tracer = tracer
        self._session_spans: dict[str, Span] = {}  # session_id → root span
        self._turn_spans: dict[str, Span] = {}  # session_id → current turn span
        self._active_spans: dict[str, Span] = {}  # correlation_key → span
        self._turn_counters: dict[str, int] = {}  # session_id → turn number

    def start_session_span(self, session_id: str, attributes: dict[str, Any]) -> Span:
        """Start root span for session.

        Args:
            session_id: The session identifier.
            attributes: Span attributes to set.

        Returns:
            The created session span.
        """
        span = self._tracer.start_span(
            "amplifier.session",
            kind=SpanKind.SERVER,
            attributes=attributes,
        )
        self._session_spans[session_id] = span
        self._turn_counters[session_id] = 0
        logger.debug(f"Started session span for {session_id}")
        return span

    def end_session_span(self, session_id: str) -> None:
        """End session span.

        Args:
            session_id: The session identifier.
        """
        if span := self._session_spans.pop(session_id, None):
            span.end()
            logger.debug(f"Ended session span for {session_id}")
        # Cleanup turn span if exists
        if span := self._turn_spans.pop(session_id, None):
            span.end()
        self._turn_counters.pop(session_id, None)

    def start_turn_span(self, session_id: str) -> Span | None:
        """Start turn span as child of session.

        Args:
            session_id: The session identifier.

        Returns:
            The created turn span, or None if no session span exists.
        """
        parent_span = self._session_spans.get(session_id)
        if not parent_span:
            logger.warning(f"No session span for turn: {session_id}")
            return None

        # End previous turn span if exists
        if old_turn := self._turn_spans.get(session_id):
            old_turn.end()

        # Increment turn counter
        self._turn_counters[session_id] = self._turn_counters.get(session_id, 0) + 1
        turn_number = self._turn_counters[session_id]

        # Start new turn span as child of session span
        with trace.use_span(parent_span, end_on_exit=False):
            span = self._tracer.start_span(
                "amplifier.turn",
                kind=SpanKind.INTERNAL,
                attributes={"amplifier.turn.number": turn_number},
            )
        self._turn_spans[session_id] = span
        logger.debug(f"Started turn {turn_number} span for {session_id}")
        return span

    def end_turn_span(self, session_id: str) -> None:
        """End current turn span.

        Args:
            session_id: The session identifier.
        """
        if span := self._turn_spans.pop(session_id, None):
            span.end()
            logger.debug(f"Ended turn span for {session_id}")

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
        # Try turn span first, fall back to session span
        parent = self._turn_spans.get(session_id) or self._session_spans.get(session_id)
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

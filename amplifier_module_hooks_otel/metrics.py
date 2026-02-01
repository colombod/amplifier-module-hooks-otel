"""Metrics recording for OpenTelemetry.

Provides both GenAI semantic convention metrics and Amplifier-specific metrics
for comprehensive observability.
"""

import logging
import time
from typing import Any

from opentelemetry.metrics import Counter, Histogram, Meter

logger = logging.getLogger(__name__)


class MetricsRecorder:
    """Record OpenTelemetry metrics for Amplifier operations.

    Tracks two categories of metrics:

    **GenAI Semantic Convention Metrics** (for APM tool compatibility):
    - gen_ai.client.token.usage - Token consumption histogram
    - gen_ai.client.operation.duration - LLM operation duration

    **Amplifier-Specific Metrics** (for detailed observability):
    - amplifier.tool.duration - Tool execution time
    - amplifier.session.duration - Total session duration
    - amplifier.tool.calls - Tool invocation count
    - amplifier.llm.calls - LLM call count
    - amplifier.sessions.started - Session count
    - amplifier.turns.completed - Turn count
    """

    def __init__(self, meter: Meter) -> None:
        """Initialize MetricsRecorder with a meter.

        Args:
            meter: OpenTelemetry Meter instance.
        """
        self._meter = meter
        self._start_times: dict[str, float] = {}
        self._session_start_times: dict[str, float] = {}

        # ========== GenAI Semantic Convention Metrics ==========
        # These follow OpenTelemetry GenAI conventions for APM compatibility

        self._token_usage: Histogram = meter.create_histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Number of input and output tokens used",
        )
        self._operation_duration: Histogram = meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="GenAI operation duration",
        )

        # ========== Amplifier-Specific Metrics ==========
        # These provide detailed Amplifier observability

        # Duration histograms
        self._tool_duration: Histogram = meter.create_histogram(
            "amplifier.tool.duration",
            unit="s",
            description="Tool execution duration",
        )
        self._session_duration: Histogram = meter.create_histogram(
            "amplifier.session.duration",
            unit="s",
            description="Total session duration",
        )

        # Call counters
        self._tool_calls: Counter = meter.create_counter(
            "amplifier.tool.calls",
            unit="{call}",
            description="Number of tool invocations",
        )
        self._llm_calls: Counter = meter.create_counter(
            "amplifier.llm.calls",
            unit="{call}",
            description="Number of LLM calls",
        )

        # Session/turn counters
        self._sessions_started: Counter = meter.create_counter(
            "amplifier.sessions.started",
            unit="{session}",
            description="Number of sessions started",
        )
        self._turns_completed: Counter = meter.create_counter(
            "amplifier.turns.completed",
            unit="{turn}",
            description="Number of turns completed",
        )

    # ========== Timing Utilities ==========

    def start_timing(self, correlation_key: str) -> None:
        """Start timing an operation.

        Args:
            correlation_key: Key to associate with this timing.
        """
        self._start_times[correlation_key] = time.perf_counter()

    def _get_elapsed(self, correlation_key: str) -> float | None:
        """Get elapsed time for a correlation key without recording.

        Args:
            correlation_key: Key used when starting the timing.

        Returns:
            Elapsed time in seconds, or None if no start time found.
        """
        start = self._start_times.pop(correlation_key, None)
        if start is None:
            return None
        return time.perf_counter() - start

    # ========== GenAI Convention Methods ==========

    def record_duration(self, correlation_key: str, attributes: dict[str, Any]) -> float | None:
        """Record GenAI operation duration and return elapsed time.

        Args:
            correlation_key: Key used when starting the timing.
            attributes: Attributes to associate with the metric.

        Returns:
            The elapsed duration in seconds, or None if no start time found.
        """
        duration = self._get_elapsed(correlation_key)
        if duration is None:
            return None

        self._operation_duration.record(duration, attributes=attributes)
        logger.debug(f"Recorded duration {duration:.3f}s for {correlation_key}")
        return duration

    def record_token_usage(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
        attributes: dict[str, Any],
    ) -> None:
        """Record token usage metrics (GenAI convention).

        Args:
            input_tokens: Number of input tokens (or None to skip).
            output_tokens: Number of output tokens (or None to skip).
            attributes: Base attributes to associate with the metrics.
        """
        if input_tokens is not None:
            self._token_usage.record(
                input_tokens,
                attributes={**attributes, "gen_ai.token.type": "input"},
            )
        if output_tokens is not None:
            self._token_usage.record(
                output_tokens,
                attributes={**attributes, "gen_ai.token.type": "output"},
            )
        logger.debug(f"Recorded tokens: input={input_tokens}, output={output_tokens}")

    # ========== Amplifier-Specific Methods ==========

    def record_tool_call(
        self,
        tool_name: str,
        duration: float | None = None,
        success: bool = True,
    ) -> None:
        """Record a tool invocation with optional duration.

        Args:
            tool_name: Name of the tool.
            duration: Execution duration in seconds (or None to skip duration).
            success: Whether the tool succeeded.
        """
        attributes = {
            "amplifier.tool.name": tool_name,
            "amplifier.tool.success": success,
        }

        # Always count the call
        self._tool_calls.add(1, attributes=attributes)

        # Record duration if provided
        if duration is not None:
            self._tool_duration.record(duration, attributes=attributes)
            logger.debug(f"Recorded tool '{tool_name}' duration: {duration:.3f}s")

    def record_llm_call(
        self,
        provider: str,
        model: str,
        success: bool = True,
    ) -> None:
        """Record an LLM call.

        Args:
            provider: Provider name (e.g., "anthropic", "openai").
            model: Model name.
            success: Whether the call succeeded.
        """
        attributes = {
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "amplifier.llm.success": success,
        }
        self._llm_calls.add(1, attributes=attributes)
        logger.debug(f"Recorded LLM call: {provider}/{model}")

    def record_session_started(
        self,
        session_id: str,
        user_id: str = "",
        is_fork: bool = False,
        is_resume: bool = False,
    ) -> None:
        """Record a session start and begin timing.

        Args:
            session_id: Session identifier.
            user_id: User identifier.
            is_fork: Whether this is a forked (child) session.
            is_resume: Whether this is a resumed session.
        """
        attributes = {
            "amplifier.session.type": "fork" if is_fork else ("resume" if is_resume else "new"),
        }
        if user_id:
            attributes["amplifier.user.id"] = user_id

        self._sessions_started.add(1, attributes=attributes)
        self._session_start_times[session_id] = time.perf_counter()
        logger.debug(f"Recorded session start: {session_id}")

    def record_session_ended(
        self,
        session_id: str,
        status: str = "completed",
    ) -> float | None:
        """Record session end and duration.

        Args:
            session_id: Session identifier.
            status: Session end status (completed, cancelled, error).

        Returns:
            Session duration in seconds, or None if start not tracked.
        """
        start = self._session_start_times.pop(session_id, None)
        if start is None:
            return None

        duration = time.perf_counter() - start
        attributes = {
            "amplifier.session.status": status,
        }
        self._session_duration.record(duration, attributes=attributes)
        logger.debug(f"Recorded session '{session_id}' duration: {duration:.3f}s")
        return duration

    def record_turn_completed(
        self,
        session_id: str,
        turn_number: int,
    ) -> None:
        """Record a completed turn.

        Args:
            session_id: Session identifier.
            turn_number: The turn number that completed.
        """
        attributes = {
            "amplifier.turn.number": turn_number,
        }
        self._turns_completed.add(1, attributes=attributes)
        logger.debug(f"Recorded turn {turn_number} completed for session {session_id}")

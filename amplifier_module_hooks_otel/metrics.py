"""Metrics recording for OpenTelemetry."""

import logging
import time
from typing import Any

from opentelemetry.metrics import Histogram, Meter

logger = logging.getLogger(__name__)


class MetricsRecorder:
    """Record OpenTelemetry metrics for Amplifier operations.

    Tracks token usage and operation duration following GenAI semantic
    conventions.
    """

    def __init__(self, meter: Meter) -> None:
        """Initialize MetricsRecorder with a meter.

        Args:
            meter: OpenTelemetry Meter instance.
        """
        self._meter = meter
        self._start_times: dict[str, float] = {}

        # Create histograms following GenAI semantic conventions
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

    def start_timing(self, correlation_key: str) -> None:
        """Start timing an operation.

        Args:
            correlation_key: Key to associate with this timing.
        """
        self._start_times[correlation_key] = time.perf_counter()

    def record_duration(self, correlation_key: str, attributes: dict[str, Any]) -> float | None:
        """Record duration and return elapsed time.

        Args:
            correlation_key: Key used when starting the timing.
            attributes: Attributes to associate with the metric.

        Returns:
            The elapsed duration in seconds, or None if no start time found.
        """
        start = self._start_times.pop(correlation_key, None)
        if start is None:
            return None

        duration = time.perf_counter() - start
        self._operation_duration.record(duration, attributes=attributes)
        logger.debug(f"Recorded duration {duration:.3f}s for {correlation_key}")
        return duration

    def record_token_usage(
        self,
        input_tokens: int | None,
        output_tokens: int | None,
        attributes: dict[str, Any],
    ) -> None:
        """Record token usage metrics.

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

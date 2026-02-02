"""Configuration for OpenTelemetry hook module."""

import os
from dataclasses import dataclass, field
from typing import Any, Literal

# Environment variable for global opt-out
OPT_OUT_ENV_VAR = "AMPLIFIER_OTEL_OPT_OUT"

# Supported exporter types
ExporterType = Literal["console", "otlp-http", "otlp-grpc", "file"]


def _check_opt_out() -> bool:
    """Check if telemetry is opted out via environment variable.

    Returns:
        True if telemetry should be ENABLED (not opted out).
        False if telemetry should be DISABLED (opted out).
    """
    opt_out_value = os.environ.get(OPT_OUT_ENV_VAR, "").lower()
    # Opt-out if env var is set to truthy value
    if opt_out_value in ("1", "true", "yes", "on"):
        return False  # Disabled (opted out)
    return True  # Enabled (not opted out)


@dataclass
class SensitiveDataConfig:
    """Configuration for sensitive data filtering.

    By default, sensitive data filtering is ENABLED to protect privacy.
    When enabled, the following data is NOT sent to telemetry:
    - LLM responses (content)
    - User inputs/prompts (content)
    - Tool parameters/arguments
    - Tool results/outputs

    What IS still captured (safe for telemetry):
    - Timings and durations
    - Tool names (which tool was called)
    - Token counts (input/output)
    - Event types and lifecycle
    - Session/turn metadata
    - Error types (not messages with sensitive content)
    - Model and provider names
    """

    # Master filter switch - ON by default for privacy
    filter_sensitive_data: bool = True

    # Granular controls (only apply when filter_sensitive_data=True)
    filter_llm_content: bool = True  # Filter LLM request/response content
    filter_user_input: bool = True  # Filter user prompts
    filter_tool_parameters: bool = True  # Filter tool input arguments
    filter_tool_results: bool = True  # Filter tool output/results
    filter_error_messages: bool = True  # Filter detailed error messages


@dataclass
class CaptureConfig:
    """What telemetry signals to capture."""

    traces: bool = True
    metrics: bool = True
    span_events: bool = True


@dataclass
class OTelConfig:
    """Configuration for OTel hook.

    Attributes:
        enabled: Master switch - if False, all telemetry is disabled.
            Also respects AMPLIFIER_OTEL_OPT_OUT environment variable.
        service_name: Service name in traces (default: "amplifier").
        service_version: Service version (default: "0.1.0").
        user_id: User identifier for team tracking (falls back to $USER).
        team_id: Team identifier for grouping in APM dashboards.
        exporter: Exporter type - "console", "otlp-http", "otlp-grpc", "file".
        endpoint: OTLP endpoint URL (default: "http://localhost:4318").
        headers: HTTP headers for OTLP (e.g., auth tokens).
        file_path: Path for file exporter output.
        sampling_rate: Sampling rate 0.0-1.0 (1.0 = 100%).
        capture: What to capture (traces, metrics, span_events).
        max_attribute_length: Max length for attribute values (truncates).
        batch_delay_ms: Batch export delay in milliseconds.
        max_batch_size: Maximum spans per batch.
        debug: Enable debug output.
    """

    # Master switch
    enabled: bool = field(default_factory=_check_opt_out)

    # Service identification
    service_name: str = "amplifier"
    service_version: str = "0.1.0"

    # User/team identification (for team tracking)
    user_id: str = ""  # Falls back to $USER if empty
    team_id: str = ""  # Optional team grouping

    # Exporter configuration
    exporter: ExporterType = "console"
    endpoint: str = "http://localhost:4318"  # OTLP HTTP default
    headers: dict[str, str] = field(default_factory=dict)

    # For file exporter
    file_path: str = "/tmp/amplifier-traces.jsonl"

    # Sampling (1.0 = 100%, 0.1 = 10%)
    sampling_rate: float = 1.0

    # What to capture
    capture: CaptureConfig = field(default_factory=CaptureConfig)

    # Sensitive data filtering (ON by default for privacy)
    sensitive_data: SensitiveDataConfig = field(default_factory=SensitiveDataConfig)

    # Attribute limits (prevent huge payloads)
    max_attribute_length: int = 1000

    # Batching configuration
    batch_delay_ms: int = 5000
    max_batch_size: int = 512

    # Debug mode (verbose logging)
    debug: bool = False

    # Legacy compatibility aliases
    @property
    def traces_enabled(self) -> bool:
        """Legacy alias for capture.traces."""
        return self.capture.traces

    @property
    def metrics_enabled(self) -> bool:
        """Legacy alias for capture.metrics."""
        return self.capture.metrics

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "OTelConfig":
        """Create OTelConfig from a dictionary.

        Extracts known fields and ignores unknown ones.
        The `enabled` field respects both config and AMPLIFIER_OTEL_OPT_OUT env var.

        Args:
            config: Dictionary with configuration values.

        Returns:
            OTelConfig instance with values from dict or defaults.
        """
        # Handle nested capture config
        capture_data = config.pop("capture", {})
        if capture_data:
            capture = CaptureConfig(**capture_data)
        else:
            # Legacy flat config support
            capture = CaptureConfig(
                traces=config.pop("traces_enabled", True),
                metrics=config.pop("metrics_enabled", True),
                span_events=config.pop("span_events_enabled", True),
            )

        # Handle nested sensitive_data config
        sensitive_data_dict = config.pop("sensitive_data", {})
        if sensitive_data_dict:
            sensitive_data = SensitiveDataConfig(**sensitive_data_dict)
        else:
            # Legacy flat config support - filter_sensitive_data at top level
            filter_sensitive = config.pop("filter_sensitive_data", True)
            sensitive_data = SensitiveDataConfig(
                filter_sensitive_data=filter_sensitive,
                filter_llm_content=config.pop("filter_llm_content", True),
                filter_user_input=config.pop("filter_user_input", True),
                filter_tool_parameters=config.pop("filter_tool_parameters", True),
                filter_tool_results=config.pop("filter_tool_results", True),
                filter_error_messages=config.pop("filter_error_messages", True),
            )

        known_fields = {
            "enabled",
            "service_name",
            "service_version",
            "user_id",
            "team_id",
            "exporter",
            "endpoint",
            "headers",
            "file_path",
            "sampling_rate",
            "max_attribute_length",
            "batch_delay_ms",
            "max_batch_size",
            "debug",
        }

        # Extract only known fields
        filtered = {k: v for k, v in config.items() if k in known_fields}

        # Create instance
        instance = cls(capture=capture, sensitive_data=sensitive_data, **filtered)

        # If env var opts out, override config
        if not _check_opt_out():
            instance.enabled = False

        return instance

    @property
    def is_active(self) -> bool:
        """Check if any telemetry is active.

        Returns:
            True if enabled AND at least one of traces/metrics is enabled.
        """
        return self.enabled and (self.capture.traces or self.capture.metrics)

    def should_filter(self, data_type: str) -> bool:
        """Check if a specific type of sensitive data should be filtered.

        Args:
            data_type: One of "llm_content", "user_input", "tool_parameters",
                       "tool_results", "error_messages".

        Returns:
            True if this data type should be filtered out.
        """
        if not self.sensitive_data.filter_sensitive_data:
            return False

        filter_map = {
            "llm_content": self.sensitive_data.filter_llm_content,
            "user_input": self.sensitive_data.filter_user_input,
            "tool_parameters": self.sensitive_data.filter_tool_parameters,
            "tool_results": self.sensitive_data.filter_tool_results,
            "error_messages": self.sensitive_data.filter_error_messages,
        }
        return filter_map.get(data_type, True)

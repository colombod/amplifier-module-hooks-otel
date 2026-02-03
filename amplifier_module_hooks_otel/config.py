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
class PayloadLimitsConfig:
    """Configuration for handling large payloads in telemetry.

    Large payloads (like LLM thinking blocks, verbose tool outputs) can cause:
    - Telemetry backend size limits exceeded
    - Increased costs for telemetry storage
    - Performance issues in trace viewers
    - Potential exposure of sensitive data

    This config allows dropping or truncating large payloads to keep
    telemetry efficient and within backend limits.

    Attributes:
        drop_large_payloads: If True, payloads exceeding max size are replaced
            with a placeholder. If False, they are truncated to max size.
        max_payload_size: Maximum size in bytes for any single payload.
            Default 10KB (10240 bytes) - suitable for most telemetry backends.
        max_llm_content_size: Max size for LLM content (prompts, responses,
            thinking blocks). Default 5KB - these can be very large.
        max_tool_payload_size: Max size for tool inputs/outputs.
            Default 5KB - tool results can be verbose.
        max_error_size: Max size for error messages/stack traces.
            Default 2KB - usually sufficient for debugging.
        include_size_metadata: If True, adds attributes like
            `payload.original_size` and `payload.truncated` for debugging.
    """

    # Master switch for large payload handling
    drop_large_payloads: bool = True  # Drop (not truncate) by default for safety

    # Size limits in bytes
    max_payload_size: int = 10240  # 10KB default
    max_llm_content_size: int = 5120  # 5KB for LLM content
    max_tool_payload_size: int = 5120  # 5KB for tool I/O
    max_error_size: int = 2048  # 2KB for errors

    # Metadata for debugging
    include_size_metadata: bool = True  # Add original_size info when dropping


# Placeholder constants for dropped/truncated content
PAYLOAD_DROPPED_PLACEHOLDER = "[PAYLOAD_DROPPED: size={size} bytes, limit={limit} bytes]"
PAYLOAD_TRUNCATED_SUFFIX = "...[TRUNCATED: {truncated} bytes removed]"


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

    # Payload size limits (drop large payloads by default)
    payload_limits: PayloadLimitsConfig = field(default_factory=PayloadLimitsConfig)

    # Attribute limits (legacy - use payload_limits for fine-grained control)
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

        # Handle nested payload_limits config
        payload_limits_dict = config.pop("payload_limits", {})
        if payload_limits_dict:
            payload_limits = PayloadLimitsConfig(**payload_limits_dict)
        else:
            # Legacy flat config support
            payload_limits = PayloadLimitsConfig(
                drop_large_payloads=config.pop("drop_large_payloads", True),
                max_payload_size=config.pop("max_payload_size", 10240),
                max_llm_content_size=config.pop("max_llm_content_size", 5120),
                max_tool_payload_size=config.pop("max_tool_payload_size", 5120),
                max_error_size=config.pop("max_error_size", 2048),
                include_size_metadata=config.pop("include_size_metadata", True),
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
        instance = cls(
            capture=capture,
            sensitive_data=sensitive_data,
            payload_limits=payload_limits,
            **filtered,
        )

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

    def get_payload_limit(self, payload_type: str) -> int:
        """Get the size limit for a specific payload type.

        Args:
            payload_type: One of "llm_content", "tool_payload", "error", or "default".

        Returns:
            Size limit in bytes for this payload type.
        """
        limit_map = {
            "llm_content": self.payload_limits.max_llm_content_size,
            "tool_payload": self.payload_limits.max_tool_payload_size,
            "error": self.payload_limits.max_error_size,
            "default": self.payload_limits.max_payload_size,
        }
        return limit_map.get(payload_type, self.payload_limits.max_payload_size)

    def process_payload(
        self, content: str, payload_type: str = "default"
    ) -> tuple[str, dict[str, Any]]:
        """Process a payload, applying size limits if configured.

        This method checks if a payload exceeds size limits and either drops
        or truncates it based on configuration.

        Args:
            content: The payload content to process.
            payload_type: Type of payload for size limit lookup.

        Returns:
            Tuple of (processed_content, metadata_dict).
            metadata_dict contains size info if include_size_metadata is True.
        """
        if not content:
            return content, {}

        content_bytes = len(content.encode("utf-8"))
        limit = self.get_payload_limit(payload_type)
        metadata: dict[str, Any] = {}

        # Check if within limits
        if content_bytes <= limit:
            return content, metadata

        # Payload exceeds limit - handle based on config
        if self.payload_limits.include_size_metadata:
            metadata["payload.original_size"] = content_bytes
            metadata["payload.limit"] = limit
            metadata["payload.truncated"] = True

        if self.payload_limits.drop_large_payloads:
            # Drop and replace with placeholder
            processed = PAYLOAD_DROPPED_PLACEHOLDER.format(size=content_bytes, limit=limit)
        else:
            # Truncate to limit
            # Need to be careful with UTF-8 encoding - truncate by characters
            # and re-check byte size
            truncated_content = content
            while len(truncated_content.encode("utf-8")) > limit:
                truncated_content = truncated_content[:-100]  # Remove 100 chars at a time

            bytes_removed = content_bytes - len(truncated_content.encode("utf-8"))
            processed = truncated_content + PAYLOAD_TRUNCATED_SUFFIX.format(truncated=bytes_removed)

        return processed, metadata

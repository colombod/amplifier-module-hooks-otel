"""Configuration for OpenTelemetry hook module."""

from dataclasses import dataclass
from typing import Any


@dataclass
class OTelConfig:
    """Configuration for OTel hook.

    Attributes:
        service_name: Name of the service for OTel resource attributes.
        service_version: Version of the service.
        traces_enabled: Whether to emit trace spans.
        metrics_enabled: Whether to record metrics.
        capture_input_messages: Whether to capture LLM input messages (privacy risk).
        capture_output_messages: Whether to capture LLM output messages (privacy risk).
        capture_tool_input: Whether to capture tool input parameters (privacy risk).
        capture_tool_output: Whether to capture tool output results (privacy risk).
    """

    service_name: str = "amplifier"
    service_version: str = "unknown"
    traces_enabled: bool = True
    metrics_enabled: bool = True
    # Privacy controls - default OFF
    capture_input_messages: bool = False
    capture_output_messages: bool = False
    capture_tool_input: bool = False
    capture_tool_output: bool = False

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "OTelConfig":
        """Create OTelConfig from a dictionary.

        Extracts known fields and ignores unknown ones.

        Args:
            config: Dictionary with configuration values.

        Returns:
            OTelConfig instance with values from dict or defaults.
        """
        known_fields = {
            "service_name",
            "service_version",
            "traces_enabled",
            "metrics_enabled",
            "capture_input_messages",
            "capture_output_messages",
            "capture_tool_input",
            "capture_tool_output",
        }

        # Extract only known fields
        filtered = {k: v for k, v in config.items() if k in known_fields}

        return cls(**filtered)

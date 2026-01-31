"""Configuration for OpenTelemetry hook module."""

from dataclasses import dataclass
from typing import Any


@dataclass
class OTelConfig:
    """Configuration for OTel hook.

    Attributes:
        traces_enabled: Whether to emit trace spans.
        metrics_enabled: Whether to record metrics.
    """

    traces_enabled: bool = True
    metrics_enabled: bool = True

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
            "traces_enabled",
            "metrics_enabled",
        }

        # Extract only known fields
        filtered = {k: v for k, v in config.items() if k in known_fields}

        return cls(**filtered)

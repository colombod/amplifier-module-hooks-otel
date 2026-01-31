"""Configuration for OpenTelemetry hook module."""

import os
from dataclasses import dataclass, field
from typing import Any

# Environment variable for global opt-out
OPT_OUT_ENV_VAR = "AMPLIFIER_OTEL_OPT_OUT"


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
class OTelConfig:
    """Configuration for OTel hook.

    Attributes:
        enabled: Master switch - if False, all telemetry is disabled.
            Also respects AMPLIFIER_OTEL_OPT_OUT environment variable.
        traces_enabled: Whether to emit trace spans.
        metrics_enabled: Whether to record metrics.
    """

    enabled: bool = field(default_factory=_check_opt_out)
    traces_enabled: bool = True
    metrics_enabled: bool = True

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
        known_fields = {
            "enabled",
            "traces_enabled",
            "metrics_enabled",
        }

        # Extract only known fields
        filtered = {k: v for k, v in config.items() if k in known_fields}

        # Create instance (enabled defaults to env var check)
        instance = cls(**filtered)

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
        return self.enabled and (self.traces_enabled or self.metrics_enabled)

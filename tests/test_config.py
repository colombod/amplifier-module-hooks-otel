"""Tests for OTelConfig and configuration handling."""

import os
from unittest.mock import patch

import pytest

from amplifier_module_hooks_otel.config import (
    OPT_OUT_ENV_VAR,
    CaptureConfig,
    OTelConfig,
    _check_opt_out,
)


class TestOptOut:
    """Tests for opt-out functionality."""

    def test_opt_out_not_set(self):
        """When env var is not set, telemetry should be enabled."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            os.environ.pop(OPT_OUT_ENV_VAR, None)
            assert _check_opt_out() is True

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "Yes", "ON"])
    def test_opt_out_truthy_values(self, value: str):
        """Truthy values should disable telemetry."""
        with patch.dict(os.environ, {OPT_OUT_ENV_VAR: value}):
            assert _check_opt_out() is False

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "other"])
    def test_opt_out_falsy_values(self, value: str):
        """Non-truthy values should keep telemetry enabled."""
        with patch.dict(os.environ, {OPT_OUT_ENV_VAR: value}):
            assert _check_opt_out() is True


class TestCaptureConfig:
    """Tests for CaptureConfig."""

    def test_defaults(self):
        """Default values should enable all capture."""
        config = CaptureConfig()
        assert config.traces is True
        assert config.metrics is True
        assert config.span_events is True

    def test_custom_values(self):
        """Should accept custom values."""
        config = CaptureConfig(traces=False, metrics=True, span_events=False)
        assert config.traces is False
        assert config.metrics is True
        assert config.span_events is False


class TestOTelConfig:
    """Tests for OTelConfig."""

    def test_defaults(self):
        """Default configuration values."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(OPT_OUT_ENV_VAR, None)
            config = OTelConfig()

            assert config.enabled is True
            assert config.service_name == "amplifier"
            assert config.service_version == "0.1.0"
            assert config.exporter == "console"
            assert config.endpoint == "http://localhost:4318"
            assert config.sampling_rate == 1.0
            assert config.capture.traces is True
            assert config.capture.metrics is True

    def test_exporter_types(self):
        """Should accept valid exporter types."""
        for exporter in ["console", "otlp-http", "otlp-grpc", "file"]:
            config = OTelConfig(exporter=exporter)  # type: ignore
            assert config.exporter == exporter

    def test_sampling_rate(self):
        """Should accept sampling rate values."""
        config = OTelConfig(sampling_rate=0.5)
        assert config.sampling_rate == 0.5

        config = OTelConfig(sampling_rate=0.0)
        assert config.sampling_rate == 0.0

        config = OTelConfig(sampling_rate=1.0)
        assert config.sampling_rate == 1.0

    def test_team_and_user_tracking(self):
        """Should support team and user tracking."""
        config = OTelConfig(user_id="test-user", team_id="test-team")
        assert config.user_id == "test-user"
        assert config.team_id == "test-team"

    def test_batch_config(self):
        """Should support batch configuration."""
        config = OTelConfig(batch_delay_ms=10000, max_batch_size=1024)
        assert config.batch_delay_ms == 10000
        assert config.max_batch_size == 1024

    def test_file_path(self):
        """Should support file path for file exporter."""
        config = OTelConfig(exporter="file", file_path="/custom/path.jsonl")  # type: ignore
        assert config.file_path == "/custom/path.jsonl"

    def test_headers(self):
        """Should support custom headers for OTLP."""
        headers = {"Authorization": "Bearer token123"}
        config = OTelConfig(headers=headers)
        assert config.headers == headers

    def test_legacy_aliases(self):
        """Legacy aliases should work."""
        config = OTelConfig()
        config.capture.traces = False
        config.capture.metrics = True

        assert config.traces_enabled is False
        assert config.metrics_enabled is True

    def test_is_active_when_enabled(self):
        """is_active should be True when enabled and traces/metrics on."""
        config = OTelConfig(enabled=True)
        config.capture.traces = True
        assert config.is_active is True

    def test_is_active_when_disabled(self):
        """is_active should be False when disabled."""
        config = OTelConfig(enabled=False)
        assert config.is_active is False

    def test_is_active_when_no_signals(self):
        """is_active should be False when no signals enabled."""
        config = OTelConfig(enabled=True)
        config.capture.traces = False
        config.capture.metrics = False
        assert config.is_active is False


class TestOTelConfigFromDict:
    """Tests for OTelConfig.from_dict()."""

    def test_empty_dict(self):
        """Empty dict should use defaults."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop(OPT_OUT_ENV_VAR, None)
            config = OTelConfig.from_dict({})
            assert config.enabled is True
            assert config.exporter == "console"

    def test_basic_fields(self):
        """Should parse basic fields."""
        config = OTelConfig.from_dict(
            {
                "enabled": True,
                "exporter": "otlp-http",
                "endpoint": "http://jaeger:4318",
                "service_name": "my-app",
            }
        )
        assert config.exporter == "otlp-http"
        assert config.endpoint == "http://jaeger:4318"
        assert config.service_name == "my-app"

    def test_nested_capture_config(self):
        """Should parse nested capture config."""
        config = OTelConfig.from_dict(
            {
                "capture": {
                    "traces": True,
                    "metrics": False,
                    "span_events": True,
                }
            }
        )
        assert config.capture.traces is True
        assert config.capture.metrics is False
        assert config.capture.span_events is True

    def test_legacy_flat_config(self):
        """Should support legacy flat config (traces_enabled, metrics_enabled)."""
        config = OTelConfig.from_dict(
            {
                "traces_enabled": False,
                "metrics_enabled": True,
            }
        )
        assert config.capture.traces is False
        assert config.capture.metrics is True

    def test_unknown_fields_ignored(self):
        """Unknown fields should be ignored."""
        config = OTelConfig.from_dict(
            {
                "enabled": True,
                "unknown_field": "value",
                "another_unknown": 123,
            }
        )
        assert config.enabled is True
        assert not hasattr(config, "unknown_field")

    def test_env_var_overrides_config(self):
        """Environment variable should override config."""
        with patch.dict(os.environ, {OPT_OUT_ENV_VAR: "1"}):
            config = OTelConfig.from_dict({"enabled": True})
            assert config.enabled is False

    def test_all_fields(self):
        """Should parse all supported fields."""
        config = OTelConfig.from_dict(
            {
                "enabled": True,
                "service_name": "test-service",
                "service_version": "2.0.0",
                "user_id": "user123",
                "team_id": "team456",
                "exporter": "otlp-grpc",
                "endpoint": "http://collector:4317",
                "headers": {"X-Custom": "value"},
                "file_path": "/logs/traces.jsonl",
                "sampling_rate": 0.5,
                "max_attribute_length": 2000,
                "batch_delay_ms": 10000,
                "max_batch_size": 256,
                "debug": True,
            }
        )
        assert config.service_name == "test-service"
        assert config.service_version == "2.0.0"
        assert config.user_id == "user123"
        assert config.team_id == "team456"
        assert config.exporter == "otlp-grpc"
        assert config.endpoint == "http://collector:4317"
        assert config.headers == {"X-Custom": "value"}
        assert config.file_path == "/logs/traces.jsonl"
        assert config.sampling_rate == 0.5
        assert config.max_attribute_length == 2000
        assert config.batch_delay_ms == 10000
        assert config.max_batch_size == 256
        assert config.debug is True

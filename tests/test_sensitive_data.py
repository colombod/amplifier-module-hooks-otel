"""Tests for sensitive data filtering functionality."""

import os
from unittest.mock import patch

import pytest
from opentelemetry.trace import StatusCode

from amplifier_module_hooks_otel.config import OTelConfig, SensitiveDataConfig
from amplifier_module_hooks_otel.spans import FILTERED_PLACEHOLDER, SpanManager


class TestSensitiveDataConfig:
    """Tests for SensitiveDataConfig defaults and behavior."""

    def test_defaults_filter_enabled(self):
        """By default, sensitive data filtering should be enabled."""
        config = SensitiveDataConfig()
        assert config.filter_sensitive_data is True
        assert config.filter_llm_content is True
        assert config.filter_user_input is True
        assert config.filter_tool_parameters is True
        assert config.filter_tool_results is True
        assert config.filter_error_messages is True

    def test_can_disable_filtering(self):
        """Filtering can be disabled entirely."""
        config = SensitiveDataConfig(filter_sensitive_data=False)
        assert config.filter_sensitive_data is False

    def test_granular_controls(self):
        """Individual filter types can be controlled."""
        config = SensitiveDataConfig(
            filter_sensitive_data=True,
            filter_llm_content=False,  # Allow LLM content
            filter_tool_parameters=True,
            filter_tool_results=False,  # Allow results
        )
        assert config.filter_sensitive_data is True
        assert config.filter_llm_content is False
        assert config.filter_tool_parameters is True
        assert config.filter_tool_results is False


class TestOTelConfigShouldFilter:
    """Tests for OTelConfig.should_filter() method."""

    def test_should_filter_when_enabled(self):
        """should_filter returns True when filtering is enabled."""
        config = OTelConfig()
        # Default is filtering enabled
        assert config.should_filter("tool_parameters") is True
        assert config.should_filter("tool_results") is True
        assert config.should_filter("error_messages") is True
        assert config.should_filter("llm_content") is True
        assert config.should_filter("user_input") is True

    def test_should_not_filter_when_disabled(self):
        """should_filter returns False when filtering is disabled."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = False

        assert config.should_filter("tool_parameters") is False
        assert config.should_filter("tool_results") is False
        assert config.should_filter("error_messages") is False

    def test_granular_filter_control(self):
        """Granular controls work correctly."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = True
        config.sensitive_data.filter_tool_parameters = False  # Allow params
        config.sensitive_data.filter_tool_results = True  # Filter results

        assert config.should_filter("tool_parameters") is False
        assert config.should_filter("tool_results") is True

    def test_unknown_data_type_defaults_to_filter(self):
        """Unknown data types default to being filtered (safe default)."""
        config = OTelConfig()
        assert config.should_filter("unknown_type") is True


class TestOTelConfigFromDictSensitiveData:
    """Tests for OTelConfig.from_dict() with sensitive_data section."""

    def test_default_sensitive_data_config(self):
        """Default config should have filtering enabled."""
        with patch.dict(os.environ, {}, clear=True):
            config = OTelConfig.from_dict({})
            assert config.sensitive_data.filter_sensitive_data is True

    def test_nested_sensitive_data_config(self):
        """Should parse nested sensitive_data config."""
        config = OTelConfig.from_dict(
            {
                "sensitive_data": {
                    "filter_sensitive_data": False,
                    "filter_tool_parameters": True,
                    "filter_tool_results": False,
                }
            }
        )
        assert config.sensitive_data.filter_sensitive_data is False
        assert config.sensitive_data.filter_tool_parameters is True
        assert config.sensitive_data.filter_tool_results is False

    def test_legacy_flat_sensitive_data_config(self):
        """Should support legacy flat config for sensitive data."""
        config = OTelConfig.from_dict(
            {
                "filter_sensitive_data": False,
                "filter_tool_parameters": True,
            }
        )
        assert config.sensitive_data.filter_sensitive_data is False
        assert config.sensitive_data.filter_tool_parameters is True

    def test_full_config_with_sensitive_data(self):
        """Full config including sensitive_data should work."""
        config = OTelConfig.from_dict(
            {
                "enabled": True,
                "exporter": "otlp-http",
                "endpoint": "http://collector:4318",
                "sensitive_data": {
                    "filter_sensitive_data": True,
                    "filter_llm_content": True,
                    "filter_user_input": True,
                    "filter_tool_parameters": True,
                    "filter_tool_results": True,
                    "filter_error_messages": False,  # Allow error messages
                },
            }
        )
        assert config.exporter == "otlp-http"
        assert config.sensitive_data.filter_sensitive_data is True
        assert config.sensitive_data.filter_error_messages is False


class TestSpanManagerSensitiveDataFiltering:
    """Tests for SpanManager with sensitive data filtering."""

    @pytest.fixture
    def config_filtering_enabled(self):
        """Config with filtering enabled (default)."""
        return OTelConfig()

    @pytest.fixture
    def config_filtering_disabled(self):
        """Config with filtering disabled."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = False
        return config

    @pytest.fixture
    def span_manager_filtered(self, tracer, config_filtering_enabled):
        """SpanManager with filtering enabled."""
        return SpanManager(tracer, config_filtering_enabled)

    @pytest.fixture
    def span_manager_unfiltered(self, tracer, config_filtering_disabled):
        """SpanManager with filtering disabled."""
        return SpanManager(tracer, config_filtering_disabled)

    def test_tool_input_filtered_when_enabled(self, span_manager_filtered, span_exporter):
        """Tool input should be filtered when filtering is enabled."""
        span_manager_filtered.start_session_span("session-1", {})
        span_manager_filtered.start_turn_span("session-1")

        sensitive_input = {"password": "secret123", "api_key": "sk-xxx"}
        span_manager_filtered.start_tool_span("session-1", "bash", tool_input=sensitive_input)
        span_manager_filtered.end_tool_span("session-1", "bash")
        span_manager_filtered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Input should be filtered
        assert tool_span.attributes.get("tool.input") == FILTERED_PLACEHOLDER
        assert tool_span.attributes.get("tool.has_input") is True
        # Tool name should still be present
        assert tool_span.attributes.get("tool.name") == "bash"

    def test_tool_input_captured_when_disabled(self, span_manager_unfiltered, span_exporter):
        """Tool input should be captured when filtering is disabled."""
        span_manager_unfiltered.start_session_span("session-1", {})
        span_manager_unfiltered.start_turn_span("session-1")

        sensitive_input = {"password": "secret123"}
        span_manager_unfiltered.start_tool_span("session-1", "bash", tool_input=sensitive_input)
        span_manager_unfiltered.end_tool_span("session-1", "bash")
        span_manager_unfiltered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Input should be captured (stringified)
        assert "password" in str(tool_span.attributes.get("tool.input"))
        assert "secret123" in str(tool_span.attributes.get("tool.input"))

    def test_tool_result_filtered_when_enabled(self, span_manager_filtered, span_exporter):
        """Tool result should be filtered when filtering is enabled."""
        span_manager_filtered.start_session_span("session-1", {})
        span_manager_filtered.start_turn_span("session-1")

        span_manager_filtered.start_tool_span("session-1", "read_file")
        sensitive_result = "Contents of /etc/passwd: root:x:0:0..."
        span_manager_filtered.end_tool_span("session-1", "read_file", result=sensitive_result)
        span_manager_filtered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Result should be filtered
        assert tool_span.attributes.get("tool.result") == FILTERED_PLACEHOLDER
        assert tool_span.attributes.get("tool.has_result") is True
        # Success status should still be present
        assert tool_span.attributes.get("tool.success") is True

    def test_tool_result_captured_when_disabled(self, span_manager_unfiltered, span_exporter):
        """Tool result should be captured when filtering is disabled."""
        span_manager_unfiltered.start_session_span("session-1", {})
        span_manager_unfiltered.start_turn_span("session-1")

        span_manager_unfiltered.start_tool_span("session-1", "read_file")
        sensitive_result = "Contents of file"
        span_manager_unfiltered.end_tool_span("session-1", "read_file", result=sensitive_result)
        span_manager_unfiltered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Result should be captured
        assert tool_span.attributes.get("tool.result") == "Contents of file"

    def test_error_message_filtered_when_enabled(self, span_manager_filtered, span_exporter):
        """Error messages should be filtered when filtering is enabled."""
        span_manager_filtered.start_session_span("session-1", {})
        span_manager_filtered.start_turn_span("session-1")

        span_manager_filtered.start_tool_span("session-1", "bash")
        sensitive_error = "Failed to connect with password: secret123"
        span_manager_filtered.end_tool_span(
            "session-1", "bash", success=False, error=sensitive_error
        )
        span_manager_filtered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Error status should be ERROR but message filtered
        assert tool_span.status.status_code == StatusCode.ERROR
        assert tool_span.status.description == FILTERED_PLACEHOLDER
        assert "secret123" not in str(tool_span.status.description)

    def test_error_message_captured_when_disabled(self, span_manager_unfiltered, span_exporter):
        """Error messages should be captured when filtering is disabled."""
        span_manager_unfiltered.start_session_span("session-1", {})
        span_manager_unfiltered.start_turn_span("session-1")

        span_manager_unfiltered.start_tool_span("session-1", "bash")
        error_msg = "Command failed: permission denied"
        span_manager_unfiltered.end_tool_span("session-1", "bash", success=False, error=error_msg)
        span_manager_unfiltered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Error message should be captured
        assert tool_span.status.status_code == StatusCode.ERROR
        assert tool_span.status.description == error_msg

    def test_tool_name_always_captured(self, span_manager_filtered, span_exporter):
        """Tool name should always be captured regardless of filtering."""
        span_manager_filtered.start_session_span("session-1", {})
        span_manager_filtered.start_turn_span("session-1")

        span_manager_filtered.start_tool_span(
            "session-1", "my_sensitive_tool", tool_input={"secret": "data"}
        )
        span_manager_filtered.end_tool_span("session-1", "my_sensitive_tool")
        span_manager_filtered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Tool name is safe metadata
        assert tool_span.attributes.get("tool.name") == "my_sensitive_tool"

    def test_success_status_always_captured(self, span_manager_filtered, span_exporter):
        """Success status should always be captured regardless of filtering."""
        span_manager_filtered.start_session_span("session-1", {})
        span_manager_filtered.start_turn_span("session-1")

        span_manager_filtered.start_tool_span("session-1", "tool")
        span_manager_filtered.end_tool_span("session-1", "tool", success=True)
        span_manager_filtered.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Success status is safe metadata
        assert tool_span.attributes.get("tool.success") is True


class TestSpanManagerNoConfig:
    """Tests for SpanManager with no config (defaults to safe filtering)."""

    @pytest.fixture
    def span_manager_no_config(self, tracer):
        """SpanManager with no config - should default to filtering."""
        return SpanManager(tracer, config=None)

    def test_defaults_to_filtering_without_config(self, span_manager_no_config, span_exporter):
        """Without config, SpanManager should default to filtering (safe)."""
        span_manager_no_config.start_session_span("session-1", {})
        span_manager_no_config.start_turn_span("session-1")

        span_manager_no_config.start_tool_span("session-1", "bash", tool_input={"secret": "data"})
        span_manager_no_config.end_tool_span("session-1", "bash", result="sensitive output")
        span_manager_no_config.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Should be filtered by default (safe)
        assert tool_span.attributes.get("tool.input") == FILTERED_PLACEHOLDER
        assert tool_span.attributes.get("tool.result") == FILTERED_PLACEHOLDER

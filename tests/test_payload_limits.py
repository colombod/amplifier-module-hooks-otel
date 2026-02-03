"""Tests for large payload handling and size limits."""

import pytest

from amplifier_module_hooks_otel.config import (
    OTelConfig,
    PayloadLimitsConfig,
)
from amplifier_module_hooks_otel.spans import SpanManager


class TestPayloadLimitsConfig:
    """Tests for PayloadLimitsConfig defaults and behavior."""

    def test_defaults_drop_enabled(self):
        """By default, large payload dropping should be enabled."""
        config = PayloadLimitsConfig()
        assert config.drop_large_payloads is True
        assert config.max_payload_size == 10240  # 10KB
        assert config.max_llm_content_size == 5120  # 5KB
        assert config.max_tool_payload_size == 5120  # 5KB
        assert config.max_error_size == 2048  # 2KB
        assert config.include_size_metadata is True

    def test_can_disable_dropping(self):
        """Dropping can be disabled (will truncate instead)."""
        config = PayloadLimitsConfig(drop_large_payloads=False)
        assert config.drop_large_payloads is False

    def test_custom_limits(self):
        """Custom size limits can be set."""
        config = PayloadLimitsConfig(
            max_payload_size=20480,  # 20KB
            max_llm_content_size=10240,  # 10KB
            max_tool_payload_size=8192,  # 8KB
            max_error_size=4096,  # 4KB
        )
        assert config.max_payload_size == 20480
        assert config.max_llm_content_size == 10240
        assert config.max_tool_payload_size == 8192
        assert config.max_error_size == 4096


class TestOTelConfigPayloadLimits:
    """Tests for OTelConfig payload limit methods."""

    def test_get_payload_limit_default(self):
        """get_payload_limit returns correct defaults."""
        config = OTelConfig()
        assert config.get_payload_limit("llm_content") == 5120
        assert config.get_payload_limit("tool_payload") == 5120
        assert config.get_payload_limit("error") == 2048
        assert config.get_payload_limit("default") == 10240
        assert config.get_payload_limit("unknown") == 10240  # Falls back to default

    def test_process_payload_small_content(self):
        """Small payloads pass through unchanged."""
        config = OTelConfig()
        content = "small content"
        processed, metadata = config.process_payload(content, "default")
        assert processed == content
        assert metadata == {}

    def test_process_payload_empty_content(self):
        """Empty payloads pass through unchanged."""
        config = OTelConfig()
        processed, metadata = config.process_payload("", "default")
        assert processed == ""
        assert metadata == {}

    def test_process_payload_drop_large(self):
        """Large payloads are dropped when drop_large_payloads=True."""
        config = OTelConfig()
        config.payload_limits.max_payload_size = 100  # Small limit for testing

        large_content = "x" * 200  # Exceeds limit
        processed, metadata = config.process_payload(large_content, "default")

        # Should be replaced with placeholder
        assert "[PAYLOAD_DROPPED:" in processed
        assert "size=200" in processed
        assert "limit=100" in processed

        # Metadata should include size info
        assert metadata["payload.original_size"] == 200
        assert metadata["payload.limit"] == 100
        assert metadata["payload.truncated"] is True

    def test_process_payload_truncate_large(self):
        """Large payloads are truncated when drop_large_payloads=False."""
        config = OTelConfig()
        config.payload_limits.drop_large_payloads = False
        config.payload_limits.max_payload_size = 100  # Small limit for testing

        large_content = "x" * 200  # Exceeds limit
        processed, metadata = config.process_payload(large_content, "default")

        # Should be truncated, not dropped
        assert "[TRUNCATED:" in processed
        assert processed.startswith("x")  # Original content preserved at start

        # Metadata should include size info
        assert metadata["payload.original_size"] == 200
        assert metadata["payload.truncated"] is True

    def test_process_payload_no_metadata(self):
        """Metadata can be disabled."""
        config = OTelConfig()
        config.payload_limits.include_size_metadata = False
        config.payload_limits.max_payload_size = 100

        large_content = "x" * 200
        processed, metadata = config.process_payload(large_content, "default")

        # Should still drop but no metadata
        assert "[PAYLOAD_DROPPED:" in processed
        assert metadata == {}

    def test_process_payload_type_specific_limits(self):
        """Different payload types use their specific limits."""
        config = OTelConfig()
        config.payload_limits.max_llm_content_size = 50
        config.payload_limits.max_tool_payload_size = 100
        config.payload_limits.max_error_size = 30

        content = "x" * 75  # Between llm and tool limits

        # LLM content should be dropped (75 > 50)
        processed, _ = config.process_payload(content, "llm_content")
        assert "[PAYLOAD_DROPPED:" in processed

        # Tool payload should pass (75 < 100)
        processed, _ = config.process_payload(content, "tool_payload")
        assert processed == content

        # Error should be dropped (75 > 30)
        processed, _ = config.process_payload(content, "error")
        assert "[PAYLOAD_DROPPED:" in processed


class TestOTelConfigFromDictPayloadLimits:
    """Tests for OTelConfig.from_dict() with payload_limits section."""

    def test_default_payload_limits_config(self):
        """Default config should have dropping enabled."""
        config = OTelConfig.from_dict({})
        assert config.payload_limits.drop_large_payloads is True

    def test_nested_payload_limits_config(self):
        """Should parse nested payload_limits config."""
        config = OTelConfig.from_dict(
            {
                "payload_limits": {
                    "drop_large_payloads": False,
                    "max_payload_size": 20480,
                    "max_llm_content_size": 10240,
                }
            }
        )
        assert config.payload_limits.drop_large_payloads is False
        assert config.payload_limits.max_payload_size == 20480
        assert config.payload_limits.max_llm_content_size == 10240

    def test_legacy_flat_payload_limits_config(self):
        """Should support legacy flat config for payload limits."""
        config = OTelConfig.from_dict(
            {
                "drop_large_payloads": False,
                "max_payload_size": 20480,
            }
        )
        assert config.payload_limits.drop_large_payloads is False
        assert config.payload_limits.max_payload_size == 20480

    def test_full_config_with_payload_limits(self):
        """Full config including payload_limits should work."""
        config = OTelConfig.from_dict(
            {
                "enabled": True,
                "exporter": "otlp-http",
                "endpoint": "http://collector:4318",
                "sensitive_data": {
                    "filter_sensitive_data": True,
                },
                "payload_limits": {
                    "drop_large_payloads": True,
                    "max_payload_size": 15000,
                    "max_llm_content_size": 8000,
                    "max_tool_payload_size": 6000,
                    "max_error_size": 3000,
                    "include_size_metadata": True,
                },
            }
        )
        assert config.exporter == "otlp-http"
        assert config.sensitive_data.filter_sensitive_data is True
        assert config.payload_limits.drop_large_payloads is True
        assert config.payload_limits.max_payload_size == 15000
        assert config.payload_limits.max_llm_content_size == 8000


class TestSpanManagerPayloadHandling:
    """Tests for SpanManager with payload size limits."""

    @pytest.fixture
    def config_with_small_limits(self):
        """Config with small payload limits for testing."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = False  # Allow content
        config.payload_limits.max_tool_payload_size = 100  # Small limit
        config.payload_limits.drop_large_payloads = True
        return config

    @pytest.fixture
    def config_truncate_mode(self):
        """Config that truncates instead of drops."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = False  # Allow content
        config.payload_limits.max_tool_payload_size = 100  # Small limit
        config.payload_limits.drop_large_payloads = False  # Truncate mode
        return config

    @pytest.fixture
    def span_manager_drop(self, tracer, config_with_small_limits):
        """SpanManager with small limits and drop mode."""
        return SpanManager(tracer, config_with_small_limits)

    @pytest.fixture
    def span_manager_truncate(self, tracer, config_truncate_mode):
        """SpanManager with small limits and truncate mode."""
        return SpanManager(tracer, config_truncate_mode)

    def test_small_tool_input_passes_through(self, span_manager_drop, span_exporter):
        """Small tool inputs pass through unchanged."""
        span_manager_drop.start_session_span("session-1", {})
        span_manager_drop.start_turn_span("session-1")

        small_input = {"key": "small value"}
        span_manager_drop.start_tool_span("session-1", "test_tool", tool_input=small_input)
        span_manager_drop.end_tool_span("session-1", "test_tool")
        span_manager_drop.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Small input should be captured
        assert "small value" in str(tool_span.attributes.get("tool.input"))

    def test_large_tool_input_dropped(self, span_manager_drop, span_exporter):
        """Large tool inputs are dropped when exceeding limit."""
        span_manager_drop.start_session_span("session-1", {})
        span_manager_drop.start_turn_span("session-1")

        large_input = {"data": "x" * 200}  # Exceeds 100 byte limit
        span_manager_drop.start_tool_span("session-1", "test_tool", tool_input=large_input)
        span_manager_drop.end_tool_span("session-1", "test_tool")
        span_manager_drop.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Input should be dropped/replaced
        tool_input = tool_span.attributes.get("tool.input")
        assert "[PAYLOAD_DROPPED:" in str(tool_input)
        # Size metadata should be present
        assert tool_span.attributes.get("tool.input.original_size") is not None

    def test_large_tool_input_truncated(self, span_manager_truncate, span_exporter):
        """Large tool inputs are truncated in truncate mode."""
        span_manager_truncate.start_session_span("session-1", {})
        span_manager_truncate.start_turn_span("session-1")

        large_input = {"data": "x" * 200}
        span_manager_truncate.start_tool_span("session-1", "test_tool", tool_input=large_input)
        span_manager_truncate.end_tool_span("session-1", "test_tool")
        span_manager_truncate.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Input should be truncated, not dropped
        tool_input = str(tool_span.attributes.get("tool.input"))
        assert "[TRUNCATED:" in tool_input
        assert "data" in tool_input  # Original content partially preserved

    def test_large_tool_result_dropped(self, span_manager_drop, span_exporter):
        """Large tool results are dropped when exceeding limit."""
        span_manager_drop.start_session_span("session-1", {})
        span_manager_drop.start_turn_span("session-1")

        span_manager_drop.start_tool_span("session-1", "test_tool")
        large_result = "x" * 200  # Exceeds limit
        span_manager_drop.end_tool_span("session-1", "test_tool", result=large_result)
        span_manager_drop.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Result should be dropped
        tool_result = tool_span.attributes.get("tool.result")
        assert "[PAYLOAD_DROPPED:" in str(tool_result)

    def test_large_error_message_dropped(self, span_manager_drop, span_exporter):
        """Large error messages are dropped when exceeding limit."""
        # Error limit is 2048 by default, let's use a custom smaller one
        span_manager_drop._config.payload_limits.max_error_size = 50

        span_manager_drop.start_session_span("session-1", {})
        span_manager_drop.start_turn_span("session-1")

        span_manager_drop.start_tool_span("session-1", "test_tool")
        large_error = "Error: " + "x" * 100  # Exceeds 50 byte limit
        span_manager_drop.end_tool_span("session-1", "test_tool", success=False, error=large_error)
        span_manager_drop.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Error should be processed (dropped or truncated)
        error_desc = tool_span.status.description
        assert "[PAYLOAD_DROPPED:" in error_desc or "[TRUNCATED:" in error_desc


class TestSpanManagerNoConfigPayload:
    """Tests for SpanManager payload handling with no config."""

    @pytest.fixture
    def span_manager_no_config(self, tracer):
        """SpanManager with no config - should use basic truncation."""
        return SpanManager(tracer, config=None)

    def test_large_payload_basic_truncation(self, span_manager_no_config, span_exporter):
        """Without config, large payloads get basic truncation."""
        span_manager_no_config.start_session_span("session-1", {})
        span_manager_no_config.start_turn_span("session-1")

        # Default truncation is 1000 chars when no config
        large_input = "x" * 2000
        span_manager_no_config.start_tool_span("session-1", "test_tool", tool_input=large_input)
        span_manager_no_config.end_tool_span("session-1", "test_tool")
        span_manager_no_config.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Should be filtered by default (no config = filter sensitive data)
        # If we had filtering disabled, we'd see truncation
        tool_input = tool_span.attributes.get("tool.input")
        assert tool_input == "[FILTERED]"  # Default is to filter


class TestPayloadLimitsIntegration:
    """Integration tests for payload limits with sensitive data filtering."""

    def test_sensitive_filter_takes_precedence(self, tracer, span_exporter):
        """When sensitive filtering is ON, payload limits don't matter."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = True  # Filter ON
        config.payload_limits.max_tool_payload_size = 10000  # Large limit

        span_manager = SpanManager(tracer, config)
        span_manager.start_session_span("session-1", {})
        span_manager.start_turn_span("session-1")

        # Even though payload is small and within limits, it's filtered
        small_input = {"secret": "small secret data"}
        span_manager.start_tool_span("session-1", "test_tool", tool_input=small_input)
        span_manager.end_tool_span("session-1", "test_tool")
        span_manager.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Should be filtered, not the actual content
        assert tool_span.attributes.get("tool.input") == "[FILTERED]"

    def test_payload_limits_when_filter_disabled(self, tracer, span_exporter):
        """Payload limits apply when sensitive filtering is OFF."""
        config = OTelConfig()
        config.sensitive_data.filter_sensitive_data = False  # Filter OFF
        config.payload_limits.max_tool_payload_size = 50  # Small limit

        span_manager = SpanManager(tracer, config)
        span_manager.start_session_span("session-1", {})
        span_manager.start_turn_span("session-1")

        # Large payload should be dropped
        large_input = {"data": "x" * 100}
        span_manager.start_tool_span("session-1", "test_tool", tool_input=large_input)
        span_manager.end_tool_span("session-1", "test_tool")
        span_manager.end_session_span("session-1")

        spans = span_exporter.get_finished_spans()
        tool_span = next(s for s in spans if s.name == "amplifier.tool")

        # Should be dropped due to payload limits
        tool_input = str(tool_span.attributes.get("tool.input"))
        assert "[PAYLOAD_DROPPED:" in tool_input

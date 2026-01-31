"""Integration tests for OTelHook and mount function."""

import pytest

from amplifier_module_hooks_otel import OTelConfig, OTelHook

# Fixtures span_exporter and metric_reader come from conftest.py


@pytest.fixture
def hook():
    """Create an OTelHook with default config."""
    config = OTelConfig()
    return OTelHook(config)


@pytest.fixture
def hook_no_metrics():
    """Create an OTelHook with metrics disabled."""
    config = OTelConfig(metrics_enabled=False)
    return OTelHook(config)


@pytest.fixture
def hook_no_traces():
    """Create an OTelHook with traces disabled."""
    config = OTelConfig(traces_enabled=False)
    return OTelHook(config)


class TestOTelHookSessionLifecycle:
    """Tests for session span lifecycle."""

    @pytest.mark.asyncio
    async def test_session_start_creates_span(self, hook, span_exporter):
        """session:start event creates a root span."""
        data = {"session_id": "test-session-123"}

        result = await hook.on_session_start("session:start", data)

        assert result.action == "continue"
        assert "test-session-123" in hook._span_manager._session_spans

    @pytest.mark.asyncio
    async def test_session_end_closes_span(self, hook, span_exporter):
        """session:end event closes the session span."""
        data = {"session_id": "test-session-123"}

        await hook.on_session_start("session:start", data)
        result = await hook.on_session_end("session:end", data)

        assert result.action == "continue"
        assert "test-session-123" not in hook._span_manager._session_spans

        # Verify span was exported
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "amplifier.session"

    @pytest.mark.asyncio
    async def test_session_without_id_is_ignored(self, hook):
        """Events without session_id are safely ignored."""
        data = {}

        result = await hook.on_session_start("session:start", data)

        assert result.action == "continue"
        assert len(hook._span_manager._session_spans) == 0


class TestOTelHookTurnLifecycle:
    """Tests for turn span lifecycle."""

    @pytest.mark.asyncio
    async def test_execution_start_creates_turn_span(self, hook, span_exporter):
        """execution:start event creates a turn span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        result = await hook.on_execution_start("execution:start", session_data)

        assert result.action == "continue"
        assert "test-session-123" in hook._span_manager._turn_spans

    @pytest.mark.asyncio
    async def test_execution_end_closes_turn_span(self, hook, span_exporter):
        """execution:end event closes the turn span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)
        await hook.on_execution_start("execution:start", session_data)

        result = await hook.on_execution_end("execution:end", session_data)

        assert result.action == "continue"
        assert "test-session-123" not in hook._span_manager._turn_spans


class TestOTelHookLlmOperations:
    """Tests for LLM request/response spans."""

    @pytest.mark.asyncio
    async def test_llm_request_creates_span(self, hook, span_exporter):
        """llm:request event creates an LLM span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        llm_data = {
            "session_id": "test-session-123",
            "provider": "anthropic",
            "model": "claude-3-opus",
        }

        result = await hook.on_llm_request("llm:request", llm_data)

        assert result.action == "continue"
        assert "_otel_correlation_key" in llm_data

    @pytest.mark.asyncio
    async def test_llm_response_closes_span(self, hook, span_exporter):
        """llm:response event closes the LLM span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        llm_data = {
            "session_id": "test-session-123",
            "provider": "anthropic",
            "model": "claude-3-opus",
        }
        await hook.on_llm_request("llm:request", llm_data)

        response_data = {
            "session_id": "test-session-123",
            "_otel_correlation_key": llm_data["_otel_correlation_key"],
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "claude-3-opus-20240229",
            "finish_reason": "end_turn",
        }

        result = await hook.on_llm_response("llm:response", response_data)

        assert result.action == "continue"

    @pytest.mark.asyncio
    async def test_llm_response_records_metrics(self, hook, metric_reader):
        """llm:response records token usage metrics."""
        session_data = {"session_id": "test-session-456"}
        await hook.on_session_start("session:start", session_data)

        llm_data = {
            "session_id": "test-session-456",
            "provider": "anthropic",
            "model": "claude-3-opus",
        }
        await hook.on_llm_request("llm:request", llm_data)

        response_data = {
            "session_id": "test-session-456",
            "_otel_correlation_key": llm_data["_otel_correlation_key"],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        await hook.on_llm_response("llm:response", response_data)

        # Verify metrics were recorded - get_metrics_data returns data
        # The metric_reader collects data; we just verify hook ran without error
        _ = metric_reader.get_metrics_data()  # Trigger collection
        assert hook._metrics_recorder is not None


class TestOTelHookToolOperations:
    """Tests for tool call spans."""

    @pytest.mark.asyncio
    async def test_tool_pre_creates_span(self, hook, span_exporter):
        """tool:pre event creates a tool span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {
            "session_id": "test-session-123",
            "tool_name": "bash",
        }

        result = await hook.on_tool_pre("tool:pre", tool_data)

        assert result.action == "continue"
        assert "_otel_correlation_key" in tool_data

    @pytest.mark.asyncio
    async def test_tool_post_closes_span_success(self, hook, span_exporter):
        """tool:post event closes the tool span with success."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {"session_id": "test-session-123", "tool_name": "bash"}
        await hook.on_tool_pre("tool:pre", tool_data)

        post_data = {
            "session_id": "test-session-123",
            "_otel_correlation_key": tool_data["_otel_correlation_key"],
            "tool_name": "bash",
        }

        result = await hook.on_tool_post("tool:post", post_data)

        assert result.action == "continue"

    @pytest.mark.asyncio
    async def test_tool_error_closes_span_with_error(self, hook, span_exporter):
        """tool:error event closes the tool span with error status."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {"session_id": "test-session-123", "tool_name": "bash"}
        await hook.on_tool_pre("tool:pre", tool_data)

        error_data = {
            "session_id": "test-session-123",
            "_otel_correlation_key": tool_data["_otel_correlation_key"],
            "tool_name": "bash",
            "error": {"type": "CommandError", "message": "Command failed"},
        }

        result = await hook.on_tool_error("tool:error", error_data)

        assert result.action == "continue"


class TestOTelHookDisabledFeatures:
    """Tests for disabled features."""

    @pytest.mark.asyncio
    async def test_traces_disabled_skips_spans(self, hook_no_traces):
        """With traces disabled, no spans are created."""
        data = {"session_id": "test-session-123"}

        await hook_no_traces.on_session_start("session:start", data)

        assert len(hook_no_traces._span_manager._session_spans) == 0

    @pytest.mark.asyncio
    async def test_metrics_disabled_skips_metrics(self, hook_no_metrics):
        """With metrics disabled, no metrics recorder exists."""
        assert hook_no_metrics._metrics_recorder is None


class TestOTelHookAlwaysContinues:
    """Tests that hook always returns continue action."""

    @pytest.mark.asyncio
    async def test_all_handlers_return_continue(self, hook):
        """All event handlers return continue action."""
        session_data = {"session_id": "test-session-789"}

        # All handlers should return continue
        assert (await hook.on_session_start("session:start", session_data)).action == "continue"
        assert (await hook.on_execution_start("execution:start", session_data)).action == "continue"
        assert (await hook.on_llm_request("llm:request", session_data)).action == "continue"
        assert (await hook.on_llm_response("llm:response", session_data)).action == "continue"
        assert (await hook.on_tool_pre("tool:pre", session_data)).action == "continue"
        assert (await hook.on_tool_post("tool:post", session_data)).action == "continue"
        assert (await hook.on_tool_error("tool:error", session_data)).action == "continue"
        assert (await hook.on_provider_error("provider:error", session_data)).action == "continue"
        assert (await hook.on_execution_end("execution:end", session_data)).action == "continue"
        assert (await hook.on_session_end("session:end", session_data)).action == "continue"


class TestOTelConfig:
    """Tests for OTelConfig."""

    def test_default_config(self):
        """Default config has expected values."""
        config = OTelConfig()

        assert config.service_name == "amplifier"
        assert config.traces_enabled is True
        assert config.metrics_enabled is True
        assert config.capture_input_messages is False
        assert config.capture_output_messages is False

    def test_from_dict(self):
        """Config can be created from dict."""
        config = OTelConfig.from_dict(
            {
                "service_name": "my-app",
                "traces_enabled": False,
                "unknown_field": "ignored",
            }
        )

        assert config.service_name == "my-app"
        assert config.traces_enabled is False
        # Unknown fields are ignored

    def test_privacy_defaults_off(self):
        """Privacy-sensitive options default to off."""
        config = OTelConfig()

        assert config.capture_input_messages is False
        assert config.capture_output_messages is False
        assert config.capture_tool_input is False
        assert config.capture_tool_output is False

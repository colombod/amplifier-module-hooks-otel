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
    config = OTelConfig.from_dict({"capture": {"traces": True, "metrics": False}})
    return OTelHook(config)


@pytest.fixture
def hook_no_traces():
    """Create an OTelHook with traces disabled."""
    config = OTelConfig.from_dict({"capture": {"traces": False, "metrics": True}})
    return OTelHook(config)


class TestOTelHookSessionLifecycle:
    """Tests for session span lifecycle."""

    @pytest.mark.asyncio
    async def test_session_start_creates_span(self, hook, span_exporter):
        """session:start event creates a root span."""
        data = {"session_id": "test-session-123"}

        result = await hook.on_session_start("session:start", data)

        assert result.action == "continue"
        assert hook._span_manager.get_session_span("test-session-123") is not None

    @pytest.mark.asyncio
    async def test_session_end_closes_span(self, hook, span_exporter):
        """session:end event closes the session span."""
        data = {"session_id": "test-session-123"}

        await hook.on_session_start("session:start", data)
        result = await hook.on_session_end("session:end", data)

        assert result.action == "continue"
        assert hook._span_manager.get_session_span("test-session-123") is None

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
        assert len(hook._span_manager._sessions) == 0


class TestOTelHookTurnLifecycle:
    """Tests for turn span lifecycle."""

    @pytest.mark.asyncio
    async def test_execution_start_creates_turn_span(self, hook, span_exporter):
        """execution:start event creates a turn span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        result = await hook.on_execution_start("execution:start", session_data)

        assert result.action == "continue"
        ctx = hook._span_manager._sessions.get("test-session-123")
        assert ctx is not None
        assert ctx.current_turn is not None

    @pytest.mark.asyncio
    async def test_execution_end_closes_turn_span(self, hook, span_exporter):
        """execution:end event closes the turn span."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)
        await hook.on_execution_start("execution:start", session_data)

        result = await hook.on_execution_end("execution:end", session_data)

        assert result.action == "continue"
        ctx = hook._span_manager._sessions.get("test-session-123")
        assert ctx is not None
        assert ctx.current_turn is None


class TestOTelHookLlmOperations:
    """Tests for LLM request/response spans."""

    @pytest.mark.asyncio
    async def test_llm_request_creates_span(self, hook, span_exporter):
        """llm:request event creates an LLM span and tracks correlation internally."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        llm_data = {
            "session_id": "test-session-123",
            "provider": "anthropic",
            "model": "claude-3-opus",
        }

        result = await hook.on_llm_request("llm:request", llm_data)

        assert result.action == "continue"
        # Verify internal correlation tracking (not event mutation)
        assert "test-session-123" in hook._pending_llm
        # Verify event data was NOT mutated
        assert "_otel_correlation_key" not in llm_data

    @pytest.mark.asyncio
    async def test_llm_response_closes_span(self, hook, span_exporter):
        """llm:response event closes the LLM span using internal correlation."""
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
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "claude-3-opus-20240229",
            "finish_reason": "end_turn",
        }

        result = await hook.on_llm_response("llm:response", response_data)

        assert result.action == "continue"
        # Verify correlation was consumed
        assert "test-session-123" not in hook._pending_llm

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
        """tool:pre event creates a tool span and tracks correlation internally."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {
            "session_id": "test-session-123",
            "tool_name": "bash",
        }

        result = await hook.on_tool_pre("tool:pre", tool_data)

        assert result.action == "continue"
        # Verify internal correlation tracking (not event mutation)
        assert "test-session-123" in hook._pending_tools
        # Verify event data was NOT mutated
        assert "_otel_correlation_key" not in tool_data

    @pytest.mark.asyncio
    async def test_tool_post_closes_span_success(self, hook, span_exporter):
        """tool:post event closes the tool span with success using internal correlation."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {"session_id": "test-session-123", "tool_name": "bash"}
        await hook.on_tool_pre("tool:pre", tool_data)

        post_data = {
            "session_id": "test-session-123",
            "tool_name": "bash",
        }

        result = await hook.on_tool_post("tool:post", post_data)

        assert result.action == "continue"
        # Verify correlation was consumed
        assert "test-session-123" not in hook._pending_tools

    @pytest.mark.asyncio
    async def test_tool_error_closes_span_with_error(self, hook, span_exporter):
        """tool:error event closes the tool span with error status."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {"session_id": "test-session-123", "tool_name": "bash"}
        await hook.on_tool_pre("tool:pre", tool_data)

        error_data = {
            "session_id": "test-session-123",
            "tool_name": "bash",
            "error": {"type": "CommandError", "message": "Command failed"},
        }

        result = await hook.on_tool_error("tool:error", error_data)

        assert result.action == "continue"
        # Verify correlation was consumed
        assert "test-session-123" not in hook._pending_tools


class TestOTelHookDisabledFeatures:
    """Tests for disabled features."""

    @pytest.mark.asyncio
    async def test_traces_disabled_skips_spans(self, hook_no_traces):
        """With traces disabled, no spans are created."""
        data = {"session_id": "test-session-123"}

        await hook_no_traces.on_session_start("session:start", data)

        assert len(hook_no_traces._span_manager._sessions) == 0

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


class TestOTelHookDoesNotMutateEventData:
    """Tests that hook never mutates event data (purely observational)."""

    @pytest.mark.asyncio
    async def test_llm_request_does_not_mutate_data(self, hook):
        """llm:request handler does not mutate the event data dict."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        llm_data = {
            "session_id": "test-session-123",
            "provider": "anthropic",
            "model": "claude-3-opus",
        }
        original_keys = set(llm_data.keys())

        await hook.on_llm_request("llm:request", llm_data)

        # Event data should have the same keys
        assert set(llm_data.keys()) == original_keys

    @pytest.mark.asyncio
    async def test_tool_pre_does_not_mutate_data(self, hook):
        """tool:pre handler does not mutate the event data dict."""
        session_data = {"session_id": "test-session-123"}
        await hook.on_session_start("session:start", session_data)

        tool_data = {
            "session_id": "test-session-123",
            "tool_name": "bash",
        }
        original_keys = set(tool_data.keys())

        await hook.on_tool_pre("tool:pre", tool_data)

        # Event data should have the same keys
        assert set(tool_data.keys()) == original_keys


class TestOTelHookOptOut:
    """Tests for opt-out functionality."""

    @pytest.fixture
    def hook_disabled(self):
        """Create an OTelHook with enabled=False (opt-out)."""
        config = OTelConfig(enabled=False)
        return OTelHook(config)

    @pytest.mark.asyncio
    async def test_disabled_hook_creates_no_spans(self, hook_disabled, span_exporter):
        """When disabled, no spans are created."""
        data = {"session_id": "test-session-123"}

        await hook_disabled.on_session_start("session:start", data)
        await hook_disabled.on_session_end("session:end", data)

        # No spans should be exported
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 0

    @pytest.mark.asyncio
    async def test_disabled_hook_still_returns_continue(self, hook_disabled):
        """Disabled hook still returns continue (doesn't block)."""
        data = {"session_id": "test-session-123"}

        result = await hook_disabled.on_session_start("session:start", data)
        assert result.action == "continue"

        result = await hook_disabled.on_llm_request("llm:request", data)
        assert result.action == "continue"

    def test_disabled_hook_has_no_span_manager(self, hook_disabled):
        """Disabled hook doesn't initialize span manager."""
        assert hook_disabled._span_manager is None
        assert hook_disabled._metrics_recorder is None


class TestOTelConfig:
    """Tests for OTelConfig."""

    def test_default_config(self):
        """Default config has expected values."""
        config = OTelConfig()

        assert config.enabled is True
        assert config.traces_enabled is True
        assert config.metrics_enabled is True

    def test_from_dict(self):
        """Config can be created from dict."""
        config = OTelConfig.from_dict(
            {
                "traces_enabled": False,
                "unknown_field": "ignored",
            }
        )

        assert config.traces_enabled is False
        # Unknown fields are ignored

    def test_from_dict_with_metrics_disabled(self):
        """Config can disable metrics."""
        config = OTelConfig.from_dict({"metrics_enabled": False})

        assert config.traces_enabled is True
        assert config.metrics_enabled is False

    def test_from_dict_with_enabled_false(self):
        """Config can be disabled via enabled=False."""
        config = OTelConfig.from_dict({"enabled": False})

        assert config.enabled is False

    def test_is_active_property(self):
        """is_active returns True only when enabled AND features active."""
        # Fully enabled
        config = OTelConfig.from_dict(
            {"enabled": True, "capture": {"traces": True, "metrics": True}}
        )
        assert config.is_active is True

        # Disabled globally
        config = OTelConfig.from_dict(
            {"enabled": False, "capture": {"traces": True, "metrics": True}}
        )
        assert config.is_active is False

        # Enabled but no features
        config = OTelConfig.from_dict(
            {"enabled": True, "capture": {"traces": False, "metrics": False}}
        )
        assert config.is_active is False


class TestOTelConfigEnvVar:
    """Tests for environment variable opt-out."""

    def test_env_var_opt_out(self, monkeypatch):
        """AMPLIFIER_OTEL_OPT_OUT=1 disables telemetry."""
        monkeypatch.setenv("AMPLIFIER_OTEL_OPT_OUT", "1")

        # Need to reimport to pick up env var change
        from amplifier_module_hooks_otel.config import OTelConfig as FreshConfig

        config = FreshConfig()
        assert config.enabled is False

    def test_env_var_opt_out_true(self, monkeypatch):
        """AMPLIFIER_OTEL_OPT_OUT=true disables telemetry."""
        monkeypatch.setenv("AMPLIFIER_OTEL_OPT_OUT", "true")

        from amplifier_module_hooks_otel.config import OTelConfig as FreshConfig

        config = FreshConfig()
        assert config.enabled is False

    def test_env_var_not_set_enables(self, monkeypatch):
        """Without env var, telemetry is enabled."""
        monkeypatch.delenv("AMPLIFIER_OTEL_OPT_OUT", raising=False)

        from amplifier_module_hooks_otel.config import OTelConfig as FreshConfig

        config = FreshConfig()
        assert config.enabled is True

    def test_env_var_overrides_config(self, monkeypatch):
        """Env var opt-out overrides config enabled=True."""
        monkeypatch.setenv("AMPLIFIER_OTEL_OPT_OUT", "1")

        from amplifier_module_hooks_otel.config import OTelConfig as FreshConfig

        # Even if config says enabled=True, env var wins
        config = FreshConfig.from_dict({"enabled": True})
        assert config.enabled is False

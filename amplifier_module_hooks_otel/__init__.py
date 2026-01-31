"""
OpenTelemetry observability hook for Amplifier.

Translates kernel events to OTel spans and metrics following GenAI
semantic conventions.

This module observes Amplifier events without modifying them, emitting
OpenTelemetry traces and metrics for observability.

Usage:
    The module is mounted by Amplifier automatically when configured.
    OTel exporters should be configured at the application level.
"""

__amplifier_module_type__ = "hook"

import logging
from typing import Any

from amplifier_core import HookResult, ModuleCoordinator
from amplifier_core.events import (
    EXECUTION_END,
    EXECUTION_START,
    LLM_REQUEST,
    LLM_RESPONSE,
    PROVIDER_ERROR,
    SESSION_END,
    SESSION_START,
    TOOL_ERROR,
    TOOL_POST,
    TOOL_PRE,
)
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from .attributes import AttributeMapper
from .config import OTelConfig
from .metrics import MetricsRecorder
from .spans import SpanManager

logger = logging.getLogger(__name__)

# Events we observe for tracing
TRACED_EVENTS = [
    SESSION_START,
    SESSION_END,
    EXECUTION_START,
    EXECUTION_END,
    TOOL_PRE,
    TOOL_POST,
    TOOL_ERROR,
    LLM_REQUEST,
    LLM_RESPONSE,
    PROVIDER_ERROR,
]

# Public exports
__all__ = [
    "OTelHook",
    "OTelConfig",
    "SpanManager",
    "MetricsRecorder",
    "AttributeMapper",
    "mount",
    "TRACED_EVENTS",
]


class OTelHook:
    """OpenTelemetry hook that observes Amplifier events.

    This hook creates trace spans and records metrics for Amplifier
    kernel events without modifying them. It always returns
    HookResult(action="continue") as it is purely observational.
    """

    def __init__(self, config: OTelConfig) -> None:
        """Initialize OTelHook with configuration.

        Args:
            config: OTelConfig instance with settings.
        """
        self.config = config

        # If globally disabled (opt-out), don't initialize anything
        if not config.enabled:
            logger.info("OTel hook disabled (opt-out active)")
            self._tracer = None
            self._meter = None
            self._span_manager = None
            self._metrics_recorder = None
            self._pending_llm = {}
            self._pending_tools = {}
            return

        # Get tracer and meter from global providers (app configures these)
        self._tracer = trace.get_tracer(
            "amplifier.hooks.otel",
            schema_url="https://opentelemetry.io/schemas/1.21.0",
        )
        self._meter = otel_metrics.get_meter(
            "amplifier.hooks.otel",
            schema_url="https://opentelemetry.io/schemas/1.21.0",
        )

        self._span_manager = SpanManager(self._tracer)
        self._metrics_recorder = MetricsRecorder(self._meter) if config.metrics_enabled else None

        # Internal correlation tracking - avoids mutating event data
        # Maps (session_id, event_type) → correlation_key for pending operations
        self._pending_llm: dict[str, str] = {}  # session_id → correlation_key
        self._pending_tools: dict[str, str] = {}  # session_id → correlation_key

    async def on_session_start(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:start - create root span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        # Check global opt-out first, then feature-specific flag
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_session(data)
        self._span_manager.start_session_span(session_id, attrs)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_session_end(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:end - end root span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if session_id:
            self._span_manager.end_session_span(session_id)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_execution_start(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle execution:start - create turn span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if session_id:
            self._span_manager.start_turn_span(session_id)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_execution_end(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle execution:end - end turn span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if session_id:
            self._span_manager.end_turn_span(session_id)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_llm_request(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle llm:request - start LLM span.

        Args:
            event: Event name.
            data: Event data containing session_id, model, provider.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_llm_request(data)
        model = data.get("model", "unknown")
        correlation_key = f"llm:{session_id}:{id(data)}"

        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            f"chat {model}",
            SpanKind.CLIENT,
            attrs,
            correlation_key=correlation_key,
        )

        # Track timing for metrics
        if self._metrics_recorder:
            self._metrics_recorder.start_timing(correlation_key)

        # Store correlation key internally (don't mutate event data)
        self._pending_llm[session_id] = correlation_key

        return HookResult(action="continue")

    async def on_llm_response(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle llm:response - end LLM span and record metrics.

        Args:
            event: Event name.
            data: Event data containing usage, model, finish_reason.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")

        # Retrieve correlation key from internal tracking (don't read from event data)
        correlation_key = self._pending_llm.pop(session_id, None) if session_id else None

        if not correlation_key:
            return HookResult(action="continue")

        # Add response attributes to span
        span = self._span_manager.get_active_span(correlation_key)  # type: ignore[union-attr]
        if span:
            attrs = AttributeMapper.for_llm_response(data)
            for key, value in attrs.items():
                span.set_attribute(key, value)

        # End span
        self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        # Record metrics
        if self._metrics_recorder:
            usage = data.get("usage", {})
            metric_attrs = AttributeMapper.for_llm_request(data)

            self._metrics_recorder.record_duration(correlation_key, metric_attrs)
            self._metrics_recorder.record_token_usage(
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                metric_attrs,
            )

        return HookResult(action="continue")

    async def on_tool_pre(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle tool:pre - start tool span.

        Args:
            event: Event name.
            data: Event data containing session_id, tool_name.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        tool_name = data.get("tool_name", "unknown")

        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_tool(data)
        correlation_key = f"tool:{session_id}:{tool_name}:{id(data)}"

        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            f"execute_tool {tool_name}",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )

        if self._metrics_recorder:
            self._metrics_recorder.start_timing(correlation_key)

        # Store correlation key internally (don't mutate event data)
        self._pending_tools[session_id] = correlation_key

        return HookResult(action="continue")

    async def on_tool_post(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle tool:post - end tool span (success).

        Args:
            event: Event name.
            data: Event data containing correlation key.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_tools.pop(session_id, None) if session_id else None

        if correlation_key:
            self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

            if self._metrics_recorder:
                attrs = AttributeMapper.for_tool(data)
                self._metrics_recorder.record_duration(correlation_key, attrs)

        return HookResult(action="continue")

    async def on_tool_error(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle tool:error - end tool span with error status.

        Args:
            event: Event name.
            data: Event data containing error information.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_tools.pop(session_id, None) if session_id else None

        if correlation_key:
            # Add error attributes
            span = self._span_manager.get_active_span(correlation_key)  # type: ignore[union-attr]
            if span:
                error_attrs = AttributeMapper.for_error(data)
                for key, value in error_attrs.items():
                    span.set_attribute(key, value)

            error_data = data.get("error", {})
            error_msg = (
                error_data.get("message", "Tool error")
                if isinstance(error_data, dict)
                else "Tool error"
            )
            self._span_manager.end_child_span(correlation_key, StatusCode.ERROR, error_msg)  # type: ignore[union-attr]

            if self._metrics_recorder:
                attrs = AttributeMapper.for_tool(data)
                self._metrics_recorder.record_duration(correlation_key, attrs)

        return HookResult(action="continue")

    async def on_provider_error(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle provider:error - record error on LLM span if exists.

        Args:
            event: Event name.
            data: Event data containing error information.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        # Provider errors relate to LLM operations
        correlation_key = self._pending_llm.pop(session_id, None) if session_id else None

        if correlation_key:
            error_data = data.get("error", {})
            error_msg = (
                error_data.get("message", "Provider error")
                if isinstance(error_data, dict)
                else "Provider error"
            )
            self._span_manager.end_child_span(correlation_key, StatusCode.ERROR, error_msg)  # type: ignore[union-attr]

        return HookResult(action="continue")


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None) -> None:
    """Mount the OpenTelemetry hook module.

    Args:
        coordinator: ModuleCoordinator for registering hooks.
        config: Optional configuration dictionary.
    """
    config_dict = config or {}
    otel_config = OTelConfig.from_dict(config_dict)
    priority = int(config_dict.get("priority", 1000))  # Run after business hooks

    hook = OTelHook(otel_config)

    # Map events to handlers
    event_handlers = {
        SESSION_START: hook.on_session_start,
        SESSION_END: hook.on_session_end,
        EXECUTION_START: hook.on_execution_start,
        EXECUTION_END: hook.on_execution_end,
        LLM_REQUEST: hook.on_llm_request,
        LLM_RESPONSE: hook.on_llm_response,
        TOOL_PRE: hook.on_tool_pre,
        TOOL_POST: hook.on_tool_post,
        TOOL_ERROR: hook.on_tool_error,
        PROVIDER_ERROR: hook.on_provider_error,
    }

    # Register handlers
    for event, handler in event_handlers.items():
        coordinator.hooks.register(event, handler, priority=priority, name="hooks-otel")

    logger.info(
        f"Mounted hooks-otel (traces={otel_config.traces_enabled}, "
        f"metrics={otel_config.metrics_enabled})"
    )

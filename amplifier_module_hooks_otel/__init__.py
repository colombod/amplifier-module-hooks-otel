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
    APPROVAL_DENIED,
    APPROVAL_GRANTED,
    # Approvals
    APPROVAL_REQUIRED,
    ARTIFACT_READ,
    # Artifacts
    ARTIFACT_WRITE,
    CANCEL_COMPLETED,
    # Cancellation
    CANCEL_REQUESTED,
    # Context management
    CONTEXT_COMPACTION,
    CONTEXT_INCLUDE,
    EXECUTION_END,
    # Orchestrator/execution
    EXECUTION_START,
    # LLM calls
    LLM_REQUEST,
    LLM_RESPONSE,
    ORCHESTRATOR_COMPLETE,
    PLAN_END,
    # Planning phases
    PLAN_START,
    # Policy
    POLICY_VIOLATION,
    PROMPT_COMPLETE,
    # Prompt lifecycle
    PROMPT_SUBMIT,
    PROVIDER_ERROR,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    # Session lifecycle
    SESSION_START,
    TOOL_ERROR,
    TOOL_POST,
    # Tool invocations
    TOOL_PRE,
)
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from . import telemetry
from .attributes import AttributeMapper
from .config import CaptureConfig, OTelConfig, SensitiveDataConfig
from .metrics import MetricsRecorder
from .spans import SpanManager

logger = logging.getLogger(__name__)

# Events we observe for tracing
TRACED_EVENTS = [
    # Session lifecycle
    SESSION_START,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    # Prompt lifecycle
    PROMPT_SUBMIT,
    PROMPT_COMPLETE,
    # Planning
    PLAN_START,
    PLAN_END,
    # Execution
    EXECUTION_START,
    EXECUTION_END,
    ORCHESTRATOR_COMPLETE,
    # LLM
    LLM_REQUEST,
    LLM_RESPONSE,
    PROVIDER_ERROR,
    # Tools
    TOOL_PRE,
    TOOL_POST,
    TOOL_ERROR,
    # Context
    CONTEXT_COMPACTION,
    CONTEXT_INCLUDE,
    # Approvals
    APPROVAL_REQUIRED,
    APPROVAL_GRANTED,
    APPROVAL_DENIED,
    # Cancellation
    CANCEL_REQUESTED,
    CANCEL_COMPLETED,
    # Artifacts
    ARTIFACT_WRITE,
    ARTIFACT_READ,
    # Policy
    POLICY_VIOLATION,
]

# Public exports
__all__ = [
    "OTelHook",
    "OTelConfig",
    "CaptureConfig",
    "SensitiveDataConfig",
    "SpanManager",
    "MetricsRecorder",
    "AttributeMapper",
    "mount",
    "unmount",
    "TRACED_EVENTS",
    "telemetry",
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
            self._pending_llm: dict[str, str] = {}
            self._pending_tools: dict[str, str] = {}
            self._pending_prompts: dict[str, str] = {}
            self._pending_plans: dict[str, str] = {}
            self._pending_approvals: dict[str, str] = {}
            self._pending_cancellations: dict[str, str] = {}
            self._fork_parent_map: dict[str, str] = {}
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

        self._span_manager = SpanManager(self._tracer, config)
        self._metrics_recorder = MetricsRecorder(self._meter) if config.metrics_enabled else None

        # Register telemetry API for application use
        if self._metrics_recorder is not None:
            telemetry._register(self._metrics_recorder, self._span_manager)

        # Internal correlation tracking - avoids mutating event data
        # Maps (session_id, event_type) → correlation_key for pending operations
        self._pending_llm: dict[str, str] = {}  # session_id → correlation_key
        self._pending_tools: dict[str, str] = {}  # session_id → correlation_key
        self._pending_prompts: dict[str, str] = {}  # session_id → correlation_key
        self._pending_plans: dict[str, str] = {}  # session_id → correlation_key
        self._pending_approvals: dict[str, str] = {}  # session_id → correlation_key
        self._pending_cancellations: dict[str, str] = {}  # session_id → correlation_key

        # Parent-child session mapping for trace context propagation
        # When session:fork is received, we record the parent so that when
        # session:start is received for the child, we can link the traces
        self._fork_parent_map: dict[str, str] = {}  # child_session_id → parent_session_id

    async def on_session_start(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:start - create root span with trace context propagation.

        For child sessions (spawned via session:fork), this links the child's
        span to the parent session's trace, ensuring:
        - Same trace_id across parent and child (W3C Trace Context)
        - Proper parent_id linking for distributed tracing
        - Full trace hierarchy visibility in APM tools

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        # Check if this session was forked from a parent (recorded in session:fork)
        parent_session_id = self._fork_parent_map.pop(session_id, None)

        # Record metrics (session started)
        if self._metrics_recorder:
            self._metrics_recorder.record_session_started(
                session_id=session_id,
                user_id=data.get("user_id", ""),
                is_fork=parent_session_id is not None,
                is_resume=False,
            )

        # Create trace span if traces enabled
        if self.config.traces_enabled and self._span_manager:
            attrs = AttributeMapper.for_session(data)
            if parent_session_id:
                attrs["amplifier.session.parent_id"] = parent_session_id
            self._span_manager.start_session_span(session_id, attrs, parent_session_id)

        return HookResult(action="continue")

    async def on_session_end(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:end - end root span and record session duration.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        # Record session duration metric
        if self._metrics_recorder:
            status = data.get("status", "completed")
            self._metrics_recorder.record_session_ended(session_id, status)

        # End trace span
        if self.config.traces_enabled and self._span_manager:
            self._span_manager.end_session_span(session_id)

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
        """Handle execution:end - end turn span and record turn completion.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        # Get turn number from span manager before ending turn
        turn_number = 0
        if self._span_manager:
            ctx = self._span_manager._sessions.get(session_id)
            if ctx:
                turn_number = ctx.turn_count

        # Record turn completed metric
        if self._metrics_recorder:
            self._metrics_recorder.record_turn_completed(session_id, turn_number)

        # End trace span
        if self.config.traces_enabled and self._span_manager:
            self._span_manager.end_turn_span(session_id)

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
            provider = data.get("provider", "unknown")
            model = data.get("model", "unknown")

            # GenAI convention metrics
            self._metrics_recorder.record_duration(correlation_key, metric_attrs)
            self._metrics_recorder.record_token_usage(
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                metric_attrs,
            )

            # Amplifier-specific metrics
            self._metrics_recorder.record_llm_call(provider, model, success=True)

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
                duration = self._metrics_recorder.record_duration(correlation_key, attrs)
                tool_name = data.get("tool_name", "unknown")
                # Record Amplifier-specific tool metrics
                self._metrics_recorder.record_tool_call(tool_name, duration, success=True)

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
            # Add error attributes (error.type is safe, not the message)
            span = self._span_manager.get_active_span(correlation_key)  # type: ignore[union-attr]
            if span:
                error_attrs = AttributeMapper.for_error(data)
                for key, value in error_attrs.items():
                    span.set_attribute(key, value)

            # Filter error message if sensitive data filtering is enabled
            error_data = data.get("error", {})
            if self.config.should_filter("error_messages"):
                error_msg = "[FILTERED]"
            else:
                error_msg = (
                    error_data.get("message", "Tool error")
                    if isinstance(error_data, dict)
                    else "Tool error"
                )
            self._span_manager.end_child_span(correlation_key, StatusCode.ERROR, error_msg)  # type: ignore[union-attr]

            if self._metrics_recorder:
                attrs = AttributeMapper.for_tool(data)
                duration = self._metrics_recorder.record_duration(correlation_key, attrs)
                tool_name = data.get("tool_name", "unknown")
                # Record Amplifier-specific tool metrics with failure
                self._metrics_recorder.record_tool_call(tool_name, duration, success=False)

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
            # Filter error message if sensitive data filtering is enabled
            error_data = data.get("error", {})
            if self.config.should_filter("error_messages"):
                error_msg = "[FILTERED]"
            else:
                error_msg = (
                    error_data.get("message", "Provider error")
                    if isinstance(error_data, dict)
                    else "Provider error"
                )
            self._span_manager.end_child_span(correlation_key, StatusCode.ERROR, error_msg)  # type: ignore[union-attr]

            # Record failed LLM call metric
            if self._metrics_recorder:
                provider = data.get("provider", "unknown")
                model = data.get("model", "unknown")
                self._metrics_recorder.record_llm_call(provider, model, success=False)

        return HookResult(action="continue")

    # ========== Session Fork/Resume (Agent Spawning) ==========

    async def on_session_fork(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:fork - record parent-child relationship for trace linking.

        This event is emitted when a child session is spawned (e.g., via task tool).
        We record the parent-child relationship here so that when session:start
        is emitted for the child, we can properly link the traces.

        W3C Trace Context Propagation:
        - The child session's span will have the same trace_id as parent
        - The parent_id (span_id) will point to the parent session's span
        - This enables full distributed tracing across agent spawning

        Args:
            event: Event name.
            data: Event data containing session_id (child), parent (parent session ID).

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        child_session_id = data.get("session_id")
        parent_session_id = data.get("parent")  # Amplifier uses "parent" for parent session ID

        if child_session_id and parent_session_id:
            # Record the relationship - session:start will use this to link traces
            self._fork_parent_map[child_session_id] = parent_session_id
            logger.debug(f"Recorded fork: child={child_session_id} parent={parent_session_id}")

        return HookResult(action="continue")

    async def on_session_resume(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle session:resume - record session resumption.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        # Create session span for resumed session
        attrs = AttributeMapper.for_session_resume(data)
        self._span_manager.start_session_span(session_id, attrs)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Prompt Lifecycle ==========

    async def on_prompt_submit(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle prompt:submit - start prompt processing span.

        Args:
            event: Event name.
            data: Event data containing session_id, prompt.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_prompt(data)
        correlation_key = f"prompt:{session_id}:{id(data)}"

        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "prompt",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )

        self._pending_prompts[session_id] = correlation_key

        return HookResult(action="continue")

    async def on_prompt_complete(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle prompt:complete - end prompt processing span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_prompts.pop(session_id, None) if session_id else None

        if correlation_key:
            self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Planning Phases ==========

    async def on_plan_start(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle plan:start - start planning phase span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_plan(data)
        correlation_key = f"plan:{session_id}:{id(data)}"

        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "plan",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )

        self._pending_plans[session_id] = correlation_key

        return HookResult(action="continue")

    async def on_plan_end(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle plan:end - end planning phase span.

        Args:
            event: Event name.
            data: Event data containing session_id.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_plans.pop(session_id, None) if session_id else None

        if correlation_key:
            self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Context Management ==========

    async def on_context_compaction(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle context:compaction - record context compaction event.

        Args:
            event: Event name.
            data: Event data containing compaction details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_context_compaction(data)

        # Context compaction is an instant event, create and immediately end span
        correlation_key = f"compaction:{session_id}:{id(data)}"
        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "context_compaction",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )
        self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_context_include(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle context:include - record context include event.

        Args:
            event: Event name.
            data: Event data containing include details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_context_include(data)

        # Context include is an instant event
        correlation_key = f"include:{session_id}:{id(data)}"
        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "context_include",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )
        self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Approvals (Human-in-Loop) ==========

    async def on_approval_required(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle approval:required - start approval span.

        Args:
            event: Event name.
            data: Event data containing approval details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_approval(data)
        correlation_key = f"approval:{session_id}:{id(data)}"

        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "approval_pending",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )

        self._pending_approvals[session_id] = correlation_key

        return HookResult(action="continue")

    async def on_approval_granted(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle approval:granted - end approval span with success.

        Args:
            event: Event name.
            data: Event data.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_approvals.pop(session_id, None) if session_id else None

        if correlation_key:
            span = self._span_manager.get_active_span(correlation_key)  # type: ignore[union-attr]
            if span:
                span.set_attribute("amplifier.approval.result", "granted")
            self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_approval_denied(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle approval:denied - end approval span with denial.

        Args:
            event: Event name.
            data: Event data containing denial reason.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_approvals.pop(session_id, None) if session_id else None

        if correlation_key:
            span = self._span_manager.get_active_span(correlation_key)  # type: ignore[union-attr]
            if span:
                span.set_attribute("amplifier.approval.result", "denied")
                reason = data.get("reason", "")
                if reason:
                    span.set_attribute("amplifier.approval.denial_reason", reason)
            self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Cancellation ==========

    async def on_cancel_requested(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle cancel:requested - record cancellation request.

        Args:
            event: Event name.
            data: Event data containing cancellation details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_cancellation(data)
        correlation_key = f"cancel:{session_id}:{id(data)}"

        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "cancellation",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )

        self._pending_cancellations[session_id] = correlation_key

        return HookResult(action="continue")

    async def on_cancel_completed(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle cancel:completed - end cancellation span.

        Args:
            event: Event name.
            data: Event data.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        correlation_key = self._pending_cancellations.pop(session_id, None) if session_id else None

        if correlation_key:
            self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Artifacts ==========

    async def on_artifact_write(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle artifact:write - record artifact write event.

        Args:
            event: Event name.
            data: Event data containing artifact details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_artifact(data, "write")

        # Artifact write is an instant event
        correlation_key = f"artifact_write:{session_id}:{id(data)}"
        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "artifact_write",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )
        self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    async def on_artifact_read(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle artifact:read - record artifact read event.

        Args:
            event: Event name.
            data: Event data containing artifact details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_artifact(data, "read")

        # Artifact read is an instant event
        correlation_key = f"artifact_read:{session_id}:{id(data)}"
        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "artifact_read",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )
        self._span_manager.end_child_span(correlation_key, StatusCode.OK)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Policy ==========

    async def on_policy_violation(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle policy:violation - record policy violation event.

        Args:
            event: Event name.
            data: Event data containing violation details.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="continue")

        attrs = AttributeMapper.for_policy_violation(data)

        # Policy violation is an instant event with error status
        correlation_key = f"policy:{session_id}:{id(data)}"
        self._span_manager.start_child_span(  # type: ignore[union-attr]
            session_id,
            "policy_violation",
            SpanKind.INTERNAL,
            attrs,
            correlation_key=correlation_key,
        )
        violation_type = data.get("violation_type", "policy violation")
        self._span_manager.end_child_span(correlation_key, StatusCode.ERROR, violation_type)  # type: ignore[union-attr]

        return HookResult(action="continue")

    # ========== Orchestrator ==========

    async def on_orchestrator_complete(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle orchestrator:complete - record orchestrator completion.

        Args:
            event: Event name.
            data: Event data.

        Returns:
            HookResult with action="continue".
        """
        if not self.config.enabled or not self.config.traces_enabled:
            return HookResult(action="continue")

        # This is informational - the session span captures the full lifecycle
        # We just add an attribute to the session span if it exists
        session_id = data.get("session_id")
        if session_id and self._span_manager:
            # Get session span and add completion attribute
            session_span = self._span_manager.get_session_span(session_id)
            if session_span:
                session_span.set_attribute("amplifier.orchestrator.completed", True)

        return HookResult(action="continue")


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None) -> None:
    """Mount the OpenTelemetry hook module.

    Args:
        coordinator: ModuleCoordinator for registering hooks.
        config: Optional configuration dictionary.
    """
    from .exporters import setup_metrics, setup_tracing

    config_dict = config or {}
    otel_config = OTelConfig.from_dict(config_dict.copy())

    # Set up exporters if enabled
    if otel_config.enabled:
        if otel_config.traces_enabled:
            setup_tracing(otel_config)
        if otel_config.metrics_enabled:
            setup_metrics(otel_config)

    hook = OTelHook(otel_config)

    # Priority-based registration:
    # - Low priority (5) for start events: see events early
    # - High priority (95) for end events: see final state
    # - Medium priority (50) for instant/informational events
    PRIORITY_LOW = 5  # Start events - observe early
    PRIORITY_MED = 50  # Instant events
    PRIORITY_HIGH = 95  # End events - capture final state

    # Event registrations: (event, handler, priority)
    event_registrations: list[tuple[str, Any, int]] = [
        # Session lifecycle - start early, end late
        (SESSION_START, hook.on_session_start, PRIORITY_LOW),
        (SESSION_END, hook.on_session_end, PRIORITY_HIGH),
        (SESSION_FORK, hook.on_session_fork, PRIORITY_LOW),
        (SESSION_RESUME, hook.on_session_resume, PRIORITY_LOW),
        # Prompt lifecycle
        (PROMPT_SUBMIT, hook.on_prompt_submit, PRIORITY_LOW),
        (PROMPT_COMPLETE, hook.on_prompt_complete, PRIORITY_HIGH),
        # Planning
        (PLAN_START, hook.on_plan_start, PRIORITY_LOW),
        (PLAN_END, hook.on_plan_end, PRIORITY_HIGH),
        # Execution - start early, end late
        (EXECUTION_START, hook.on_execution_start, PRIORITY_LOW),
        (EXECUTION_END, hook.on_execution_end, PRIORITY_HIGH),
        (ORCHESTRATOR_COMPLETE, hook.on_orchestrator_complete, PRIORITY_HIGH),
        # LLM - request early, response late
        (LLM_REQUEST, hook.on_llm_request, PRIORITY_LOW),
        (LLM_RESPONSE, hook.on_llm_response, PRIORITY_HIGH),
        (PROVIDER_ERROR, hook.on_provider_error, PRIORITY_HIGH),
        # Tools - pre early, post late
        (TOOL_PRE, hook.on_tool_pre, PRIORITY_LOW),
        (TOOL_POST, hook.on_tool_post, PRIORITY_HIGH),
        (TOOL_ERROR, hook.on_tool_error, PRIORITY_HIGH),
        # Context - instant events
        (CONTEXT_COMPACTION, hook.on_context_compaction, PRIORITY_MED),
        (CONTEXT_INCLUDE, hook.on_context_include, PRIORITY_MED),
        # Approvals
        (APPROVAL_REQUIRED, hook.on_approval_required, PRIORITY_LOW),
        (APPROVAL_GRANTED, hook.on_approval_granted, PRIORITY_HIGH),
        (APPROVAL_DENIED, hook.on_approval_denied, PRIORITY_HIGH),
        # Cancellation
        (CANCEL_REQUESTED, hook.on_cancel_requested, PRIORITY_LOW),
        (CANCEL_COMPLETED, hook.on_cancel_completed, PRIORITY_HIGH),
        # Artifacts - instant events
        (ARTIFACT_WRITE, hook.on_artifact_write, PRIORITY_MED),
        (ARTIFACT_READ, hook.on_artifact_read, PRIORITY_MED),
        # Policy - instant event
        (POLICY_VIOLATION, hook.on_policy_violation, PRIORITY_MED),
    ]

    # Register handlers with appropriate priorities
    for event, handler, priority in event_registrations:
        coordinator.hooks.register(event, handler, priority=priority, name="hooks-otel")

    logger.info(
        f"Mounted hooks-otel (exporter={otel_config.exporter}, "
        f"traces={otel_config.traces_enabled}, metrics={otel_config.metrics_enabled})"
    )


async def unmount(coordinator: ModuleCoordinator) -> None:
    """Unmount the OpenTelemetry hook module.

    Cleans up:
    - Unregisters all event handlers from coordinator
    - Clears telemetry API registration

    Args:
        coordinator: ModuleCoordinator to unregister hooks from.
    """
    # Unregister all hooks-otel handlers
    coordinator.hooks.unregister_by_name("hooks-otel")

    # Clean up telemetry API
    telemetry._unregister()

    logger.info("Unmounted hooks-otel")

"""Attribute mapping from Amplifier kernel events to OTel semantic conventions."""

from typing import Any


class AttributeMapper:
    """Map Amplifier kernel events to OTel GenAI semantic conventions.

    This class provides static methods to translate event data from the
    Amplifier kernel into OpenTelemetry attributes following the GenAI
    semantic conventions specification.
    """

    # GenAI semantic convention attribute names
    GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
    GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
    GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
    GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
    GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"

    # Amplifier-specific attributes
    AMPLIFIER_SESSION_ID = "amplifier.session.id"
    AMPLIFIER_TURN_NUMBER = "amplifier.turn.number"
    AMPLIFIER_TOOL_NAME = "amplifier.tool.name"

    @staticmethod
    def for_session(data: dict[str, Any]) -> dict[str, Any]:
        """Map session:start data to span attributes.

        Args:
            data: Event data from session:start event.

        Returns:
            Dictionary of OTel attributes for the session span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_PROVIDER_NAME: "amplifier",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        return attrs

    @staticmethod
    def for_llm_request(data: dict[str, Any]) -> dict[str, Any]:
        """Map llm:request to gen_ai.* attributes.

        Args:
            data: Event data from llm:request event.

        Returns:
            Dictionary of OTel attributes for the LLM request span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "chat",
        }
        if provider := data.get("provider"):
            attrs[AttributeMapper.GEN_AI_PROVIDER_NAME] = provider
        if model := data.get("model"):
            attrs[AttributeMapper.GEN_AI_REQUEST_MODEL] = model
        return attrs

    @staticmethod
    def for_llm_response(data: dict[str, Any]) -> dict[str, Any]:
        """Map llm:response to gen_ai.* attributes with usage.

        Args:
            data: Event data from llm:response event.

        Returns:
            Dictionary of OTel attributes including token usage.
        """
        attrs: dict[str, Any] = {}
        if usage := data.get("usage"):
            if input_tokens := usage.get("input_tokens"):
                attrs[AttributeMapper.GEN_AI_USAGE_INPUT_TOKENS] = input_tokens
            if output_tokens := usage.get("output_tokens"):
                attrs[AttributeMapper.GEN_AI_USAGE_OUTPUT_TOKENS] = output_tokens
        if model := data.get("model") or data.get("response_model"):
            attrs[AttributeMapper.GEN_AI_RESPONSE_MODEL] = model
        if finish_reason := data.get("finish_reason"):
            attrs[AttributeMapper.GEN_AI_RESPONSE_FINISH_REASONS] = [finish_reason]
        return attrs

    @staticmethod
    def for_tool(data: dict[str, Any]) -> dict[str, Any]:
        """Map tool:pre/post to amplifier.tool.* attributes.

        Args:
            data: Event data from tool:pre or tool:post event.

        Returns:
            Dictionary of OTel attributes for tool execution span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "execute_tool",
        }
        if tool_name := data.get("tool_name"):
            attrs[AttributeMapper.AMPLIFIER_TOOL_NAME] = tool_name
        return attrs

    @staticmethod
    def for_error(data: dict[str, Any]) -> dict[str, Any]:
        """Map error data to error.type attribute.

        Args:
            data: Event data containing error information.

        Returns:
            Dictionary with error.type attribute.
        """
        attrs: dict[str, Any] = {}
        if error := data.get("error"):
            if isinstance(error, dict):
                attrs["error.type"] = error.get("type", "_OTHER")
            else:
                attrs["error.type"] = type(error).__name__
        return attrs

    # ========== Session Fork/Resume ==========

    @staticmethod
    def for_session_fork(data: dict[str, Any]) -> dict[str, Any]:
        """Map session:fork data to span attributes (agent spawning).

        Args:
            data: Event data from session:fork event.

        Returns:
            Dictionary of OTel attributes for child session span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_PROVIDER_NAME: "amplifier",
            "amplifier.session.type": "fork",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if parent_id := data.get("parent_id"):
            attrs["amplifier.session.parent_id"] = parent_id
        if agent := data.get("agent"):
            attrs["amplifier.agent.name"] = agent
        return attrs

    @staticmethod
    def for_session_resume(data: dict[str, Any]) -> dict[str, Any]:
        """Map session:resume data to span attributes.

        Args:
            data: Event data from session:resume event.

        Returns:
            Dictionary of OTel attributes for resumed session span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_PROVIDER_NAME: "amplifier",
            "amplifier.session.type": "resume",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        return attrs

    # ========== Prompt Lifecycle ==========

    @staticmethod
    def for_prompt(data: dict[str, Any]) -> dict[str, Any]:
        """Map prompt:submit data to span attributes.

        Args:
            data: Event data from prompt:submit event.

        Returns:
            Dictionary of OTel attributes for prompt span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "prompt",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        # Don't include prompt content for privacy
        if prompt := data.get("prompt"):
            attrs["amplifier.prompt.length"] = len(prompt)
        return attrs

    # ========== Planning ==========

    @staticmethod
    def for_plan(data: dict[str, Any]) -> dict[str, Any]:
        """Map plan:start data to span attributes.

        Args:
            data: Event data from plan:start event.

        Returns:
            Dictionary of OTel attributes for plan span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "plan",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if plan_type := data.get("plan_type"):
            attrs["amplifier.plan.type"] = plan_type
        return attrs

    # ========== Context Management ==========

    @staticmethod
    def for_context_compaction(data: dict[str, Any]) -> dict[str, Any]:
        """Map context:compaction data to span attributes.

        Args:
            data: Event data from context:compaction event.

        Returns:
            Dictionary of OTel attributes for compaction span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "context_compaction",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if tokens_before := data.get("tokens_before"):
            attrs["amplifier.context.tokens_before"] = tokens_before
        if tokens_after := data.get("tokens_after"):
            attrs["amplifier.context.tokens_after"] = tokens_after
        if messages_removed := data.get("messages_removed"):
            attrs["amplifier.context.messages_removed"] = messages_removed
        return attrs

    @staticmethod
    def for_context_include(data: dict[str, Any]) -> dict[str, Any]:
        """Map context:include data to span attributes.

        Args:
            data: Event data from context:include event.

        Returns:
            Dictionary of OTel attributes for include span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "context_include",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if source := data.get("source"):
            attrs["amplifier.context.include_source"] = source
        if path := data.get("path"):
            attrs["amplifier.context.include_path"] = path
        return attrs

    # ========== Approvals ==========

    @staticmethod
    def for_approval(data: dict[str, Any]) -> dict[str, Any]:
        """Map approval:required data to span attributes.

        Args:
            data: Event data from approval:required event.

        Returns:
            Dictionary of OTel attributes for approval span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "approval",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if approval_type := data.get("type"):
            attrs["amplifier.approval.type"] = approval_type
        if tool_name := data.get("tool_name"):
            attrs["amplifier.approval.tool"] = tool_name
        return attrs

    # ========== Cancellation ==========

    @staticmethod
    def for_cancellation(data: dict[str, Any]) -> dict[str, Any]:
        """Map cancel:requested data to span attributes.

        Args:
            data: Event data from cancel:requested event.

        Returns:
            Dictionary of OTel attributes for cancellation span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "cancellation",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if immediate := data.get("immediate"):
            attrs["amplifier.cancel.immediate"] = immediate
        if reason := data.get("reason"):
            attrs["amplifier.cancel.reason"] = reason
        return attrs

    # ========== Artifacts ==========

    @staticmethod
    def for_artifact(data: dict[str, Any], operation: str) -> dict[str, Any]:
        """Map artifact:read/write data to span attributes.

        Args:
            data: Event data from artifact event.
            operation: Either "read" or "write".

        Returns:
            Dictionary of OTel attributes for artifact span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: f"artifact_{operation}",
            "amplifier.artifact.operation": operation,
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if path := data.get("path"):
            attrs["amplifier.artifact.path"] = path
        if artifact_type := data.get("type"):
            attrs["amplifier.artifact.type"] = artifact_type
        if size := data.get("size"):
            attrs["amplifier.artifact.size"] = size
        return attrs

    # ========== Policy ==========

    @staticmethod
    def for_policy_violation(data: dict[str, Any]) -> dict[str, Any]:
        """Map policy:violation data to span attributes.

        Args:
            data: Event data from policy:violation event.

        Returns:
            Dictionary of OTel attributes for policy violation span.
        """
        attrs: dict[str, Any] = {
            AttributeMapper.GEN_AI_OPERATION_NAME: "policy_violation",
        }
        if session_id := data.get("session_id"):
            attrs[AttributeMapper.AMPLIFIER_SESSION_ID] = session_id
        if violation_type := data.get("violation_type"):
            attrs["amplifier.policy.violation_type"] = violation_type
        if policy := data.get("policy"):
            attrs["amplifier.policy.name"] = policy
        if tool_name := data.get("tool_name"):
            attrs["amplifier.policy.tool"] = tool_name
        return attrs

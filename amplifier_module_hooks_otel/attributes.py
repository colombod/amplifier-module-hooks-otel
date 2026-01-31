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

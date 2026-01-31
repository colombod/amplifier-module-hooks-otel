"""Tests for AttributeMapper."""

from amplifier_module_hooks_otel.attributes import AttributeMapper


class TestAttributeMapperForSession:
    """Tests for session attribute mapping."""

    def test_maps_session_id(self):
        """Session ID is mapped to amplifier.session.id."""
        data = {"session_id": "test-session-123"}
        attrs = AttributeMapper.for_session(data)

        assert attrs[AttributeMapper.AMPLIFIER_SESSION_ID] == "test-session-123"

    def test_sets_provider_name_to_amplifier(self):
        """Provider name is always 'amplifier' for sessions."""
        data = {"session_id": "test-session-123"}
        attrs = AttributeMapper.for_session(data)

        assert attrs[AttributeMapper.GEN_AI_PROVIDER_NAME] == "amplifier"

    def test_handles_missing_session_id(self):
        """Missing session_id doesn't add the attribute."""
        data = {}
        attrs = AttributeMapper.for_session(data)

        assert AttributeMapper.AMPLIFIER_SESSION_ID not in attrs


class TestAttributeMapperForLlmRequest:
    """Tests for LLM request attribute mapping."""

    def test_maps_operation_name(self):
        """Operation name is always 'chat'."""
        data = {}
        attrs = AttributeMapper.for_llm_request(data)

        assert attrs[AttributeMapper.GEN_AI_OPERATION_NAME] == "chat"

    def test_maps_provider(self):
        """Provider name is mapped from data."""
        data = {"provider": "anthropic"}
        attrs = AttributeMapper.for_llm_request(data)

        assert attrs[AttributeMapper.GEN_AI_PROVIDER_NAME] == "anthropic"

    def test_maps_model(self):
        """Model name is mapped from data."""
        data = {"model": "claude-3-opus"}
        attrs = AttributeMapper.for_llm_request(data)

        assert attrs[AttributeMapper.GEN_AI_REQUEST_MODEL] == "claude-3-opus"

    def test_handles_missing_provider(self):
        """Missing provider doesn't add attribute."""
        data = {"model": "gpt-4"}
        attrs = AttributeMapper.for_llm_request(data)

        assert AttributeMapper.GEN_AI_PROVIDER_NAME not in attrs

    def test_handles_missing_model(self):
        """Missing model doesn't add attribute."""
        data = {"provider": "openai"}
        attrs = AttributeMapper.for_llm_request(data)

        assert AttributeMapper.GEN_AI_REQUEST_MODEL not in attrs


class TestAttributeMapperForLlmResponse:
    """Tests for LLM response attribute mapping."""

    def test_maps_input_tokens(self):
        """Input tokens are mapped from usage."""
        data = {"usage": {"input_tokens": 100}}
        attrs = AttributeMapper.for_llm_response(data)

        assert attrs[AttributeMapper.GEN_AI_USAGE_INPUT_TOKENS] == 100

    def test_maps_output_tokens(self):
        """Output tokens are mapped from usage."""
        data = {"usage": {"output_tokens": 50}}
        attrs = AttributeMapper.for_llm_response(data)

        assert attrs[AttributeMapper.GEN_AI_USAGE_OUTPUT_TOKENS] == 50

    def test_maps_response_model(self):
        """Response model is mapped."""
        data = {"model": "claude-3-opus-20240229"}
        attrs = AttributeMapper.for_llm_response(data)

        assert attrs[AttributeMapper.GEN_AI_RESPONSE_MODEL] == "claude-3-opus-20240229"

    def test_maps_response_model_from_response_model_field(self):
        """Response model can come from response_model field."""
        data = {"response_model": "gpt-4-turbo"}
        attrs = AttributeMapper.for_llm_response(data)

        assert attrs[AttributeMapper.GEN_AI_RESPONSE_MODEL] == "gpt-4-turbo"

    def test_maps_finish_reason(self):
        """Finish reason is mapped as a list."""
        data = {"finish_reason": "end_turn"}
        attrs = AttributeMapper.for_llm_response(data)

        assert attrs[AttributeMapper.GEN_AI_RESPONSE_FINISH_REASONS] == ["end_turn"]

    def test_handles_missing_usage(self):
        """Missing usage doesn't cause error."""
        data = {}
        attrs = AttributeMapper.for_llm_response(data)

        assert AttributeMapper.GEN_AI_USAGE_INPUT_TOKENS not in attrs
        assert AttributeMapper.GEN_AI_USAGE_OUTPUT_TOKENS not in attrs

    def test_handles_empty_usage(self):
        """Empty usage dict doesn't add token attributes."""
        data = {"usage": {}}
        attrs = AttributeMapper.for_llm_response(data)

        assert AttributeMapper.GEN_AI_USAGE_INPUT_TOKENS not in attrs


class TestAttributeMapperForTool:
    """Tests for tool attribute mapping."""

    def test_maps_operation_name(self):
        """Operation name is 'execute_tool'."""
        data = {}
        attrs = AttributeMapper.for_tool(data)

        assert attrs[AttributeMapper.GEN_AI_OPERATION_NAME] == "execute_tool"

    def test_maps_tool_name(self):
        """Tool name is mapped."""
        data = {"tool_name": "bash"}
        attrs = AttributeMapper.for_tool(data)

        assert attrs[AttributeMapper.AMPLIFIER_TOOL_NAME] == "bash"

    def test_handles_missing_tool_name(self):
        """Missing tool name doesn't add attribute."""
        data = {}
        attrs = AttributeMapper.for_tool(data)

        assert AttributeMapper.AMPLIFIER_TOOL_NAME not in attrs


class TestAttributeMapperForError:
    """Tests for error attribute mapping."""

    def test_maps_error_type_from_dict(self):
        """Error type is extracted from error dict."""
        data = {"error": {"type": "ValidationError", "message": "Invalid input"}}
        attrs = AttributeMapper.for_error(data)

        assert attrs["error.type"] == "ValidationError"

    def test_maps_error_type_default(self):
        """Error type defaults to _OTHER when not in dict."""
        data = {"error": {"message": "Something went wrong"}}
        attrs = AttributeMapper.for_error(data)

        assert attrs["error.type"] == "_OTHER"

    def test_handles_non_dict_error(self):
        """Non-dict error uses type name."""
        data = {"error": ValueError("test")}
        attrs = AttributeMapper.for_error(data)

        assert attrs["error.type"] == "ValueError"

    def test_handles_missing_error(self):
        """Missing error returns empty attrs."""
        data = {}
        attrs = AttributeMapper.for_error(data)

        assert "error.type" not in attrs

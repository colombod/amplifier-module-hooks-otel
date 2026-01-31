"""Tests for exporters module."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from amplifier_module_hooks_otel.config import OTelConfig
from amplifier_module_hooks_otel.exporters import (
    FileSpanExporter,
    _build_resource,
    setup_tracing,
)


class TestBuildResource:
    """Tests for _build_resource."""

    def test_basic_resource(self):
        """Should create resource with service name and version."""
        config = OTelConfig(service_name="test-app", service_version="1.0.0")
        resource = _build_resource(config)

        attrs = dict(resource.attributes)
        assert attrs["service.name"] == "test-app"
        assert attrs["service.version"] == "1.0.0"

    def test_user_id_from_config(self):
        """Should use user_id from config."""
        config = OTelConfig(user_id="custom-user")
        resource = _build_resource(config)

        attrs = dict(resource.attributes)
        assert attrs["amplifier.user.id"] == "custom-user"

    def test_user_id_fallback_to_env(self):
        """Should fall back to USER env var when user_id is empty."""
        with patch.dict(os.environ, {"USER": "env-user"}):
            config = OTelConfig(user_id="")
            resource = _build_resource(config)

            attrs = dict(resource.attributes)
            assert attrs["amplifier.user.id"] == "env-user"

    def test_team_id(self):
        """Should include team_id."""
        config = OTelConfig(team_id="my-team")
        resource = _build_resource(config)

        attrs = dict(resource.attributes)
        assert attrs["amplifier.team.id"] == "my-team"


class TestFileSpanExporter:
    """Tests for FileSpanExporter."""

    def test_creates_file(self):
        """Should create file if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "traces.jsonl")
            exporter = FileSpanExporter(file_path)
            assert os.path.exists(file_path)
            exporter.shutdown()

    def test_exports_spans(self):
        """Should write spans as JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "traces.jsonl")
            exporter = FileSpanExporter(file_path)

            # Create mock span
            mock_span = MagicMock()
            mock_span.name = "test-span"
            mock_span.context.trace_id = 0x12345678901234567890123456789012
            mock_span.context.span_id = 0x1234567890123456
            mock_span.parent = None
            mock_span.start_time = 1000000000
            mock_span.end_time = 2000000000
            mock_span.attributes = {"key": "value"}
            mock_span.status.status_code.name = "OK"
            mock_span.events = []

            # Export
            from opentelemetry.sdk.trace.export import SpanExportResult

            result = exporter.export([mock_span])
            assert result == SpanExportResult.SUCCESS

            # Verify file content
            with open(file_path) as f:
                line = f.readline()
                record = json.loads(line)
                assert record["name"] == "test-span"
                assert record["attributes"] == {"key": "value"}
                assert record["status"] == "OK"

            exporter.shutdown()

    def test_handles_events(self):
        """Should include span events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "traces.jsonl")
            exporter = FileSpanExporter(file_path)

            # Create mock event
            mock_event = MagicMock()
            mock_event.name = "test-event"
            mock_event.timestamp = 1500000000
            mock_event.attributes = {"event_key": "event_value"}

            # Create mock span with event
            mock_span = MagicMock()
            mock_span.name = "test-span"
            mock_span.context.trace_id = 0x12345678901234567890123456789012
            mock_span.context.span_id = 0x1234567890123456
            mock_span.parent = None
            mock_span.start_time = 1000000000
            mock_span.end_time = 2000000000
            mock_span.attributes = {}
            mock_span.status.status_code.name = "OK"
            mock_span.events = [mock_event]

            exporter.export([mock_span])

            with open(file_path) as f:
                record = json.loads(f.readline())
                assert len(record["events"]) == 1
                assert record["events"][0]["name"] == "test-event"

            exporter.shutdown()


class TestSetupTracing:
    """Tests for setup_tracing."""

    def test_console_exporter(self):
        """Should set up console exporter without error."""
        config = OTelConfig(exporter="console")  # type: ignore
        # Should not raise
        setup_tracing(config)

    def test_file_exporter(self):
        """Should set up file exporter without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "traces.jsonl")
            config = OTelConfig(exporter="file", file_path=file_path)  # type: ignore
            setup_tracing(config)
            assert os.path.exists(file_path)

    def test_unknown_exporter_raises(self):
        """Should raise ValueError for unknown exporter."""
        config = OTelConfig()
        config.exporter = "unknown"  # type: ignore
        with pytest.raises(ValueError, match="Unknown exporter type"):
            setup_tracing(config)

    def test_debug_output(self, capsys):
        """Should print debug info when debug=True."""
        config = OTelConfig(exporter="console", debug=True)  # type: ignore
        setup_tracing(config)

        captured = capsys.readouterr()
        assert "[otel]" in captured.out
        assert "console" in captured.out

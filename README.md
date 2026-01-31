# amplifier-module-hooks-otel

OpenTelemetry observability hook module for [Amplifier](https://github.com/microsoft/amplifier) - translates kernel events to OTel spans and metrics following GenAI semantic conventions.

## Overview

This module provides OpenTelemetry-based observability for Amplifier agents by:

- **Translating kernel events** (session, execution, LLM, tool) to OTel spans and metrics
- **Following GenAI semantic conventions** for AI/ML observability
- **Implementing the hook protocol correctly** - always returns `continue`, never modifies events
- **Purely observational** - traces and measures without affecting agent behavior

## Installation

```bash
# Basic installation
pip install amplifier-module-hooks-otel

# With OTLP exporter support
pip install amplifier-module-hooks-otel[otlp]
```

## Usage

### Basic Setup

The module follows Amplifier's module pattern and can be mounted via entry points:

```python
from amplifier_module_hooks_otel import mount

# Mount returns (hook_function, config_schema)
hook, config_schema = mount()
```

### Configuration

Configure via environment variables or programmatically:

```python
from amplifier_module_hooks_otel import OtelHookConfig

config = OtelHookConfig(
    service_name="my-agent",           # Service name for traces
    enable_tracing=True,               # Enable span creation
    enable_metrics=True,               # Enable metrics collection
)
```

### Application-Side OTel Setup

This module provides the **mechanism** for observability, not the **policy**. Your application configures the OTel exporters:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Configure tracing
provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4317"))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

# Now kernel events will be exported as spans
```

## Spans Created

| Event Type | Span Name | Key Attributes |
|------------|-----------|----------------|
| `session.start` | `session {session_id}` | `session.id`, `amplifier.agent.name` |
| `execution.start` | `execution {execution_id}` | `execution.id`, `gen_ai.request.model` |
| `llm.start` | `gen_ai.chat` | `gen_ai.system`, `gen_ai.request.model`, token counts |
| `tool.start` | `tool {tool_name}` | `tool.name`, `tool.parameters` |

## Metrics Collected

- `gen_ai.client.token.usage` - Token consumption (input/output)
- `gen_ai.client.operation.duration` - Operation latencies
- `amplifier.tool.invocations` - Tool call counts

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
pyright

# Linting
ruff check .
```

## License

MIT

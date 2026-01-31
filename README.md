# Amplifier OpenTelemetry Hook Module

Provides OpenTelemetry observability for Amplifier agents through lifecycle event tracing and metrics.

## Overview

This hook module integrates with Amplifier's hook system to emit OpenTelemetry spans and metrics for agent lifecycle events, following [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

**Events Traced (Full Kernel Coverage):**

| Category | Events | Span/Metric |
|----------|--------|-------------|
| **Session Lifecycle** | `session:start`, `session:end`, `session:fork`, `session:resume` | Root spans, agent spawning |
| **Prompt Lifecycle** | `prompt:submit`, `prompt:complete` | Prompt processing spans |
| **Planning** | `plan:start`, `plan:end` | Planning phase spans |
| **Execution** | `execution:start`, `execution:end`, `orchestrator:complete` | Turn spans |
| **LLM Calls** | `llm:request`, `llm:response`, `provider:error` | GenAI spans + token metrics |
| **Tool Invocations** | `tool:pre`, `tool:post`, `tool:error` | Tool execution spans |
| **Context Management** | `context:compaction`, `context:include` | Context operation spans |
| **Approvals** | `approval:required`, `approval:granted`, `approval:denied` | Human-in-loop spans |
| **Cancellation** | `cancel:requested`, `cancel:completed` | Cancellation spans |
| **Artifacts** | `artifact:read`, `artifact:write` | File operation spans |
| **Policy** | `policy:violation` | Violation spans (error status) |

**Design Philosophy:**
- **Mechanism, not policy** - Module emits telemetry; your application configures where it goes
- **Purely observational** - Never modifies event data or affects agent behavior
- **Always continues** - Hook always returns `continue`, never blocks execution

## Prerequisites

- **Python 3.11+**
- **[UV](https://github.com/astral-sh/uv)** - Fast Python package manager
- **Amplifier** installed and configured

## Installation

```bash
# Install from GitHub
uv pip install git+https://github.com/colombod/amplifier-module-hooks-otel

# Or clone and install locally
git clone https://github.com/colombod/amplifier-module-hooks-otel
uv pip install -e ./amplifier-module-hooks-otel
```

## Configuration

Add to your Amplifier settings file (`~/.amplifier/settings.yaml`):

```yaml
hooks:
  - module: hooks-otel
    config:
      traces_enabled: true   # Enable span creation (default: true)
      metrics_enabled: true  # Enable metrics recording (default: true)
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Master switch - disables all telemetry when false |
| `traces_enabled` | bool | `true` | Enable/disable span creation |
| `metrics_enabled` | bool | `true` | Enable/disable metrics recording |

### Opt-Out via Environment Variable

You can disable all telemetry collection using the `AMPLIFIER_OTEL_OPT_OUT` environment variable:

```bash
# Disable telemetry globally
export AMPLIFIER_OTEL_OPT_OUT=1

# Or per-command
AMPLIFIER_OTEL_OPT_OUT=1 amplifier run "hello"
```

**Accepted values:** `1`, `true`, `yes`, `on` (case-insensitive)

The environment variable **takes precedence** over configuration settings. This is useful for:
- CI/CD environments where telemetry is not needed
- Development machines where you want to reduce noise
- Privacy-sensitive deployments
- Troubleshooting (temporarily disable to isolate issues)

## Application-Side OTel Setup

This module emits telemetry to the **global OpenTelemetry providers**. Your application must configure where telemetry goes (console, OTLP, Jaeger, etc.).

### Basic Console Export (Development)

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader

# Set up tracing to console
trace_provider = TracerProvider()
trace_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(trace_provider)

# Set up metrics to console
metric_reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))

# Now run Amplifier - spans and metrics will print to console
```

### OTLP Export (Production / .NET Aspire)

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

# Configure OTLP endpoint (e.g., .NET Aspire dashboard, Jaeger, etc.)
OTLP_ENDPOINT = "http://localhost:4317"

# Set up tracing
trace_provider = TracerProvider()
trace_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT))
)
trace.set_tracer_provider(trace_provider)

# Set up metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTLP_ENDPOINT)
)
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))

# Now run Amplifier - telemetry goes to OTLP collector
```

### .NET Aspire Integration

When running Amplifier as part of a .NET Aspire application:

1. **Aspire provides the OTLP endpoint** - typically `http://localhost:4317`
2. **Configure Python app** with the OTLP exporter (see above)
3. **Telemetry appears in Aspire dashboard** alongside .NET services

```python
import os
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

# Aspire sets OTEL_EXPORTER_OTLP_ENDPOINT environment variable
otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

# Create resource with service name (appears in Aspire dashboard)
resource = Resource.create({"service.name": "amplifier-agent"})

# Set up tracing
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
)
trace.set_tracer_provider(trace_provider)

# Set up metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=otlp_endpoint)
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

# Run Amplifier - traces appear in Aspire dashboard
```

## Spans Created

### Core Spans

| Kernel Event | Span Name | Kind | Key Attributes |
|--------------|-----------|------|----------------|
| `session:start` | `amplifier.session` | SERVER | `amplifier.session.id` |
| `session:fork` | `amplifier.session` | SERVER | `amplifier.session.id`, `amplifier.session.parent_id`, `amplifier.agent.name` |
| `session:resume` | `amplifier.session` | SERVER | `amplifier.session.id`, `amplifier.session.type=resume` |
| `execution:start` | `amplifier.turn` | INTERNAL | `amplifier.turn.number` |
| `llm:request` | `chat {model}` | CLIENT | `gen_ai.request.model`, `gen_ai.provider.name` |
| `tool:pre` | `execute_tool {name}` | INTERNAL | `amplifier.tool.name` |

### Additional Spans

| Kernel Event | Span Name | Key Attributes |
|--------------|-----------|----------------|
| `prompt:submit` | `prompt` | `amplifier.prompt.length` |
| `plan:start` | `plan` | `amplifier.plan.type` |
| `context:compaction` | `context_compaction` | `amplifier.context.tokens_before`, `amplifier.context.tokens_after` |
| `context:include` | `context_include` | `amplifier.context.include_source`, `amplifier.context.include_path` |
| `approval:required` | `approval_pending` | `amplifier.approval.type`, `amplifier.approval.tool` |
| `cancel:requested` | `cancellation` | `amplifier.cancel.immediate`, `amplifier.cancel.reason` |
| `artifact:write` | `artifact_write` | `amplifier.artifact.path`, `amplifier.artifact.type` |
| `artifact:read` | `artifact_read` | `amplifier.artifact.path` |
| `policy:violation` | `policy_violation` | `amplifier.policy.violation_type`, `amplifier.policy.name` |

### Span Hierarchy

```
amplifier.session (root)
├── prompt
├── amplifier.turn
│   ├── chat claude-sonnet-4-20250514
│   ├── execute_tool bash
│   │   └── approval_pending (if approval required)
│   ├── chat claude-sonnet-4-20250514
│   └── execute_tool task
│       └── amplifier.session (child - agent spawn via session:fork)
│           └── amplifier.turn
│               └── ...
├── context_compaction (when context is trimmed)
└── cancellation (if cancelled)
```

## Metrics Recorded

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | tokens | Input/output token counts per LLM call |
| `gen_ai.client.operation.duration` | Histogram | seconds | Duration of LLM and tool operations |

### Metric Attributes

All metrics include:
- `gen_ai.system` - Provider name (e.g., "anthropic", "openai")
- `gen_ai.request.model` - Model name
- `gen_ai.operation.name` - Operation type ("chat", "execute_tool")
- `gen_ai.token.type` - "input" or "output" (for token usage)

## GenAI Semantic Conventions

This module follows [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

| Convention | Attribute | Example |
|------------|-----------|---------|
| Provider | `gen_ai.system` | `anthropic`, `openai` |
| Model | `gen_ai.request.model` | `claude-3-opus-20240229` |
| Response Model | `gen_ai.response.model` | `claude-3-opus-20240229` |
| Operation | `gen_ai.operation.name` | `chat` |
| Input Tokens | `gen_ai.usage.input_tokens` | `150` |
| Output Tokens | `gen_ai.usage.output_tokens` | `89` |
| Finish Reason | `gen_ai.response.finish_reasons` | `["end_turn"]` |

## Development

```bash
# Clone the repository
git clone https://github.com/colombod/amplifier-module-hooks-otel
cd amplifier-module-hooks-otel

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=amplifier_module_hooks_otel

# Type checking
pyright

# Linting and formatting
ruff check .
ruff format .
```

## License

MIT

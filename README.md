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
      enabled: true
      exporter: console        # console, otlp-http, otlp-grpc, file
      endpoint: http://localhost:4318  # OTLP endpoint
      service_name: my-amplifier-app
      capture:
        traces: true
        metrics: true
        span_events: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Master switch - disables all telemetry when false |
| `exporter` | string | `console` | Exporter type: `console`, `otlp-http`, `otlp-grpc`, `file` |
| `endpoint` | string | `http://localhost:4318` | OTLP collector endpoint |
| `service_name` | string | `amplifier` | Service name in traces |
| `service_version` | string | `0.1.0` | Service version |
| `user_id` | string | `$USER` | User identifier for tracking |
| `team_id` | string | `""` | Team identifier for grouping in APM |
| `headers` | dict | `{}` | HTTP headers for OTLP (auth tokens) |
| `file_path` | string | `/tmp/amplifier-traces.jsonl` | Output path for file exporter |
| `sampling_rate` | float | `1.0` | Sampling rate 0.0-1.0 (1.0 = 100%) |
| `capture.traces` | bool | `true` | Enable/disable span creation |
| `capture.metrics` | bool | `true` | Enable/disable metrics recording |
| `capture.span_events` | bool | `true` | Enable/disable span events |
| `max_attribute_length` | int | `1000` | Max attribute value length |
| `batch_delay_ms` | int | `5000` | Batch export delay (ms) |
| `max_batch_size` | int | `512` | Maximum spans per batch |
| `debug` | bool | `false` | Enable debug output |

### Exporter Types

| Exporter | Use Case | Description |
|----------|----------|-------------|
| `console` | Development | Prints spans to stdout |
| `otlp-http` | Production | Sends to OTLP collector via HTTP (Jaeger, Aspire) |
| `otlp-grpc` | Production | Sends to OTLP collector via gRPC (high throughput) |
| `file` | Debugging | Writes spans to JSONL file |

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

## Quick Start Examples

The module now handles exporter configuration automatically. Just specify the exporter type in config.

### Console Output (Development)

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: console
      debug: true
```

### Jaeger / OTLP Collector

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: otlp-http
      endpoint: http://localhost:4318
      service_name: my-agent
```

### .NET Aspire Integration

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: otlp-http
      endpoint: http://localhost:18889  # Aspire dashboard
      service_name: amplifier-agent
```

### File Output (Debugging)

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: file
      file_path: ./traces.jsonl
```

### Advanced: Custom Application Setup

For advanced scenarios where you need full control over OTel configuration, you can configure exporters at the application level instead:

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Custom setup - module will use these global providers
trace_provider = TracerProvider()
trace_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4317"))
)
trace.set_tracer_provider(trace_provider)

# Then configure hooks-otel with exporter: console (or omit exporter config)
# The module will emit to the globally configured providers
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

### W3C Trace Context Propagation

When agents spawn child sessions (via `session:fork`), trace context is automatically propagated following the [W3C Trace Context](https://www.w3.org/TR/trace-context/) specification:

| Field | Behavior |
|-------|----------|
| `trace_id` | **Same** across parent and all child sessions - identifies the entire distributed trace |
| `parent_id` (span_id) | Child session's span links to parent session's span |
| `trace_flags` | Inherited from parent (sampling decisions propagate) |

This enables:
- **Full trace hierarchy visibility** - See agent spawning chains in your APM (Jaeger, Zipkin, Aspire)
- **Cross-session correlation** - All spans from a request share the same `trace_id`
- **Distributed tracing integration** - Works with any W3C-compliant observability backend

**Example trace with nested agent spawning:**
```
trace_id: abc123...  (same for entire tree)

amplifier.session (root)                    span_id: 001
└── execute_tool task
    └── amplifier.session (child agent)    span_id: 002, parent_id: 001
        └── execute_tool task
            └── amplifier.session (grandchild) span_id: 003, parent_id: 002
```

**Extracting trace context programmatically:**
```python
# Get span context for external correlation
span_context = span_manager.get_span_context(session_id)
if span_context:
    trace_id = format(span_context.trace_id, '032x')
    span_id = format(span_context.span_id, '016x')
    # Use for correlation with external systems
```

### Recipe Tracing

Recipe executions appear as `execute_tool recipes` spans, providing visibility into when recipes run and their overall duration:

```
amplifier.session
└── amplifier.turn
    └── execute_tool recipes    ← Recipe execution visible here
```

> **Note:** Individual recipe steps and stage transitions are not yet traced at a granular level. Deep integration with recipe internals (step-by-step spans, stage approvals, etc.) is planned for future work and will require coordination with the recipes module to emit dedicated events.

## Metrics Recorded

The module emits two categories of metrics for comprehensive observability.

### GenAI Semantic Convention Metrics

Following [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) for APM tool compatibility:

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | `{token}` | Input/output token counts per LLM call |
| `gen_ai.client.operation.duration` | Histogram | `s` | Duration of LLM and tool operations |

**GenAI Metric Attributes:**
- `gen_ai.system` - Provider name (e.g., "anthropic", "openai")
- `gen_ai.request.model` - Model name
- `gen_ai.operation.name` - Operation type ("chat", "execute_tool")
- `gen_ai.token.type` - "input" or "output" (for token usage)

### Amplifier-Specific Metrics

Detailed metrics for Amplifier-specific observability:

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `amplifier.tool.duration` | Histogram | `s` | Tool execution duration |
| `amplifier.session.duration` | Histogram | `s` | Total session duration |
| `amplifier.tool.calls` | Counter | `{call}` | Number of tool invocations |
| `amplifier.llm.calls` | Counter | `{call}` | Number of LLM calls |
| `amplifier.sessions.started` | Counter | `{session}` | Number of sessions started |
| `amplifier.turns.completed` | Counter | `{turn}` | Number of turns completed |

**Amplifier Metric Attributes:**

| Metric | Attributes |
|--------|------------|
| `amplifier.tool.duration` | `amplifier.tool.name`, `amplifier.tool.success` |
| `amplifier.tool.calls` | `amplifier.tool.name`, `amplifier.tool.success` |
| `amplifier.llm.calls` | `gen_ai.system`, `gen_ai.request.model`, `amplifier.llm.success` |
| `amplifier.sessions.started` | `amplifier.session.type` (new/fork/resume), `amplifier.user.id` |
| `amplifier.session.duration` | `amplifier.session.status` (completed/cancelled/error) |
| `amplifier.turns.completed` | `amplifier.turn.number` |

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
uv sync --group dev

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=amplifier_module_hooks_otel

# Type checking
uv run pyright

# Linting and formatting
uv run ruff check .
uv run ruff format .
```

## License

MIT

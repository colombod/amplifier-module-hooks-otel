# amplifier-module-hooks-otel Design

## Overview

OpenTelemetry instrumentation hook for Amplifier. Captures traces, span events, and metrics from Amplifier sessions for observability in APM tools like Jaeger, .NET Aspire, Grafana, and Honeycomb.

This module follows Amplifier's kernel philosophy: **mechanism, not policy**. It provides the mechanism for telemetry export; applications decide where to send it.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Amplifier Session                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Kernel Event System                     │    │
│  │  (session:start, llm:request, tool:pre, etc.)       │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │ events                             │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              hooks-otel Module                       │    │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │    │
│  │  │ SpanManager │ │  Metrics    │ │  Attribute  │    │    │
│  │  │             │ │  Recorder   │ │   Mapper    │    │    │
│  │  └──────┬──────┘ └──────┬──────┘ └─────────────┘    │    │
│  └─────────┼───────────────┼───────────────────────────┘    │
│            │               │                                 │
└────────────┼───────────────┼────────────────────────────────┘
             │               │
             ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Exporters                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ Console  │ │ OTLP-HTTP│ │ OTLP-gRPC│ │   File   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
             │               │
             ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│              APM Backends                                    │
│  Jaeger, .NET Aspire, Grafana Tempo, Honeycomb, etc.        │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. W3C Trace Context Propagation

**Problem**: Agent spawning (via task tool) creates child sessions. Without proper trace linking, these appear as disconnected traces in APM tools.

**Solution**: Full W3C Trace Context propagation:
- Child sessions inherit parent's `trace_id`
- Child's `parent_id` points to parent session's `span_id`
- Enables distributed tracing across agent hierarchies

```
Parent Session (trace_id=abc123)
├── amplifier.session (span_id=001)
│   └── amplifier.tool "task" (span_id=002)
│       └── Child Session (trace_id=abc123, parent_id=002)
│           └── amplifier.session (span_id=003)
│               └── ... child's work ...
```

### 2. GenAI Semantic Conventions

Follows OpenTelemetry GenAI semantic conventions for LLM observability:

| Attribute | Description |
|-----------|-------------|
| `gen_ai.system` | Provider name (anthropic, openai) |
| `gen_ai.request.model` | Model identifier |
| `gen_ai.usage.input_tokens` | Input token count |
| `gen_ai.usage.output_tokens` | Output token count |
| `gen_ai.response.finish_reasons` | Completion reason |

### 3. Nested Tool Stack

**Problem**: Tools can call other tools (e.g., task tool spawns agents that use tools).

**Solution**: Maintain a tool stack per session:
```python
# Tool A starts
stack: [Tool A span]

# Tool A calls Tool B (nested)
stack: [Tool A span, Tool B span]

# Tool B completes
stack: [Tool A span]  # Restored

# Tool A completes
stack: []
```

### 4. Priority-Based Hook Registration

**Problem**: Observability hooks should see events at the right time:
- Start events: See initial state before business hooks modify data
- End events: See final state after all processing

**Solution**: Priority-based registration:
| Event Type | Priority | Rationale |
|------------|----------|-----------|
| Start events (session:start, tool:pre) | Low (5) | Observe early |
| End events (session:end, tool:post) | High (95) | Capture final state |
| Instant events (artifact:write) | Medium (50) | Order doesn't matter |

### 5. Multiple Exporter Support

| Exporter | Use Case | Processor |
|----------|----------|-----------|
| `console` | Development, debugging | SimpleSpanProcessor |
| `otlp-http` | Production (Jaeger, Aspire) | BatchSpanProcessor |
| `otlp-grpc` | Production (high throughput) | BatchSpanProcessor |
| `file` | Debugging, offline analysis | SimpleSpanProcessor |

### 6. Opt-Out Mechanism

Environment variable `AMPLIFIER_OTEL_OPT_OUT=true` disables all telemetry:
- Checked at module load time
- Overrides any config settings
- Zero overhead when disabled (no spans created)

## Span Hierarchy

```
amplifier.session (root, SpanKind.SERVER)
├── amplifier.turn (per execution turn)
│   ├── chat {model} (LLM call, SpanKind.CLIENT)
│   ├── execute_tool {name} (tool execution)
│   │   └── execute_tool {nested} (nested tools)
│   ├── prompt (prompt processing)
│   ├── plan (planning phase)
│   └── approval_pending (human approval wait)
├── context_compaction (instant event)
├── artifact_write (instant event)
└── policy_violation (instant event, ERROR status)
```

## Metrics

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
| `amplifier.bundle.used` | Counter | `{bundle}` | Number of times a bundle is used |

**Amplifier Metric Attributes:**

| Metric | Attributes |
|--------|------------|
| `amplifier.tool.duration` | `amplifier.tool.name`, `amplifier.tool.success` |
| `amplifier.tool.calls` | `amplifier.tool.name`, `amplifier.tool.success` |
| `amplifier.llm.calls` | `gen_ai.system`, `gen_ai.request.model`, `amplifier.llm.success` |
| `amplifier.sessions.started` | `amplifier.session.type` (new/fork/resume), `amplifier.user.id` |
| `amplifier.session.duration` | `amplifier.session.status` (completed/cancelled/error) |
| `amplifier.turns.completed` | `amplifier.turn.number` |
| `amplifier.bundle.used` | `amplifier.bundle.name`, `amplifier.bundle.version`, `amplifier.bundle.source` |

### Bundle Tracking Limitations

> **NOTE**: Bundle lifecycle events (`bundle:load`, `bundle:activate`) do not yet exist in Amplifier's kernel.
> See [microsoft/amplifier#207](https://github.com/microsoft/amplifier/issues/207) for the proposal.
>
> Current workaround: Bundle information is extracted from session context when available.
> The `amplifier.bundle.used` metric tracks bundles when sessions start with bundle information.

**Privacy Protection**: Local bundle paths are sanitized:
- Git URLs (`git+https://`, `https://`) are preserved (public)
- Local paths (`/home/user/...`, `./my-bundle`) become `"local"` (privacy)

## Configuration

```yaml
hooks:
  - module: hooks-otel
    config:
      enabled: true
      exporter: otlp-http          # console, otlp-http, otlp-grpc, file
      endpoint: http://localhost:4318
      service_name: my-amplifier-app
      service_version: 1.0.0
      user_id: ""                   # Falls back to $USER
      team_id: ""                   # For team tracking in APM
      sampling_rate: 1.0            # 1.0 = 100%, 0.1 = 10%
      file_path: /tmp/traces.jsonl  # For file exporter
      capture:
        traces: true
        metrics: true
        span_events: true
      max_attribute_length: 1000
      batch_delay_ms: 5000
      max_batch_size: 512
      debug: false
```

## Event Coverage

All kernel events are instrumented:

| Category | Events |
|----------|--------|
| Session | session:start, session:end, session:fork, session:resume |
| Execution | execution:start, execution:end, orchestrator:complete |
| LLM | llm:request, llm:response, provider:error |
| Tools | tool:pre, tool:post, tool:error |
| Prompt | prompt:submit, prompt:complete |
| Planning | plan:start, plan:end |
| Context | context:compaction, context:include |
| Approvals | approval:required, approval:granted, approval:denied |
| Cancellation | cancel:requested, cancel:completed |
| Artifacts | artifact:write, artifact:read |
| Policy | policy:violation |

## Integration Examples

### .NET Aspire

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: otlp-http
      endpoint: http://localhost:18889  # Aspire dashboard
```

### Jaeger

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: otlp-http
      endpoint: http://localhost:4318
```

### Local Debugging

```yaml
hooks:
  - module: hooks-otel
    config:
      exporter: file
      file_path: ./traces.jsonl
      debug: true
```

## Philosophy Alignment

This module embodies Amplifier's kernel philosophy:

1. **Mechanism, not policy**: Provides telemetry export mechanism; applications decide destination
2. **Non-interference**: Always returns `HookResult(action="continue")`; never blocks or modifies events
3. **Opt-out by default**: Can be disabled via environment variable
4. **Observability as mechanism**: The kernel provides events; this module translates them to OTel

## Credits

This implementation merges work from:
- **colombod/amplifier-module-hooks-otel**: W3C Trace Context, GenAI conventions, test suite
- **robotdad/amplifier-module-hooks-otel**: Multiple exporters, nested tool stack, priority registration

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

## Integration

Hook modules require **two steps** to integrate with Amplifier:

1. **Install** - Makes the Python code available
2. **Configure** - Tells Amplifier to mount the hook and receive events

### How It Works: Complete Integration with amplifier-app-cli

When you run `amplifier run "prompt"`, here's **exactly** what happens to load and activate this hook module:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         USER: amplifier run "hello"                          │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: CLI RESOLVES CONFIGURATION                                           │
│ Component: amplifier-app-cli                                                 │
│                                                                              │
│ What happens:                                                                │
│   • CLI reads active bundle (from `amplifier bundle use` or --bundle flag)   │
│   • Loads bundle YAML including all `includes:` (behaviors, nested bundles)  │
│   • Merges settings.yaml overrides (environment-specific config)             │
│   • Produces a "mount_plan" containing: providers, tools, hooks, context     │
│                                                                              │
│ Why needed:                                                                  │
│   The CLI is the POLICY layer - it decides WHICH bundle/config to use.       │
│   The kernel doesn't know about bundles; it only sees the final mount_plan.  │
│                                                                              │
│ Code path: run.py:157 → config.py:109 → bundle.py:200                        │
│                                                                              │
│ Result: mount_plan = {                                                       │
│   "hooks": [{"module": "hooks-otel", "config": {...}}],                      │
│   "providers": [...], "tools": [...], ...                                    │
│ }                                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: FOUNDATION PREPARES THE SESSION                                      │
│ Component: amplifier-foundation                                              │
│                                                                              │
│ What happens:                                                                │
│   • Foundation's `load_and_prepare_bundle()` activates all modules           │
│   • For each module in hooks/providers/tools:                                │
│     - If `source:` is git URL → clone repo, install package                  │
│     - If already installed → use existing package                            │
│   • Creates a `BundleModuleResolver` that maps module IDs to paths           │
│   • Creates `PreparedBundle` with mount_plan + resolver                      │
│                                                                              │
│ Why needed:                                                                  │
│   Foundation handles MODULE ACTIVATION - downloading, installing, and        │
│   creating the mapping so the kernel can find "hooks-otel" → actual code.    │
│   This separation allows bundles to reference modules by name, not path.     │
│                                                                              │
│ Code path: bundle.py:323 (activate_all) → bundle.py:722 (resolver)           │
│                                                                              │
│ Result: resolver = {"hooks-otel": Path("/home/user/.amplifier/cache/...")}   │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: KERNEL SESSION IS CREATED                                            │
│ Component: amplifier-core (kernel)                                           │
│                                                                              │
│ What happens:                                                                │
│   • `PreparedBundle.create_session()` creates an `AmplifierSession`          │
│   • The resolver is mounted: coordinator.mount("module-source-resolver", r)  │
│   • `session.initialize()` is called to load all modules                     │
│                                                                              │
│ Why needed:                                                                  │
│   The kernel provides the SESSION LIFECYCLE - it's the container that holds  │
│   all modules together. The resolver must be mounted BEFORE initialization   │
│   so the kernel can find modules during the loading loop.                    │
│                                                                              │
│ Code path: bundle.py:1023 → bundle.py:1033 → bundle.py:1053                  │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: KERNEL LOADS HOOK MODULES                                            │
│ Component: amplifier-core (kernel)                                           │
│                                                                              │
│ What happens:                                                                │
│   • Kernel iterates: for hook_config in mount_plan["hooks"]:                 │
│   • For each hook (e.g., "hooks-otel"):                                      │
│     1. loader.load("hooks-otel", config, source_hint)                        │
│     2. Resolver maps "hooks-otel" → installed package path                   │
│     3. Loader finds entry point: amplifier.modules → hooks-otel              │
│     4. Entry point resolves to: amplifier_module_hooks_otel:mount            │
│                                                                              │
│ Why needed:                                                                  │
│   The kernel provides the MODULE LOADING MECHANISM. It uses Python's         │
│   entry_points system to discover the mount() function. This decouples       │
│   the module name from its implementation - you can swap implementations     │
│   without changing bundle configuration.                                     │
│                                                                              │
│ Code path: session.py:250-269 → loader.py:228 → loader.py:266                │
│                                                                              │
│ Entry point lookup:                                                          │
│   [project.entry-points."amplifier.modules"]                                 │
│   hooks-otel = "amplifier_module_hooks_otel:mount"                           │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: HOOK MODULE'S mount() IS CALLED                                      │
│ Component: amplifier-module-hooks-otel (this module)                         │
│                                                                              │
│ What happens:                                                                │
│   • Kernel calls: await mount(coordinator, config)                           │
│   • Hook reads config (exporter, endpoint, service_name, etc.)               │
│   • Hook creates OTelHook instance with configured exporters                 │
│   • Hook registers handlers for each event it wants to observe               │
│                                                                              │
│ Why needed:                                                                  │
│   The hook module provides the BEHAVIOR. It decides what to do when events   │
│   occur. The mount() function is the hook's opportunity to set up and        │
│   register for the events it cares about.                                    │
│                                                                              │
│ Code path: __init__.py:1049 (mount function)                                 │
│                                                                              │
│ Code example:                                                                │
│   async def mount(coordinator, config):                                      │
│       hook = OTelHook(OTelConfig.from_dict(config))                          │
│       coordinator.hooks.register("session:start", hook.on_session_start)     │
│       coordinator.hooks.register("llm:request", hook.on_llm_request)         │
│       # ... register for all 26 kernel events                                │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: HOOK REGISTERS EVENT HANDLERS                                        │
│ Component: amplifier-core (HookRegistry)                                     │
│                                                                              │
│ What happens:                                                                │
│   • coordinator.hooks.register(event, handler, priority, name)               │
│   • HookRegistry stores handler in _handlers[event] list                     │
│   • Handlers are sorted by priority (lower = called earlier)                 │
│   • Returns unregister function for cleanup                                  │
│                                                                              │
│ Why needed:                                                                  │
│   The kernel's HookRegistry is the EVENT DISPATCH MECHANISM. It maintains    │
│   a mapping of event → handlers and ensures handlers are called in priority  │
│   order. Multiple hooks can register for the same event.                     │
│                                                                              │
│ Code path: hooks.py:54-86                                                    │
│                                                                              │
│ Registry state after mount:                                                  │
│   _handlers = {                                                              │
│     "session:start": [HookHandler(on_session_start, priority=5)],            │
│     "llm:request": [HookHandler(on_llm_request, priority=5)],                │
│     "tool:pre": [HookHandler(on_tool_pre, priority=5)],                      │
│     ...                                                                      │
│   }                                                                          │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: EVENTS FLOW DURING EXECUTION                                         │
│ Component: amplifier-core (orchestrator emits) → hooks-otel (receives)       │
│                                                                              │
│ What happens:                                                                │
│   • Orchestrator runs the agent loop (LLM → tools → response)                │
│   • At each lifecycle point, kernel emits events:                            │
│     - await hooks.emit("session:start", {session_id, ...})                   │
│     - await hooks.emit("llm:request", {model, messages, ...})                │
│     - await hooks.emit("tool:pre", {tool_name, arguments, ...})              │
│   • HookRegistry calls all registered handlers for each event                │
│   • hooks-otel handlers create OTel spans and record metrics                 │
│                                                                              │
│ Why needed:                                                                  │
│   This is the RUNTIME OBSERVATION. The kernel emits events as a MECHANISM;   │
│   the hook decides POLICY (what to record, where to send). Multiple hooks    │
│   can observe the same events without interfering with each other.           │
│                                                                              │
│ Event flow example:                                                          │
│   1. User sends prompt                                                       │
│   2. Kernel emits "session:start" → hooks-otel creates root span             │
│   3. Orchestrator calls LLM                                                  │
│   4. Kernel emits "llm:request" → hooks-otel creates GenAI span              │
│   5. LLM responds with tool call                                             │
│   6. Kernel emits "tool:pre" → hooks-otel creates tool span                  │
│   7. Tool executes                                                           │
│   8. Kernel emits "tool:post" → hooks-otel ends tool span with result        │
│   9. ... continues until session ends ...                                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities Summary

| Component | Layer | Responsibility | Why Separated |
|-----------|-------|----------------|---------------|
| **amplifier-app-cli** | Application | Config resolution, bundle selection, user interaction | Policy decisions (which bundle, which settings) |
| **amplifier-foundation** | Library | Bundle composition, module activation, session creation helpers | Convenience layer (downloading, caching, resolving) |
| **amplifier-core** | Kernel | Module loading loop, event emission, hook registry | Mechanism layer (how to load, how to dispatch) |
| **hooks-otel** | Module | Event handlers, OTel span/metric creation | Behavior layer (what to do with events) |

### Why This Architecture?

**Separation of Concerns:**
- CLI doesn't know about OTel
- Kernel doesn't know about bundles
- Hook doesn't know about config resolution
- Each layer has a single responsibility

**Pluggability:**
- Swap hooks without changing CLI or kernel
- Swap exporters without changing hook registration
- Swap bundles without changing module implementations

**Testability:**
- Test hook in isolation with mock coordinator
- Test CLI with mock bundles
- Test kernel with mock modules

### Step 1: Install the Package

```bash
# Install from GitHub
uv add git+https://github.com/colombod/amplifier-module-hooks-otel

# Or for development
git clone https://github.com/colombod/amplifier-module-hooks-otel
uv add -e ./amplifier-module-hooks-otel
```

This registers the entry point in Python's package metadata:
```toml
# pyproject.toml (already configured)
[project.entry-points."amplifier.modules"]
hooks-otel = "amplifier_module_hooks_otel:mount"
```

### Step 2: Configure the Hook

There are three ways to configure the hook:

#### Option A: Bundle Behavior (Recommended)

Create a reusable behavior for your bundle:

```yaml
# behaviors/otel.yaml
bundle:
  name: behavior-otel
  version: 1.0.0
  description: OpenTelemetry observability

hooks:
  - module: hooks-otel
    config:
      service_name: my-amplifier-app
      exporter: otlp-http
      endpoint: http://localhost:4318
```

Include in your bundle:
```yaml
# bundle.md frontmatter
includes:
  - bundle: foundation
  - bundle: my-bundle:behaviors/otel
```

#### Option B: Direct in Bundle

Add directly to your bundle's frontmatter:

```yaml
# bundle.md
hooks:
  - module: hooks-otel
    config:
      service_name: my-app
      exporter: console
```

#### Option C: Settings File (Environment-Specific)

For environment-specific configuration (overrides bundle defaults):

```yaml
# ~/.amplifier/settings.yaml
hooks:
  - module: hooks-otel
    config:
      endpoint: ${OTEL_EXPORTER_OTLP_ENDPOINT}
      headers:
        Authorization: Bearer ${OTEL_AUTH_TOKEN}
```

#### Option D: Git Source (Auto-Install)

Let Amplifier install the module automatically:

```yaml
hooks:
  - module: hooks-otel
    source: git+https://github.com/colombod/amplifier-module-hooks-otel@main
    config:
      service_name: my-app
```

## Configuration Reference

Full configuration options:

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
| `sensitive_data.filter_sensitive_data` | bool | `true` | **Master filter switch - ON by default for privacy** |
| `sensitive_data.filter_llm_content` | bool | `true` | Filter LLM request/response content |
| `sensitive_data.filter_user_input` | bool | `true` | Filter user prompts |
| `sensitive_data.filter_tool_parameters` | bool | `true` | Filter tool input arguments |
| `sensitive_data.filter_tool_results` | bool | `true` | Filter tool output/results |
| `sensitive_data.filter_error_messages` | bool | `true` | Filter detailed error messages |

### Sensitive Data Filtering (Privacy Protection)

**By default, sensitive data filtering is ENABLED** to protect privacy and ensure telemetry is safe for production use.

When filtering is enabled (default), the following data is **NOT sent** to telemetry:
- LLM responses (content)
- User inputs/prompts (content)
- Tool parameters/arguments
- Tool results/outputs
- Detailed error messages

What **IS still captured** (safe for telemetry):
- Timings and durations
- Tool names (which tool was called)
- Token counts (input/output)
- Event types and lifecycle
- Session/turn metadata
- Error types (not messages with sensitive content)
- Model and provider names
- Success/failure status

#### Configuration Examples

**Default (filtering ON - recommended for production):**
```yaml
hooks:
  - module: hooks-otel
    config:
      service_name: my-app
      exporter: otlp-http
      # sensitive_data filtering is ON by default
```

**Explicit filtering configuration:**
```yaml
hooks:
  - module: hooks-otel
    config:
      service_name: my-app
      sensitive_data:
        filter_sensitive_data: true    # Master switch (default: true)
        filter_llm_content: true       # Filter LLM content
        filter_user_input: true        # Filter user prompts
        filter_tool_parameters: true   # Filter tool inputs
        filter_tool_results: true      # Filter tool outputs
        filter_error_messages: true    # Filter error details
```

**Disable filtering (development/debugging only):**
```yaml
hooks:
  - module: hooks-otel
    config:
      service_name: my-dev-app
      sensitive_data:
        filter_sensitive_data: false   # WARNING: Captures all data!
```

**Granular control (allow some data types):**
```yaml
hooks:
  - module: hooks-otel
    config:
      service_name: my-app
      sensitive_data:
        filter_sensitive_data: true
        filter_tool_parameters: false  # Allow tool inputs (e.g., file paths)
        filter_tool_results: true      # Still filter outputs
        filter_error_messages: false   # Allow error messages for debugging
```

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
| `amplifier.bundle.used` | Counter | `{bundle}` | Number of times a bundle is used |

> **Bundle Tracking**: Applications can emit bundle telemetry using the public API.
> See [Application Integration](#application-integration) for usage.
> Local paths are automatically sanitized to `"local"` for privacy; git URLs are preserved.

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

## Application Integration

Applications (like `amplifier-app-cli`) can emit bundle telemetry by importing the public API:

```python
from amplifier_module_hooks_otel import telemetry

# When a bundle is added (e.g., `amplifier bundle add`)
telemetry.bundle_added(
    name="my-bundle",
    source="git+https://github.com/org/my-bundle",
    version="1.0.0",
)

# When a bundle is activated (e.g., `amplifier bundle use`)
telemetry.bundle_activated(
    name="my-bundle",
    source="git+https://github.com/org/my-bundle",
)

# When a bundle is loaded from cache/disk
telemetry.bundle_loaded(
    name="foundation",
    source="git+https://github.com/microsoft/amplifier-foundation",
    cached=True,
)
```

### Privacy Protection

Local paths are automatically sanitized:

```python
# Git URLs are preserved (public)
telemetry.bundle_added(name="x", source="git+https://github.com/org/repo")
# → source recorded as "git+https://github.com/org/repo"

# Local paths become "local" (privacy)
telemetry.bundle_added(name="x", source="/home/user/private-bundle")
# → source recorded as "local"
```

### Graceful Degradation

If the OTel hook is not mounted, these functions safely no-op:

```python
# Safe to call even if OTel is not configured
telemetry.bundle_added(name="test")  # No-op, no error

# Check if telemetry is active
if telemetry.is_initialized():
    # OTel is configured and ready
    pass
```

## License

MIT

# RFC-0015: Progress Event Protocol

**RFC**: 0015
**Title**: Progress Event Protocol
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-20
**Updated**: 2026-03-27
**Dependencies**: RFC-0003, RFC-0013

## Abstract

This RFC defines a typed, registry-based progress event protocol for Soothe's `soothe.*` custom event system. It introduces a domain-tiered naming hierarchy (`soothe.<domain>.<component>.<action>`), typed event models, O(1) registry dispatch, and a unified renderer protocol. The design replaces the current ad-hoc `dict[str, Any]` events, duplicated if-elif rendering chains, and inconsistent naming conventions with a single-source-of-truth event catalog that is type-safe, extensible, and structurally classifiable.

## Motivation

Progress events are the sole mechanism for protocol orchestration observability between the Soothe daemon/runner and CLI/TUI consumers. The current implementation suffers from ten systemic drawbacks:

### D1. No type safety

Events are `dict[str, Any]` with magic string keys. A typo in `"soothe.plan.step_starrted"` is silently ignored. `core/events.py` defines constants for only 13 of 70+ distinct event types; the rest are inline string literals scattered across 10+ files.

### D2. O(n) if-elif dispatch

`progress_renderer.py` uses ~30 if-elif branches (209 lines). `renderers.py` uses ~25 branches in `_handle_protocol_event`, ~12 in `_handle_subagent_progress`, and ~10 in `_handle_subagent_custom`. Every event traverses a linear scan.

### D3. Quadruple-duplicated rendering logic

The same event types are independently handled in four consumer locations:
- `cli/rendering/progress_renderer.py` (headless CLI stderr)
- `cli/tui/renderers.py` (TUI activity panel via Rich Text)
- `cli/execution/daemon_runner.py` (daemon headless, ad-hoc for `final_report`/`chitchat`)
- `cli/execution/standalone_runner.py` (standalone headless, same ad-hoc)

Each has its own formatting. For example, `soothe.browser.step` is rendered three different ways.

### D4. No single source of truth

Event type strings are scattered across `core/events.py`, `_runner_phases.py`, `_runner_steps.py`, `_runner_autonomous.py`, `_runner_checkpoint.py`, `subagents/browser.py`, `subagents/claude.py`, `subagents/weaver/`, `subagents/skillify/`, `subagents/research/`, `tools/_internal/wizsearch/`, and `utils/tool_logging.py`.

### D5. No payload validation

Missing required fields silently produce broken rendering. `soothe.plan.step_started` expects `step_id` but nothing enforces it at emission time.

### D6. Inconsistent naming

- Subagent tools: `soothe.{agent}.tool_start` vs main agent: `soothe.tool.{name}.started`
- Tense inconsistency: `projected` vs `started` vs `step_completed` in the same domain
- `soothe.chitchat.*`, `soothe.autonomous.*` are undocumented in RFC-0003

### D7. Closed taxonomy

Adding a new event requires modifying the emitter, `progress_renderer.py`, `renderers.py`, and `progress_verbosity.py`'s prefix sets. No open extension mechanism exists.

### D8. No event versioning

No mechanism to add or rename fields without breaking all consumers simultaneously.

### D9. Fragile verbosity classification

`classify_custom_event()` uses hardcoded `_SUBAGENT_PREFIXES` sets and string heuristics (`"thinking" in etype`). New subagents or protocols must be manually added.

### D10. Duplicated event construction

`_runner_phases.py` builds a full plan-created dict inline (15 lines). `tool_logging.py` repeats nearly identical emit blocks four times (120 lines of boilerplate). No builder helpers exist.

## Design Principles

### Principle 1: Structural classification via naming

The event type string itself encodes the classification domain. No runtime heuristics or hardcoded prefix sets are needed — `event_type.split(".")[1]` yields the domain.

### Principle 2: Single source of truth

Every event type is defined exactly once in a central catalog module. Emission sites import typed constructors; consumer sites import handler registrations. No inline string literals for event types.

### Principle 3: Type-safe emission and consumption

Event payloads are validated at construction time via Pydantic models. Missing required fields raise immediate errors at the emission site, not silent rendering failures downstream.

### Principle 4: O(1) dispatch

Consumers use a `dict[str, Handler]` registry instead of if-elif chains. Handler lookup is constant-time. Unknown event types fall through to a default handler.

### Principle 5: Open for extension, closed for modification

Adding a new event type requires only: (1) define the model in the catalog, (2) register handler(s). No existing consumer code is modified. The registry is append-only.

### Principle 6: Render once, display anywhere

Each event type defines a single canonical summary extraction. Renderers (CLI, TUI, JSONL) differ only in formatting/styling, not in field extraction or message composition.

### Principle 7: Wire-format backward compatibility

The JSON wire format is unchanged: `{"type": "soothe.xxx.yyy.zzz", ...fields}`. Typed models serialize to the same dict shape via `.model_dump()`. The IPC protocol (RFC-0013) is unaffected.

## Prefix Hierarchy

### Current state: flat namespace

All events share `soothe.<something>.*` with 14+ distinct second-level segments. Protocols (`soothe.context.*`), subagents (`soothe.browser.*`), lifecycle (`soothe.thread.*`), tools (`soothe.tool.*`), and output (`soothe.chitchat.*`) sit at the same level. Classification requires hardcoded prefix sets in `classify_custom_event()`.

Subagent tool events use a completely different pattern from main agent tools:
- Main agent: `soothe.tool.{name}.started` / `.completed` / `.failed`
- Subagent: `soothe.{agent}.tool_start` / `.tool_end` / `.tool_error`

### Proposed: 4-segment `soothe.<domain>.<component>.<action>`

A mandatory **domain** tier is introduced as the second segment.

```
soothe.<domain>.<component>.<action>
  │       │         │          │
  │       │         │          └── past-participle verb (created, started, completed, failed, ...)
  │       │         └── protocol name, subagent name, or tool name
  │       └── one of: lifecycle, protocol, tool, subagent, output, error
  └── fixed prefix
```

#### Domain definitions

| Domain | Purpose | Default Verbosity |
|--------|---------|-------------------|
| `lifecycle` | Thread creation/resume/save, iteration start/end, checkpoint, recovery | `normal` |
| `protocol` | Core protocol activity: context, memory, plan, policy, goal | `normal` |
| `tool` | Main agent tool execution lifecycle | `normal` |
| `subagent` | All subagent activity: browser, research, claude, skillify, weaver, planner tool calls, scout tool calls | `detailed` (promoted key events at `normal`) |
| `output` | Content destined for user display: chitchat responses, final reports, subagent text/response | `normal` |
| `error` | Error events | always shown |

#### Classification rule

```python
def classify_event(event_type: str) -> str:
    segments = event_type.split(".")
    if len(segments) >= 2:
        return segments[1]  # lifecycle, protocol, tool, subagent, output, error
    return "unknown"
```

No prefix sets. No string heuristics. Structural by construction.

### Naming conventions

#### Action suffixes

All action suffixes use past participle for state changes and observations:

| Category | Suffixes |
|----------|----------|
| Lifecycle transitions | `created`, `started`, `resumed`, `saved`, `ended`, `completed` |
| Activity lifecycle | `started`, `completed`, `failed` |
| Protocol observations | `projected`, `recalled`, `ingested`, `stored`, `checked`, `denied`, `reflected` |

#### Component names

Components use the existing protocol or subagent name in snake_case: `thread`, `context`, `memory`, `plan`, `policy`, `goal`, `iteration`, `checkpoint`, `recovery`, `browser`, `research`, `claude`, `skillify`, `weaver`, `planner`, `scout`, `chitchat`, `autonomous`.

For dynamic main-agent tools, `<component>` is the tool name: `soothe.tool.search.started`, `soothe.tool.read_file.completed`.

#### Subagent tool events

Subagent tool events are unified under a consistent pattern:

```
soothe.subagent.<agent>.tool_started
soothe.subagent.<agent>.tool_completed
soothe.subagent.<agent>.tool_failed
```

This replaces the current inconsistent `soothe.{agent}.tool_start` / `tool_end` / `tool_error` and aligns suffixes with the main agent tool pattern.

### Migration mapping

All current events migrate to the new domain-prefixed naming. Key patterns:

**Lifecycle**: `soothe.thread.*` → `soothe.lifecycle.thread.*`, `soothe.iteration.*` → `soothe.lifecycle.iteration.*`

**Protocol**: `soothe.context.*` → `soothe.protocol.context.*`, `soothe.memory.*` → `soothe.protocol.memory.*`, `soothe.plan.*` → `soothe.protocol.plan.*`, `soothe.policy.*` → `soothe.protocol.policy.*`, `soothe.goal.*` → `soothe.protocol.goal.*`

**Tool**: Largely unchanged (`soothe.tool.{name}.*`)

**Subagent**: `soothe.browser.*` → `soothe.subagent.browser.*`, `soothe.claude.*` → `soothe.subagent.claude.*`, `soothe.research.*` → `soothe.subagent.research.*`, `soothe.skillify.*` → `soothe.subagent.skillify.*`, `soothe.weaver.*` → `soothe.subagent.weaver.*`

**Subagent tool events**: `soothe.{agent}.tool_start` → `soothe.subagent.{agent}.tool_started` (unified suffix pattern)

**Output**: `soothe.chitchat.*` → `soothe.output.chitchat.*`, `soothe.autonomous.final_report` → `soothe.output.autonomous.final_report`

**Error**: `soothe.error` → `soothe.error.general`

Subagent events with 5-segment depth (e.g., `soothe.skillify.retrieve.started`) are flattened to 4 segments using underscores: `soothe.subagent.skillify.retrieve_started`.

## Architecture

### Event model hierarchy

All events inherit from `SootheEvent` (Pydantic `BaseModel`) with domain-specific base classes:

```
SootheEvent (BaseModel)
├── LifecycleEvent      — Thread and session lifecycle
├── ProtocolEvent       — Core protocol activity
├── ToolEvent           — Main agent tool execution (includes tool: str field)
├── SubagentEvent       — Subagent activity
├── OutputEvent         — Content for user display
└── ErrorEvent          — Error events (includes error: str field)
```

### Base event model

```python
class SootheEvent(BaseModel):
    """Base class for all Soothe progress events."""
    type: str

    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
```

The `extra="allow"` policy permits forward-compatible consumption. Each concrete event class uses `Literal` type for the `type` field (e.g., `type: Literal["soothe.protocol.plan.step_started"]`).

### Example concrete models

```python
class PlanStepStartedEvent(ProtocolEvent):
    type: Literal["soothe.protocol.plan.step_started"] = "soothe.protocol.plan.step_started"
    step_id: str
    description: str
    depends_on: list[str] = []
    batch_index: int | None = None

class ToolStartedEvent(ToolEvent):
    type: str  # Dynamic: "soothe.tool.{name}.started"
    tool: str
    args: str = ""
    kwargs: str = ""
```

### Event catalog and registry

A central catalog module (`core/event_catalog.py`) serves as the single source of truth:

```python
@dataclass(frozen=True)
class EventMeta:
    """Metadata for a registered event type."""
    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: ProgressCategory
    summary_template: str

class EventRegistry:
    """Central registry for all Soothe event types."""

    def register(self, meta: EventMeta) -> None: ...
    def get_meta(self, event_type: str) -> EventMeta | None: ...
    def classify(self, event_type: str) -> str: ...
    def get_verbosity(self, event_type: str) -> ProgressCategory: ...
    def on(self, event_type: str, handler: EventHandler) -> None: ...
    def dispatch(self, event: dict[str, Any]) -> None: ...

REGISTRY = EventRegistry()
```

The registry provides O(1) dispatch via `dict[str, EventMeta]` lookup, replacing if-elif chains. Domain default verbosity is configured in `_DOMAIN_DEFAULT_VERBOSITY`.

### Event emission

Emission sites use typed constructors instead of raw dicts:

```python
# Before (current):
yield _custom({"type": "soothe.plan.step_started", "step_id": s.id, "description": s.description})

# After (proposed):
yield _custom(PlanStepStartedEvent(step_id=s.id, description=s.description).to_dict())
```

For convenience, an `emit()` helper is provided on the base model:

```python
class SootheEvent(BaseModel):
    def emit(self, logger: logging.Logger) -> None:
        from soothe.utils.progress import emit_progress
        emit_progress(self.to_dict(), logger)
```

### Renderer protocol

A unified renderer protocol replaces the duplicated if-elif rendering logic:

```python
class EventRenderer(Protocol):
    """Protocol for rendering progress events."""

    def render(self, event: dict[str, Any], *, verbosity: VerbosityLevel = "normal") -> None:
        ...
```

Three implementations:

1. **`CliEventRenderer`** — replaces `progress_renderer.py`. Writes formatted text to stderr.
2. **`TuiEventRenderer`** — replaces `_handle_protocol_event`, `_handle_subagent_progress`, `_handle_subagent_custom` in `renderers.py`. Produces Rich `Text` objects for the activity panel.
3. **`JsonlEventRenderer`** — passthrough for `--format jsonl` mode.

Each renderer uses registry-based dispatch internally:

```python
class CliEventRenderer:
    def __init__(self, registry: EventRegistry) -> None:
        self._registry = registry
        self._handlers: dict[str, Callable] = {}
        self._register_handlers()

    def render(self, event: dict[str, Any], *, verbosity: VerbosityLevel = "normal") -> None:
        etype = event.get("type", "")
        meta = self._registry.get_meta(etype)
        if meta and not should_show(meta.verbosity, verbosity):
            return
        handler = self._handlers.get(etype, self._default_handler)
        handler(event)

    def _default_handler(self, event: dict[str, Any]) -> None:
        etype = event.get("type", "")
        domain = self._registry.classify(etype)
        tag = etype.split(".")[-2] if len(etype.split(".")) >= 3 else domain
        summary = self._extract_summary(event)
        sys.stderr.write(f"[{tag}] {summary}\n")
        sys.stderr.flush()
```

### Summary extraction

Each event registration includes a `summary_template` that defines how to extract a human-readable one-liner:

```python
EventMeta(
    type_string="soothe.protocol.plan.step_started",
    model=PlanStepStartedEvent,
    domain="protocol",
    component="plan",
    action="step_started",
    verbosity="protocol",
    summary_template="Step {step_id}: {description}",
)
```

The renderer evaluates the template against the event dict using `str.format_map()`. For events that need custom logic (e.g., conditional fields), the handler can override the template.

### Data flow

```
Emission Site                    Registry                    Consumer
─────────────                    ────────                    ────────
PlanStepStartedEvent(            REGISTRY.get_meta(          CliEventRenderer.render(
  step_id="s1",        ──to_dict()──>  "soothe.protocol.    ──dispatch──>  handler(event)
  description="..."               plan.step_started")          │
)                                   │                          ├─ template: "Step {step_id}: {description}"
                                    ├─ verbosity: "protocol"   ├─ should_show(verbosity)?
                                    └─ domain: "protocol"      └─ sys.stderr.write("[plan] Step s1: ...")
```

### Verbosity integration

The registry replaces `classify_custom_event()` entirely:

```python
def should_render(event_type: str, verbosity: VerbosityLevel) -> bool:
    category = REGISTRY.get_verbosity(event_type)
    return should_show(category, verbosity)
```

Promoted subagent events (visible at `normal` verbosity) are registered with `verbosity="subagent_progress"` instead of the domain default `"subagent_custom"`.

## Event Catalog

The complete event catalog with all event types, fields, and verbosity classifications is maintained in [event-catalog.md](event-catalog.md).

### Event domains

| Domain | Purpose | Default Verbosity |
|--------|---------|-------------------|
| `lifecycle` | Thread creation/resume/save, iteration start/end, checkpoint, recovery | `protocol` |
| `protocol` | Core protocol activity: context, memory, plan, policy, goal | `protocol` |
| `tool` | Main agent tool execution lifecycle | `tool_activity` |
| `subagent` | All subagent activity: browser, research, claude, skillify, weaver | `subagent_custom` (promoted key events at `subagent_progress`) |
| `output` | Content destined for user display: chitchat responses, final reports | `assistant_text` |
| `error` | Error events | `error` (always shown) |

## Event Access

### Real-time streaming

Real-time event streaming uses WebSocket or Unix socket transports as defined in RFC-0013. Events are streamed immediately as they occur during agent execution.

### Historical access

Historical events can be retrieved via the REST API endpoint:

```http
GET /api/v1/threads/{thread_id}/messages
```

This endpoint supports filtering by `kind`, `type`, and time range. See RFC-0013 for complete REST API specification.

### Event classification

Events are classified by domain (second segment of type string):

```python
def classify_event(event_type: str) -> str:
    segments = event_type.split(".")
    return segments[1] if len(segments) >= 2 else "unknown"
```

Classification values: `lifecycle`, `protocol`, `tool`, `subagent`, `output`, `error`

## Backward Compatibility

### Wire format

The JSON wire format is unchanged. Events are `{"type": "...", ...fields}` dicts. The IPC protocol (RFC-0013) event message wrapping is unaffected. Typed models serialize to the same dict shape via `model_dump(exclude_none=True)`.

### Migration strategy

Migration uses a staged approach:

**Phase 1: Catalog and registry (non-breaking)**
- Create `core/event_catalog.py` with all event models and registry
- Event models accept both old and new type strings during transition
- Emit new-format strings from emission sites
- Consumer registrations handle both formats

**Phase 2: Consumer migration**
- Replace if-elif chains in renderers with registry dispatch
- `CliEventRenderer` replaces `progress_renderer.py`
- `TuiEventRenderer` replaces `_handle_protocol_event`, `_handle_subagent_progress`, `_handle_subagent_custom`
- `classify_custom_event()` delegates to `REGISTRY.classify()`

**Phase 3: Cleanup**
- Remove old `core/events.py` constants (superseded by catalog)
- Remove `_SUBAGENT_PREFIXES` and `_PROTOCOL_PREFIXES` sets
- Remove deprecated if-elif rendering functions

### Versioning

Event models support forward compatibility via `extra="allow"` in the Pydantic config. Consumers ignore unknown fields. If a field is renamed, both old and new names can coexist during transition via field aliases.

## Architectural Constraints

1. **All events MUST use the 4-segment type string** `soothe.<domain>.<component>.<action>` with the exception of dynamic tool events which may have the tool name as the component.
2. **All event types MUST be registered** in the central catalog before emission.
3. **Consumers MUST NOT match event types with if-elif chains**; registry dispatch is mandatory.
4. **Event models MUST validate required fields** at construction time.
5. **The wire format MUST remain JSON dicts** for IPC compatibility.
6. **New subagents automatically get the `soothe.subagent.<name>.*` prefix** without modifying any consumer code.

## Dependencies

- RFC-0003 (CLI TUI Architecture Design — current event taxonomy)
- RFC-0013 (Unified Daemon Communication Protocol — IPC message wrapping)

## Related Documents

- [RFC-0003](./RFC-0003.md) — CLI TUI Architecture Design (superseded for event schema; retains TUI layout, daemon architecture)
- [RFC-0013](./RFC-0013.md) — Unified Daemon Communication Protocol
- [RFC Index](./rfc-index.md) — All RFCs

---

*This RFC supersedes the "Protocol custom events" table in RFC-0003 Section "Stream Architecture" for event type definitions, naming conventions, and schema specifications. RFC-0003 retains ownership of TUI layout, daemon architecture, stream format, and IPC protocol.*

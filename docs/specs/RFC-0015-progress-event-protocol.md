# RFC-0015: Progress Event Protocol

**RFC**: 0015
**Title**: Progress Event Protocol
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-20
**Updated**: 2026-03-29
**Dependencies**: RFC-0003, RFC-0013, RFC-0024

## Abstract

This RFC defines a typed, registry-based progress event protocol for Soothe's `soothe.*` custom event system. It introduces a domain-tiered naming hierarchy (`soothe.<domain>.<component>.<action>`), typed event models, O(1) registry dispatch, and unified renderer protocol. The design replaces ad-hoc `dict[str, Any]` events, duplicated if-elif rendering chains, and inconsistent naming with a single-source-of-truth event catalog that is type-safe, extensible, and structurally classifiable.

## Problem Statement

Current implementation has ten systemic issues:

1. **No type safety** - Events are `dict[str, Any]`, typos silently ignored, only 13 of 70+ event types have constants
2. **O(n) dispatch** - ~30 if-elif branches in `progress_renderer.py`, ~25 in `renderers.py`, linear scans
3. **Quadruple-duplicated logic** - Same events handled independently in 4 locations with inconsistent formatting
4. **No single source of truth** - Event strings scattered across 10+ files
5. **No payload validation** - Missing fields cause silent rendering failures
6. **Inconsistent naming** - `soothe.{agent}.tool_start` vs `soothe.tool.{name}.started`, tense inconsistency
7. **Closed taxonomy** - Adding events requires modifying emitters, renderers, verbosity classification
8. **No versioning** - No mechanism for backward-compatible field changes
9. **Fragile classification** - Hardcoded prefix sets and string heuristics
10. **Duplicated construction** - 120 lines of boilerplate in `tool_logging.py`

## Design Principles

1. **Structural classification** - Event type encodes domain: `event_type.split(".")[1]`
2. **Single source of truth** - Central catalog, no inline string literals
3. **Type-safe emission** - Pydantic models validate at construction
4. **O(1) dispatch** - Registry lookup, not if-elif chains
5. **Open extension** - Add events without modifying consumers
6. **Render once** - Single summary extraction, multiple display formats
7. **Wire-format compatible** - Unchanged JSON: `{"type": "...", ...fields}`

## Prefix Hierarchy

### Current: Flat Namespace

`soothe.<something>.*` with 14+ second-level segments. Different patterns for subagent tools vs main agent tools. Classification requires hardcoded prefix sets.

### Proposed: 4-Segment `soothe.<domain>.<component>.<action>`

```
soothe.<domain>.<component>.<action>
  │       │         │          │
  │       │         │          └── past-participle (created, started, completed, failed)
  │       │         └── protocol/subagent/tool name
  │       └── lifecycle, protocol, tool, subagent, output, error
  └── fixed prefix
```

### Domain Definitions

| Domain | Purpose | Default Tier |
|--------|---------|--------------|
| `lifecycle` | Thread/session/iteration/checkpoint/recovery | DETAILED |
| `protocol` | Context/memory/plan/policy/goal | DETAILED |
| `tool` | Main agent tool execution | DETAILED |
| `subagent` | Browser/research/claude/skillify/weaver | DETAILED (promoted key events: NORMAL) |
| `output` | Chitchat/final reports | QUIET |
| `error` | Error events | QUIET (always shown) |

**Classification**: `classify_event(event_type) = event_type.split(".")[1]`

### Naming Conventions

**Action suffixes**: `created`, `started`, `resumed`, `saved`, `completed`, `failed`, `projected`, `recalled`, `ingested`, `stored`, `checked`, `denied`, `reflected`

**Component names**: `thread`, `context`, `memory`, `plan`, `policy`, `goal`, `iteration`, `checkpoint`, `recovery`, `browser`, `research`, `claude`, `skillify`, `weaver`, `chitchat`

**Subagent tool events**: Unified as `soothe.subagent.<agent>.tool_started/completed/failed`

### Migration Mapping

**Lifecycle**: `soothe.thread.*` → `soothe.lifecycle.thread.*`

**Protocol**: `soothe.context.*` → `soothe.protocol.context.*`, `soothe.plan.*` → `soothe.cognition.plan.*`

**Tool**: Largely unchanged (`soothe.tool.{name}.*`)

**Subagent**: `soothe.browser.*` → `soothe.subagent.browser.*`

**Output**: `soothe.chitchat.*` → `soothe.output.chitchat.*`

**Subagent tools**: `soothe.{agent}.tool_start` → `soothe.subagent.{agent}.tool_started`

## Architecture

### Event Model Hierarchy

```
SootheEvent (BaseModel)
├── LifecycleEvent
├── ProtocolEvent
├── ToolEvent (includes tool: str)
├── SubagentEvent
├── OutputEvent
└── ErrorEvent (includes error: str)
```

### Base Event Model

```python
class SootheEvent(BaseModel):
    type: str
    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def emit(self, logger: logging.Logger) -> None:
        emit_progress(self.to_dict(), logger)
```

### Event Catalog & Registry

```python
@dataclass(frozen=True)
class EventMeta:
    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: VerbosityTier
    summary_template: str

class EventRegistry:
    def register(self, meta: EventMeta) -> None
    def get_meta(self, event_type: str) -> EventMeta | None
    def classify(self, event_type: str) -> str
    def get_verbosity(self, event_type: str) -> VerbosityTier
    def on(self, event_type: str, handler: EventHandler) -> None
    def dispatch(self, event: dict[str, Any]) -> None

REGISTRY = EventRegistry()
```

O(1) dispatch via dict lookup, domain default verbosity from RFC-0024.

### Event Emission

```python
# Before: yield _custom({"type": "soothe.plan.step_started", "step_id": s.id})
# After:  yield _custom(PlanStepStartedEvent(step_id=s.id, description=s.description).to_dict())
```

### Renderer Protocol

```python
class EventRenderer(Protocol):
    def render(self, event: dict[str, Any], *, verbosity: VerbosityLevel = "normal") -> None:
        """Render event with verbosity filtering."""

class CliEventRenderer:  # Replaces progress_renderer.py
    def render(self, event, *, verbosity="normal"):
        etype = event.get("type", "")
        meta = self._registry.get_meta(etype)
        if meta and not should_show(meta.verbosity, verbosity):  # RFC-0024
            return
        handler = self._handlers.get(etype, self._default_handler)
        handler(event)
```

**Implementations**: `CliEventRenderer` (stderr), `TuiEventRenderer` (Rich Text), `JsonlEventRenderer` (passthrough).

### Summary Extraction

Each registration includes `summary_template`:

```python
EventMeta(
    type_string="soothe.cognition.plan.step_started",
    model=PlanStepStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Step {step_id}: {description}",
)
```

Renderer evaluates template via `str.format_map()`.

### Data Flow

```
Emission Site → REGISTRY.get_meta() → Renderer.render() → should_show(verbosity) → handler(event)
                ├─ verbosity            ├─ template         ├─ integer comparison
                └─ domain               └─ extraction       └─ display
```

### Verbosity Integration

```python
def should_render(event_type: str, verbosity: VerbosityLevel) -> bool:
    tier = REGISTRY.get_verbosity(event_type)
    return should_show(tier, verbosity)  # tier <= verbosity
```

Replaces `classify_custom_event()` entirely. Promoted events registered with `VerbosityTier.NORMAL`.

## Event Catalog

Complete catalog maintained in [event-catalog.md](event-catalog.md).

### Event Domains

| Domain | Purpose | Default Tier |
|--------|---------|--------------|
| `lifecycle` | Thread/iteration/checkpoint | DETAILED |
| `protocol` | Context/memory/plan/policy/goal | DETAILED |
| `tool` | Main agent tools | DETAILED |
| `subagent` | Browser/research/claude/skillify/weaver | DETAILED (promoted: NORMAL) |
| `output` | Chitchat/final reports | QUIET |
| `error` | Errors | QUIET |

## Event Access

**Real-time**: WebSocket/Unix socket streaming (RFC-0013).

**Historical**: `GET /api/v1/threads/{thread_id}/messages` with filtering by `kind`, `type`, time range.

**Classification**: `classify_event(event_type) = event_type.split(".")[1]` → domain.

## Backward Compatibility

### Wire Format

Unchanged JSON: `{"type": "...", ...fields}`. Models serialize via `model_dump(exclude_none=True)`.

### Migration Strategy

**Phase 1** (Non-breaking): Create catalog/registry, emit new-format strings, consumers handle both formats.

**Phase 2**: Replace if-elif chains with registry dispatch, `CliEventRenderer`/`TuiEventRenderer` replace old renderers.

**Phase 3**: Remove old constants, prefix sets, deprecated functions.

### Versioning

Forward compatibility via `extra="allow"`. Field renames use aliases during transition.

## Architectural Constraints

1. All events MUST use 4-segment type string `soothe.<domain>.<component>.<action>`
2. All event types MUST be registered in catalog before emission
3. Consumers MUST use registry dispatch, not if-elif chains
4. Event models MUST validate required fields at construction
5. Wire format MUST remain JSON dicts for IPC compatibility
6. New subagents automatically get `soothe.subagent.<name>.*` prefix

## References

- RFC-0003: CLI TUI Architecture (superseded for event schema)
- RFC-0013: Daemon Communication Protocol
- RFC-0024: VerbosityTier Unification

---

*Registry-based progress events with domain-tiered naming, type-safe models, O(1) dispatch.*
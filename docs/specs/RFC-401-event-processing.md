# RFC-401: Event Processing & Filtering

**RFC**: 451
**Status**: Implemented
**Authors**: Soothe Team
**Created**: 2026-03-31
**Last Updated**: 2026-04-17
**Depends on**: RFC-450 (Daemon Communication), `RFC-403-unified-event-naming.md` (Unified Event Naming), RFC-500 (CLI/TUI Architecture), RFC-502 (Unified Presentation Engine)
**Supersedes**: RFC-0015, RFC-0019, RFC-0022
**Kind**: Implementation Interface Design
**Legacy Note**: Daemon/event consolidation references this document alongside `RFC-450-daemon-communication-protocol.md` and `RFC-453.md`.

---

## 1. Abstract

This RFC defines the interface contracts for Soothe's event processing system, including the typed event protocol, unified event processor architecture, and daemon-side filtering. It consolidates the progress event protocol (RFC-0015), unified event processing (RFC-0019), and daemon-side filtering (RFC-0022) into a single implementation interface specification.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* Event model hierarchy and base classes
* Event registry interface for O(1) dispatch
* RendererProtocol for mode-agnostic display
* Daemon-side filtering protocol with verbosity integration
* EventProcessor unified processing architecture
* Integration boundary with PresentationEngine

**Note**: Event naming conventions and domain taxonomy are defined in RFC-402 (Unified Event Naming).

### 2.2 Non-Goals

This RFC does **not** define:

* Daemon transport layer (see RFC-400)
* CLI/TUI display implementation (see RFC-500)
* Specific event types (see event-catalog.md)
* VerbosityTier classification (see RFC-501)

---

## 3. Background & Motivation

### 3.1 Problems Solved

| Problem | Before | After |
|---------|--------|-------|
| Type safety | `dict[str, Any]`, typos silent | Pydantic models validate at construction |
| Dispatch performance | O(n) if-elif chains | O(1) registry lookup |
| Code duplication | 60% across CLI/TUI | 5% via RendererProtocol |
| Naming inconsistency | Mixed patterns | 4-segment hierarchy |
| Network overhead | All events sent | 60-70% filtered at daemon |

### 3.2 Design Goals

1. Structural classification via event type encoding
2. Single source of truth in central registry
3. Type-safe emission with Pydantic validation
4. Unified processing across CLI and TUI modes
5. Daemon-side filtering to reduce network overhead
6. Keep display strategy out of transport/event routing paths

---

## 4. Naming Conventions

Event naming semantics, including grammar rules, domain taxonomy, and approved vocabularies, are defined in **RFC-402 (Unified Event Naming)**.

This RFC references RFC-402 for:
* Event type hierarchy format: `soothe.<domain>.<component>.<action>`
* Domain definitions and scope
* Present progressive tense grammar rules
* Plugin extension namespace conventions
* Approved verb and state noun lists

For complete naming guidelines, migration rules, and validation criteria, see RFC-402.

---

## 5. Data Structures

### 5.1 Base Event Model

```python
class SootheEvent(BaseModel):
    type: str
    model_config = ConfigDict(extra="allow")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def emit(self, logger: logging.Logger) -> None:
        emit_progress(self.to_dict(), logger)
```

### 5.2 Event Model Hierarchy

```
SootheEvent (BaseModel)
├── LifecycleEvent
├── ProtocolEvent
├── ToolEvent (includes tool: str)
├── SubagentEvent
├── OutputEvent
└── ErrorEvent (includes error: str)
```

### 5.3 EventMeta

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
```

### 5.4 ProcessorState

```python
@dataclass
class ProcessorState:
    seen_message_ids: set[str] = field(default_factory=set)
    pending_tool_calls: dict[str, dict] = field(default_factory=dict)
    name_map: dict[str, str] = field(default_factory=dict)
    current_plan: Plan | None = None
    thread_id: str = ""
    multi_step_active: bool = False
```

### 5.5 ClientSession

```python
@dataclass
class ClientSession:
    client_id: str
    thread_id: str
    verbosity: VerbosityLevel = "normal"
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=100))
```

---

## 6. Interface Contracts

### 6.1 EventRegistry

```python
class EventRegistry:
    def register(self, meta: EventMeta) -> None:
        """Register event type with metadata."""
        ...

    def get_meta(self, event_type: str) -> EventMeta | None:
        """O(1) lookup of event metadata."""
        ...

    def classify(self, event_type: str) -> str:
        """Extract domain from event type."""
        return event_type.split(".")[1]

    def get_verbosity(self, event_type: str) -> VerbosityTier:
        """Get verbosity tier for event type."""
        ...

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register handler for event type."""
        ...

    def dispatch(self, event: dict[str, Any]) -> None:
        """Dispatch event to registered handler."""
        ...
```

### 6.2 RendererProtocol

```python
class RendererProtocol(Protocol):
    # Core callbacks (required)
    def on_assistant_text(
        self,
        text: str,
        *,
        is_main: bool,
        is_streaming: bool,
    ) -> None: ...

    def on_tool_call(
        self,
        name: str,
        args: dict,
        tool_call_id: str,
        *,
        is_main: bool,
    ) -> None: ...

    def on_tool_result(
        self,
        name: str,
        result: str,
        tool_call_id: str,
        *,
        is_error: bool,
        is_main: bool,
    ) -> None: ...

    def on_status_change(self, state: str) -> None: ...

    def on_error(self, error: str, *, context: str | None = None) -> None: ...

    def on_progress_event(
        self,
        event_type: str,
        data: dict,
        *,
        namespace: tuple[str, ...],
    ) -> None: ...

    # Optional fine-grained hooks
    def on_plan_created(self, plan: Plan) -> None: ...
    def on_plan_step_started(self, step_id: str, description: str) -> None: ...
    def on_plan_step_completed(
        self,
        step_id: str,
        success: bool,
        duration_ms: int,
    ) -> None: ...
    def on_turn_end(self) -> None: ...
```

### 6.3 EventProcessor

```python
class EventProcessor:
    def __init__(
        self,
        renderer: RendererProtocol,
        verbosity: VerbosityLevel = "normal",
    ) -> None: ...

    def process_event(self, event: dict[str, Any]) -> None:
        """Route event to appropriate renderer callback."""
        ...

    @property
    def thread_id(self) -> str: ...

    @property
    def current_plan(self) -> Plan | None: ...
```

EventProcessor responsibilities are limited to:

1. Parse incoming daemon stream envelopes (`status` / `event` / `error`).
2. Normalize message/custom payload shape.
3. Dispatch normalized data to renderer callbacks.

Display strategy responsibilities (dedup/rate-limit/summarization/icon policy)
belong to PresentationEngine (RFC-502), not EventProcessor.

### 6.4 EventBus

```python
class EventBus:
    async def publish(
        self,
        topic: str,
        event: dict[str, Any],
        event_meta: EventMeta | None = None,
    ) -> None:
        """Publish event to topic with optional metadata."""
        ...

    async def subscribe(
        self,
        topic: str,
        client_id: str,
        verbosity: VerbosityLevel = "normal",
    ) -> None: ...
```

### 6.5 Daemon Filtering Protocol

**Extended `subscribe_thread`**:

```json
{
  "type": "subscribe_thread",
  "thread_id": "string (required)",
  "verbosity": "string (optional: quiet|normal|detailed|debug, default: normal)"
}
```

**Extended `subscription_confirmed`**:

```json
{
  "type": "subscription_confirmed",
  "thread_id": "string",
  "client_id": "string",
  "verbosity": "string (echoes preference)"
}
```

---

## 7. Implementation Patterns

### 7.1 Event Registration

```python
register_event(
    PlanStepStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Step {step_id}: {description}",
)
```

### 7.2 Event Emission

```python
# Type-safe emission
emit_progress(
    PlanStepStartedEvent(
        step_id=step.id,
        description=step.description,
    ).to_dict(),
    logger,
)
```

### 7.3 Daemon Filtering Flow

```
Backend → EventBus.publish(event, event_meta) → _filter_and_enqueue
            │
            ▼
    should_show(event_meta.verbosity, session.verbosity)?
            │
    ┌───────┴───────┐
    │ Yes           │ No
    ▼               ▼
  Enqueue         Skip
    │
    ▼
  Transport → Client
```

### 7.4 Unified Processing

```python
# CLI mode
renderer = CliRenderer(verbosity="normal")
processor = EventProcessor(renderer, verbosity="normal")

# TUI mode
renderer = TuiRenderer(
    on_panel_write=panel.append_entry,
    on_status_update=update_status_bar,
)
processor = EventProcessor(renderer, verbosity="normal")

# Both use same processor
for event in event_stream:
    processor.process_event(event)
```

---

## 8. Abstract Schemas

### 8.1 VerbosityTier Values

| Tier | Value | Visible At |
|------|-------|------------|
| QUIET | 0 | All levels |
| NORMAL | 1 | normal, detailed, debug |
| DETAILED | 2 | detailed, debug |
| DEBUG | 3 | debug only |
| INTERNAL | 4 | Never displayed |

### 8.2 VerbosityLevel Values

| Level | Value | Events Shown |
|-------|-------|--------------|
| quiet | 0 | QUIET only (errors, outputs) |
| normal | 1 | QUIET + NORMAL |
| detailed | 2 | QUIET + NORMAL + DETAILED |
| debug | 3 | All except INTERNAL |

### 8.3 Filtering Efficiency

| Verbosity | Event Reduction |
|-----------|-----------------|
| quiet | ~90% |
| normal | ~60-70% |
| detailed | ~30-40% |
| debug | ~0% (all except INTERNAL) |

---

## 9. File Structure

```
src/soothe/
├── core/
│   └── event_catalog.py      # EventRegistry, register_event()
├── ux/
│   ├── core/
│   │   ├── renderer_protocol.py  # RendererProtocol
│   │   ├── processor_state.py    # ProcessorState
│   │   └── event_processor.py    # EventProcessor
│   ├── cli/
│   │   └── cli_renderer.py       # CliRenderer
│   └── tui/
│       └── tui_renderer.py       # TuiRenderer
└── daemon/
    ├── event_bus.py              # EventBus with metadata
    └── client_session.py         # ClientSession with verbosity
```

---

## 10. Examples

### 10.1 Adding New Event Type

```python
# In module events.py
class MyCustomEvent(SootheEvent):
    type: Literal["soothe.tool.my_tool.custom_action"] = "soothe.tool.my_tool.custom_action"
    data: str = ""

register_event(
    MyCustomEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Custom: {data}",
)

# Emission site
emit_progress(MyCustomEvent(data="example").to_dict(), logger)
```

### 10.2 Custom Renderer

```python
class LoggingRenderer:
    def on_assistant_text(self, text, *, is_main, is_streaming):
        logging.info(f"Assistant: {text}")

    def on_tool_call(self, name, args, tool_call_id, *, is_main):
        logging.info(f"Tool call: {name}({args})")

    # ... implement other callbacks

processor = EventProcessor(LoggingRenderer())
```

---

## 11. Relationship to Other RFCs

* **RFC-450 (Daemon Communication)**: Transport layer for events
* **RFC-500 (CLI/TUI Architecture)**: Renderer implementations
* **RFC-501 (Display & Verbosity)**: VerbosityTier classification
* **RFC-101 (Tool Interface)**: Tool event naming patterns
* **RFC-301 (Protocol Registry)**: Protocol event types

---

## 12. Open Questions

1. Should `register_event()` support versioning for backward-compatible field changes?
2. Should EventProcessor support async callbacks for TUI?
3. Per-thread verbosity preference in daemon?

---

## 13. Conclusion

This RFC unifies Soothe's event processing into a coherent architecture:

- Registry-based dispatch with O(1) lookup
- Type-safe Pydantic models for validation
- Unified EventProcessor across CLI and TUI
- Daemon-side filtering for 60-70% network reduction
- RendererProtocol for mode-agnostic display

> **Type-safe events, unified processing, filtered transport.**
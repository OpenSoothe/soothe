# Event System

Centralized event system infrastructure for Soothe.

---

## Overview

The event system (`soothe.core.events`) provides a centralized infrastructure for event management in Soothe. It includes event constants, models, registry, and a public API for event registration.

---

## Architecture

### Event System Components

```
Event System Architecture
├─ Event Constants (constants.py)
│  ├─ 60+ event type constants
│  ├─ Namespace-based organization
│  └─ Type-safe event identifiers
│
├─ Event Models (catalog.py)
│  ├─ Base event models
│  ├─ Specialized event types
│  └─ Pydantic validation
│
├─ Event Registry
│  ├─ register_event() API
│  ├─ Summary templates
│  └─ Visibility controls
│
├─ Internal Events
│  ├─ Internal bus
│  ├─ Internal event types
│  └─ Event filtering
│
└─ Visibility System
   ├─ Visibility levels
   ├─ Visibility filters
   └─ Visibility inheritance
```

---

## Event Constants

### Namespace Organization

Events are organized by namespace:

```python
# Thread namespace
THREAD_CREATED = "soothe.thread.created"
THREAD_RESUMED = "soothe.thread.resumed"
THREAD_COMPLETED = "soothe.thread.completed"

# Plan namespace
PLAN_CREATED = "soothe.plan.created"
PLAN_UPDATED = "soothe.plan.updated"
PLAN_COMPLETED = "soothe.plan.completed"

# Step namespace
STEP_STARTED = "soothe.step.started"
STEP_COMPLETED = "soothe.step.completed"
STEP_FAILED = "soothe.step.failed"

# Context namespace
CONTEXT_INGESTED = "soothe.context.ingested"
CONTEXT_PERSISTED = "soothe.context.persisted"
CONTEXT_PROJECTED = "soothe.context.projected"

# Memory namespace
MEMORY_REMEMBERED = "soothe.memory.remembered"
MEMORY_RECALLED = "soothe.memory.recalled"
MEMORY_FORGOTTEN = "soothe.memory.forgot"

# Goal namespace
GOAL_CREATED = "soothe.goal.created"
GOAL_READY = "soothe.goal.ready"
GOAL_STARTED = "soothe.goal.started"
GOAL_COMPLETED = "soothe.goal.completed"
GOAL_FAILED = "soothe.goal.failed"
```

### Complete Event Types

60+ event type constants covering:
- Thread lifecycle (created, resumed, completed)
- Plan management (created, updated, completed)
- Step execution (started, completed, failed)
- Context operations (ingested, persisted, projected)
- Memory operations (remembered, recalled, forgot)
- Goal lifecycle (created, ready, started, completed, failed)
- Tool events (called, completed, error)
- Subagent events (spawned, completed, error)
- Policy events (validated, violation)
- Durability events (checkpoint, restored)

---

## Event Models

### Base Event Model

```python
class SootheEvent(BaseModel):
    """Base event model for all Soothe events."""
    
    # Core fields
    type: str                 # Event type identifier
    timestamp: datetime       # Event timestamp
    
    # Optional fields
    thread_id: str | None     # Associated thread
    goal_id: str | None       # Associated goal
    
    # Data payload
    data: dict[str, Any]      # Event-specific data
    
    # Metadata
    visibility: VisibilityLevel = VisibilityLevel.NORMAL
    source: str | None        # Event source
```

### Specialized Events

Thread events:

```python
class ThreadCreatedEvent(SootheEvent):
    """Thread creation event."""
    type: str = "soothe.thread.created"
    thread_id: str
    query: str

class ThreadCompletedEvent(SootheEvent):
    """Thread completion event."""
    type: str = "soothe.thread.completed"
    thread_id: str
    result: dict
```

Plan events:

```python
class PlanCreatedEvent(SootheEvent):
    """Plan creation event."""
    type: str = "soothe.plan.created"
    thread_id: str
    plan: Plan

class PlanStepEvent(SootheEvent):
    """Step execution event."""
    type: str = "soothe.step.started"  # or completed/failed
    step_id: str
    step: PlanStep
```

Goal events:

```python
class GoalCreatedEvent(SootheEvent):
    """Goal creation event."""
    type: str = "soothe.goal.created"
    goal_id: str
    goal: Goal

class GoalCompletedEvent(SootheEvent):
    """Goal completion event."""
    type: str = "soothe.goal.completed"
    goal_id: str
    result: PlanResult
```

---

## Event Registry

### register_event() API

Public API for registering custom events:

```python
def register_event(
    event_class: type[SootheEvent],
    summary_template: str | None = None,
    visibility: VisibilityLevel | None = None
) -> None:
    """Register custom event type.
    
    Args:
        event_class: Event model class to register
        summary_template: Template for event summaries (e.g., "Goal {goal_id} created")
        visibility: Default visibility level for this event type
        
    Example:
        register_event(
            MyCustomEvent,
            summary_template="Custom: {data}",
            visibility=VisibilityLevel.NORMAL
        )
    """
```

### Registry Functions

```python
# Get registered event types
def get_registered_events() -> list[str]:
    """Get all registered event types."""

# Check if event is registered
def is_event_registered(event_type: str) -> bool:
    """Check if event type is registered."""

# Get event summary template
def get_summary_template(event_type: str) -> str | None:
    """Get summary template for event type."""
```

---

## Visibility System

### Visibility Levels

```python
class VisibilityLevel:
    """Event visibility levels."""
    
    INTERNAL = "internal"    # Internal only (not exposed to clients)
    NORMAL = "normal"        # Normal visibility (exposed to clients)
    VERBOSE = "verbose"      # Verbose visibility (debug mode)
    SILENT = "silent"        # Silent (no visibility)
```

### Visibility Inheritance

Events inherit visibility from registration:

```python
# Register with visibility
register_event(
    InternalEvent,
    visibility=VisibilityLevel.INTERNAL
)

# Event instances inherit visibility
event = InternalEvent(...)
# event.visibility == VisibilityLevel.INTERNAL
```

### Visibility Filtering

Filter events by visibility level:

```python
def filter_events_by_visibility(
    events: list[SootheEvent],
    max_visibility: VisibilityLevel
) -> list[SootheEvent]:
    """Filter events by visibility level."""
    
    return [
        e for e in events
        if e.visibility <= max_visibility
    ]
```

---

## Internal Event Bus

### Internal Bus

Internal event bus for internal events:

```python
class InternalEventBus:
    """Internal event bus for Soothe."""
    
    async def publish(self, event: SootheEvent):
        """Publish event to internal bus."""
        
    async def subscribe(
        self,
        event_types: list[str],
        handler: EventHandler
    ):
        """Subscribe to event types."""
```

### Internal Events

Internal event types for internal processing:

```python
class InternalEvent(SootheEvent):
    """Internal event for internal processing."""
    type: str
    visibility: VisibilityLevel = VisibilityLevel.INTERNAL
```

---

## Summary Templates

### Template Format

Summary templates use string interpolation:

```python
# Template format
template = "Goal {goal_id} created with priority {priority}"

# Event data provides values
event = GoalCreatedEvent(
    goal_id="goal-123",
    goal=Goal(priority=5)
)

# Generated summary
summary = template.format(**event.data)
# "Goal goal-123 created with priority 5"
```

### Template Registration

Register templates with events:

```python
register_event(
    GoalCreatedEvent,
    summary_template="Goal {goal_id} created"
)

register_event(
    StepCompletedEvent,
    summary_template="Step {step_id} completed in {duration}s"
)
```

---

## Usage Patterns

### Basic Event Creation

```python
from soothe.core.events import ThreadCreatedEvent

# Create event
event = ThreadCreatedEvent(
    thread_id="thread-123",
    query="Analyze codebase"
)

# Event fields
print(event.type)  # "soothe.thread.created"
print(event.timestamp)  # Current datetime
print(event.thread_id)  # "thread-123"
```

### Custom Event Registration

```python
from soothe.core.events import register_event, SootheEvent

class MyCustomEvent(SootheEvent):
    type: str = "soothe.plugin.custom.event"
    custom_data: str

# Register custom event
register_event(
    MyCustomEvent,
    summary_template="Custom: {custom_data}",
    visibility=VisibilityLevel.NORMAL
)

# Use registered event
event = MyCustomEvent(custom_data="test")
```

### Event Filtering

```python
from soothe.core.events import filter_events_by_visibility, VisibilityLevel

# Filter events
filtered = filter_events_by_visibility(
    events,
    max_visibility=VisibilityLevel.NORMAL
)

# Only NORMAL and INTERNAL events included
```

---

## Module Organization

### Package Structure

```
soothe.core.events/
├─ constants.py      # Event type constants
├─ catalog.py        # Event models, registry
├─ internal_events.py  # Internal event types
├─ internal_bus.py   # Internal event bus
├─ visibility.py     # Visibility system
└─ __init__.py       # Public exports
```

### Imports

```python
# Import event constants
from soothe.core.events import (
    THREAD_CREATED,
    PLAN_CREATED,
    STEP_STARTED
)

# Import event models
from soothe.core.events import (
    ThreadCreatedEvent,
    PlanCreatedEvent,
    StepStartedEvent
)

# Import registry functions
from soothe.core.events import (
    register_event,
    get_registered_events
)

# Import visibility
from soothe.core.events import VisibilityLevel
```

---

## Event Examples

### Thread Events

```python
# Thread creation
event = ThreadCreatedEvent(
    thread_id="thread-123",
    query="Analyze codebase"
)

# Thread completion
event = ThreadCompletedEvent(
    thread_id="thread-123",
    result={"status": "done", "output": "Analysis complete"}
)
```

### Plan Events

```python
# Plan creation
event = PlanCreatedEvent(
    thread_id="thread-123",
    plan=Plan(
        steps=[step1, step2, step3],
        strategy="iterative analysis"
    )
)

# Step completion
event = StepCompletedEvent(
    step_id="step-1",
    step=step1,
    result={"files": 10, "lines": 5000}
)
```

### Goal Events

```python
# Goal creation
event = GoalCreatedEvent(
    goal_id="goal-123",
    goal=Goal(
        description="Analyze codebase",
        priority=5
    )
)

# Goal completion
event = GoalCompletedEvent(
    goal_id="goal-123",
    result=PlanResult(
        status="done",
        progress=1.0
    )
)
```

---

## Related Documentation

- **[SootheRunner](runner.md)** - Runner event handling
- **[AgentLoop](agent-loop.md)** - Loop events
- **[GoalEngine](goal-engine.md)** - Goal events
- **[Event Catalog](../../specs/event-catalog.md)** - Event catalog spec
- **[RFC-401](../../specs/RFC-401-event-processing.md)** - Event processing

---

## API Reference

### Core Functions

```python
# Event registration
def register_event(
    event_class: type[SootheEvent],
    summary_template: str | None = None,
    visibility: VisibilityLevel | None = None
) -> None: ...

# Registry functions
def get_registered_events() -> list[str]: ...
def is_event_registered(event_type: str) -> bool: ...
def get_summary_template(event_type: str) -> str | None: ...

# Visibility filtering
def filter_events_by_visibility(
    events: list[SootheEvent],
    max_visibility: VisibilityLevel
) -> list[SootheEvent]: ...
```

### Event Classes

```python
class SootheEvent(BaseModel):
    """Base event model."""
    type: str
    timestamp: datetime
    thread_id: str | None
    goal_id: str | None
    data: dict[str, Any]
    visibility: VisibilityLevel
    ...

class ThreadCreatedEvent(SootheEvent):
    """Thread creation event."""
    type: str = "soothe.thread.created"
    thread_id: str
    query: str

class PlanCreatedEvent(SootheEvent):
    """Plan creation event."""
    type: str = "soothe.plan.created"
    thread_id: str
    plan: Plan

class GoalCreatedEvent(SootheEvent):
    """Goal creation event."""
    type: str = "soothe.goal.created"
    goal_id: str
    goal: Goal
```

---

## See Also

- **[RFC-401](../../specs/RFC-401-event-processing.md)** - Event processing spec
- **[RFC-600](../../specs/RFC-600-plugin-extension-system.md)** - Plugin events
- **[Plugin System](../architecture/plugin-system.md)** - Plugin event registration
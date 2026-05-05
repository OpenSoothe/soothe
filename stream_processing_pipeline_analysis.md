# Stream Processing Pipeline Event Flow Analysis

## Executive Summary

The Soothe platform implements a sophisticated **three-layer streaming architecture** for event flow processing, designed to handle real-time AI agent execution with proper event routing, filtering, and display. This analysis covers the complete event flow from generation through processing to display.

---

## 1. Architecture Overview

### Three-Layer Streaming Architecture (RFC-614)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Layer 3: Configuration Layer (Control Plane)                                 │
│ • OutputStreamingConfig: Global enable/disable, mode control                │
│ • CLI override flags: Per-session streaming control                         │
│ • Verbosity tiers: QUIET, NORMAL, DETAILED, DEBUG                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓ Config propagation
┌─────────────────────────────────────────────────────────────────────────────┐
│ Layer 2: Runner Layer (Stream Generation)                                    │
│ • Event generation from AgentLoop, tools, subagents                         │
│ • IG-119-safe forwarding of tool UI + loop-tagged assistant messages       │
│ • LangGraph stream chunks: (namespace, mode, data) tuples                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓ Multiplexed stream tuples
┌─────────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Daemon/Client Layer (Transport & Display)                          │
│ • EventBus: Lock-free pub/sub with priority-aware overflow (IG-258)        │
│ • EventProcessor: Unified event routing with pluggable rendering           │
│ • StreamDisplayPipeline: CLI progress display with verbosity filtering     │
│ • Namespace isolation: Concurrent stream tracking for parallel subagents   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Event Type System (RFC-0015)

### Naming Convention
All events follow the 4-segment naming pattern:
```
soothe.<domain>.<component>.<action>
```

### Domain Classification

| Domain | Purpose | Default Verbosity |
|--------|---------|-------------------|
| `lifecycle` | Thread/session lifecycle | DETAILED |
| `protocol` | Core protocol activity | DETAILED |
| `cognition` | AI reasoning and planning | NORMAL |
| `tool` | Tool execution | INTERNAL |
| `subagent` | Subagent activity | DETAILED |
| `output` | User-facing content | QUIET |
| `error` | Error conditions | QUIET |
| `agentic` | Agent loop execution | NORMAL |

### Core Event Types

#### Lifecycle Events
- `soothe.lifecycle.thread.started` - Thread creation
- `soothe.lifecycle.thread.resumed` - Thread resumption
- `soothe.lifecycle.thread.saved` - Checkpoint save
- `soothe.lifecycle.thread.ended` - Thread termination
- `soothe.lifecycle.iteration.started/completed` - Iteration boundaries
- `soothe.system.daemon.heartbeat` - Keepalive (5-second interval)

#### Cognition Events
- `soothe.cognition.agent_loop.started/completed` - Agent loop lifecycle
- `soothe.cognition.agent_loop.step.started/completed` - Step execution
- `soothe.cognition.agent_loop.reasoned` - Reasoning progress (IG-287)
- `soothe.cognition.plan.created` - Plan generation
- `soothe.cognition.plan.step.started/completed` - Plan step execution
- `soothe.cognition.goal.created/completed/failed` - Goal lifecycle

#### Subagent Events (Curated Wire Events - IG-338)
- `soothe.subagent.claude.started/step.completed/completed/failed`
- `soothe.subagent.explore.started/milestone/completed`
- `soothe.subagent.research.started/milestone/completed/failed`
- `soothe.subagent.browser.started/completed/failed`

---

## 3. Event Flow Pipeline

### 3.1 Event Generation Sources

```
┌─────────────────────────────────────────────────────────────────┐
│ Event Sources                                                   │
├─────────────────────────────────────────────────────────────────┤
│ 1. Agent Loop (soothe.cognition.agent_loop.*)                  │
│    - Loop lifecycle events                                     │
│    - Step execution events                                     │
│    - Reasoning events (LoopAgentReasonEvent)                   │
├─────────────────────────────────────────────────────────────────┤
│ 2. Plan Execution (soothe.cognition.plan.*)                    │
│    - Plan creation and updates                                 │
│    - Step start/completion                                     │
│    - DAG snapshots                                             │
├─────────────────────────────────────────────────────────────────┤
│ 3. Tool Execution (soothe.tool.execution.*)                    │
│    - Tool start/completion/error                               │
│    - Tool call accumulation                                    │
├─────────────────────────────────────────────────────────────────┤
│ 4. Subagent Activity (soothe.subagent.<type>.*)                │
│    - Curated wire events (started/milestone/completed/failed)  │
│    - Task scope tracking (IG-334)                              │
├─────────────────────────────────────────────────────────────────┤
│ 5. Protocol Events (soothe.protocol.*)                         │
│    - Memory recalled/stored                                    │
│    - Policy checked/denied                                     │
│    - Message sent/received                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Event Processing Flow

```
Event Generation (Daemon)
         │
         ▼
┌─────────────────────┐
│ LangGraph Stream    │  (namespace, mode, data) tuples
│ - mode="custom"     │  → Custom events (soothe.*)
│ - mode="messages"   │  → AIMessage/ToolMessage chunks
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ EventBus (RFC-0013) │  Lock-free publish (IG-258 Phase 2)
│ - Topic: thread:{id}│
│ - Priority-aware    │  CRITICAL/HIGH/NORMAL/LOW
│ - Overflow handling │  Queue management at 80% capacity
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ EventProcessor      │  Unified processing (RFC-0019)
│ (soothe_cli)        │
│ - State management  │  ProcessorState
│ - Task namespace    │  IG-334 task scope binding
│ - Tool accumulation │  Tool call chunk handling
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ StreamDisplayPipeline│ CLI display (RFC-0020)
│ (soothe_cli)        │
│ - Verbosity filter  │  Tier-based filtering
│ - Event dispatch    │  Handler routing
│ - DisplayLine gen   │  Structured output
└─────────────────────┘
         │
         ▼
    Display Output
```

---

## 4. Key Components Deep Dive

### 4.1 EventBus (RFC-0013, IG-258)

**Location**: `/packages/soothe/src/soothe/daemon/event_bus.py`

**Features**:
- **Lock-free publishing** (Phase 2): No asyncio.Lock in hot path
- **Reader-writer pattern**: Write lock only for subscribe/unsubscribe
- **Priority-aware overflow**:
  - CRITICAL: Never dropped, blocks if queue full
  - HIGH: Rarely dropped (tool/subagent results)
  - NORMAL: Standard drop with warning
  - LOW: Silent drop at 80% capacity

**API**:
```python
# Publish with priority
await bus.publish(topic, event, event_meta)

# Subscribe/unsubscribe (write-locked)
await bus.subscribe(topic, queue)
await bus.unsubscribe(topic, queue)
```

### 4.2 EventProcessor (RFC-0019)

**Location**: `/packages/soothe-cli/src/soothe_cli/shared/core/event_processor.py`

**Responsibilities**:
- Event routing to RendererProtocol callbacks
- State management (deduplication, streaming)
- Task namespace binding (IG-334)
- Tool call accumulation from chunks
- Loop-tagged assistant output handling (RFC-614)

**Key Methods**:
```python
process_event(event)           # Main entry point
_emit_tool_call_for_renderer() # Tool call display
_emit_tool_result_for_renderer() # Tool result display
_maybe_bind_task_namespace()   # Task scope binding
```

### 4.3 StreamDisplayPipeline (RFC-0020)

**Location**: `/packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py`

**Event Classification**:
```python
def _classify_event(self, event_type: str) -> VerbosityTier:
    # Goal events → NORMAL
    # Step start events → NORMAL
    # Goal completion → QUIET (always visible)
    # soothe.* events → SDK domain classification
    # Non-soothe subagent events → NORMAL
```

**Event Dispatch**:
```python
def _dispatch_event(self, event_type: str, event: dict) -> list[DisplayLine]:
    # soothe.subagent.* → _dispatch_curated_subagent_wire()
    # goal start → _on_goal_started()
    # step start → _on_step_started()
    # step complete → _on_step_completed()
    # goal complete → _on_goal_completed()
    # loop reason → _on_loop_agent_reason()
```

### 4.4 DisplayLine System

**Location**: `/packages/soothe-cli/src/soothe_cli/cli/stream/display_line.py`

**Structure**:
```python
@dataclass
class DisplayLine:
    level: int          # 1=goal, 2=step/tool, 3=result
    content: str        # Text content
    icon: str           # ●, ○, ⚙, ✓, ✗, →
    indent: str         # "" for flat, "  " for tree
    status: str | None  # "running" for parallel
    duration_ms: int | None  # Execution time
```

**Formatting**:
- Level 1-2: Flat layout (no indent)
- Level 3: 2-space tree indent (IG-182)
- Icons: ● goal, ○ step, ⚙ tool, ✓ success, ✗ failure

---

## 5. Verbosity Tier System (RFC-0024)

### Tier Hierarchy

```
QUIET = 0      # Always visible (errors, final output)
NORMAL = 1     # Standard progress (goals, steps, milestones)
DETAILED = 2   # Detailed internals (protocol, subagent activity)
DEBUG = 3      # Everything including internals
INTERNAL = 99  # Never shown (implementation details)
```

### Filtering Logic

```python
def should_show(tier: VerbosityTier, verbosity: VerbosityLevel) -> bool:
    if tier == VerbosityTier.INTERNAL:
        return False
    return tier <= _VERBOSITY_LEVEL_VALUES[verbosity]
```

### Event Classification Examples

| Event Type | Domain | Tier |
|------------|--------|------|
| `soothe.cognition.agent_loop.started` | cognition | NORMAL |
| `soothe.lifecycle.thread.started` | lifecycle | DETAILED |
| `soothe.tool.execution.started` | tool | INTERNAL |
| `soothe.subagent.claude.started` | subagent | NORMAL |
| `soothe.error.general.failed` | error | QUIET |

---

## 6. Subagent Event Flow (IG-338, IG-339)

### Curated Wire Events

Subagents emit curated events instead of raw internal events:

```python
# Claude Subagent Events
soothe.subagent.claude.started          # Task preview
soothe.subagent.claude.step.completed   # Tool use metadata
soothe.subagent.claude.completed        # Cost, duration, summary
soothe.subagent.claude.failed           # Error message

# Explore Subagent Events
soothe.subagent.explore.started         # Search target
soothe.subagent.explore.milestone       # Decision + counts
soothe.subagent.explore.completed       # Total findings
```

### Task Scope Tracking (IG-334)

```
Main Graph Task Spawn
         │
         ▼
┌─────────────────────┐
│ task tool call      │ → Record (tool_call_id, subagent_type)
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Subgraph Stream     │ → namespace binding
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ Task Scope Resolution│ → (task_tool_call_id, subagent_type)
└─────────────────────┘
         │
         ▼
    Display with Task prefix:
    "⚙ Task(explore):#0 milestone..."
```

---

## 7. Loop-Tagged Assistant Output (RFC-614, IG-317)

### Message Stream Phases

Assistant output uses `mode="messages"` with phase tagging:

```python
LOOP_ASSISTANT_OUTPUT_PHASES = frozenset({
    "goal_completion",   # Final answer
    "chitchat",         # Casual conversation
    "quiz",             # Clarifying questions
    "autonomous_goal"   # Autonomous execution summary
})
```

### Flow

```
Agent Loop Execution
         │
         ├── Execute Phase ──► Suppressed (not streamed)
         │
         └── Complete Phase ─► messages stream + phase
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ phase=goal_completion│
                         │ content="Final answer..."│
                         └─────────────────┘
                                  │
                                  ▼
                         Client accumulation
                         (StreamingTextAccumulator)
                                  │
                                  ▼
                         User-facing display
```

---

## 8. Configuration-Driven Behavior

### Output Streaming Config

```python
@dataclass
class OutputStreamingConfig:
    enabled: bool = True           # Global enable/disable
    display_mode: str = "streaming" # "streaming" or "batch"
    buffer_size: int = 1024        # Accumulation buffer
```

### Display Mode Differences

| Mode | Behavior |
|------|----------|
| `streaming` | Real-time chunk delivery |
| `batch` | Accumulate and deliver at boundaries |

---

## 9. Performance Characteristics

### EventBus (IG-258)

| Metric | Value |
|--------|-------|
| Publish latency | ~1μs (lock-free) |
| Queue capacity | 10,000 events |
| Overflow threshold | 80% capacity |
| Concurrent publishers | Unlimited |

### Processing Pipeline

| Stage | Complexity |
|-------|------------|
| Event classification | O(1) - dict lookup |
| Verbosity filtering | O(1) - integer comparison |
| Handler dispatch | O(1) - direct method call |
| DisplayLine generation | O(n) - string formatting |

---

## 10. Testing Coverage

### Test Files

| Test File | Coverage |
|-----------|----------|
| `test_cli_stream_display_pipeline.py` | DisplayLine formatting, goal/step headers |
| `test_event_processor.py` | Event routing, state management |
| `test_daemon_event_protocol.py` | Daemon event bus protocol |
| `test_stream_normalize.py` | Stream normalization utilities |
| `test_runner_stream_poll.py` | Runner stream polling |

### Test Scenarios

- Event classification accuracy
- Verbosity tier filtering
- Task scope binding (IG-334)
- Tool call accumulation
- Subagent wire event handling
- Concurrent stream isolation

---

## 11. Key Design Decisions

### 1. Lock-Free EventBus (IG-258)
**Decision**: Use atomic dict reads instead of locks for publishing.
**Rationale**: Eliminates contention in high-frequency event scenarios.

### 2. Curated Subagent Events (IG-338)
**Decision**: Subagents emit metadata-only events, not raw internals.
**Rationale**: Clean UX without exposing subagent implementation details.

### 3. Loop-Tagged Messages (RFC-614)
**Decision**: Use `messages` stream with `phase` field for assistant output.
**Rationale**: Single wire for assistant text, explicit phase semantics.

### 4. Task Scope Binding (IG-334)
**Decision**: Bind task tool calls to subgraph namespaces.
**Rationale**: Enables proper task attribution in delegated execution.

### 5. Verbosity Tiers (RFC-0024)
**Decision**: Five-tier system with domain defaults.
**Rationale**: Flexible filtering with sensible defaults.

---

## 12. Future Considerations

### Potential Enhancements

1. **Event Replay** (RFC-411): Store and replay event streams
2. **Event Sourcing**: Persist events for audit/debugging
3. **Metrics Integration**: Event-based performance metrics
4. **Backpressure**: Advanced flow control for slow consumers
5. **Schema Evolution**: Versioned event schemas

---

## Appendix: File Reference

### Core Event Files

| File | Purpose |
|------|---------|
| `/packages/soothe/src/soothe/core/events/catalog.py` | Event registry, models, metadata |
| `/packages/soothe/src/soothe/core/events/__init__.py` | Public API exports |
| `/packages/soothe/src/soothe/daemon/event_bus.py` | Pub/sub event bus |
| `/packages/soothe/src/soothe/foundation/base_events.py` | Base event classes |
| `/packages/soothe/src/soothe/foundation/verbosity_tier.py` | Verbosity classification |

### CLI Event Files

| File | Purpose |
|------|---------|
| `/packages/soothe-cli/src/soothe_cli/shared/core/event_processor.py` | Unified event processor |
| `/packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py` | Stream display pipeline |
| `/packages/soothe-cli/src/soothe_cli/cli/stream/display_line.py` | Display line dataclass |
| `/packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py` | Output formatters |
| `/packages/soothe-cli/src/soothe_cli/shared/events/essential_events.py` | Essential event filtering |

### SDK Event Files

| File | Purpose |
|------|---------|
| `/packages/soothe-sdk/src/soothe_sdk/core/events.py` | SDK event base classes |
| `/packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py` | Loop-tagged assistant output |

### Subagent Event Files

| File | Purpose |
|------|---------|
| `/packages/soothe/src/soothe/subagents/claude/events.py` | Claude subagent events |
| `/packages/soothe/src/soothe/subagents/explore/events.py` | Explore subagent events |
| `/packages/soothe/src/soothe/subagents/research/events.py` | Research subagent events |
| `/packages/soothe/src/soothe/subagents/browser/events.py` | Browser subagent events |

# Codebase Consolidation Recommendations Report

**Generated**: 2026-06-19  
**Scope**: Duplicate code patterns and consolidation opportunities across packages  
**Method**: Static analysis, architectural review, and RFC cross-reference

---

## Executive Summary

This report identifies **5 high-priority consolidation opportunities** in the Soothe codebase that would significantly reduce maintenance burden, eliminate synchronization complexity, and establish single sources of truth for critical abstractions.

### Key Findings

| Priority | Consolidation Target | Impact | Effort | Packages Affected |
|----------|----------------------|--------|--------|-------------------|
| **P0** | State Container Unification (LoopState/ThreadState) | HIGH | Medium | soothe, soothe-daemon |
| **P0** | Message Type Proliferation | HIGH | Medium | soothe, soothe-daemon, soothe-sdk, soothe-cli |
| **P1** | Configuration Inheritance Hierarchy | MEDIUM | Low | soothe, soothe-daemon |
| **P1** | Persistence Protocol Consolidation | MEDIUM | Low | soothe, soothe-sdk |
| **P2** | Context Class Convergence | LOW | Low | soothe-cli, soothe-sdk |

---

## P0-1: State Container Unification — LoopState/ThreadState/Checkpoint

### Current Problem

**Three overlapping state containers** manage similar execution state across architectural layers:

| Container | Location | Responsibility | Duplicated Fields |
|-----------|----------|---------------|-------------------|
| `LoopState` | `soothe/sloop/state/schemas.py` | StrangeLoop execution state | iteration, tokens, plan history, thread_id |
| `ThreadState` | `soothe_daemon/runtime/thread_state.py` | Per-checkpoint daemon isolation | thread_id, workspace, last_activity |
| `Checkpoint` models | `soothe/sloop/state/checkpoint.py` | StrangeLoop checkpoint persistence | thread_id, goal_history, working_memory |

**Evidence from RFC-626**:
> "LoopState persists as execution-only container: StrangeLoop still maintains LoopState (RFC-203) with wave metrics, iteration tracking, and plan history. These fields duplicate ContextEngine properties (total_tokens_used, iteration, previous_plan) and create two sources of truth."

**Evidence from IG-480**:
> "State management split across three layers: ContextEngine (goal/step DAG), StrangeLoop state manager (checkpoint lifecycle), LoopState (wave metrics, iteration tracking)"

### Consolidation Strategy

**RFC-626 already defines the solution**: Replace LoopState with thin `ExecutionState` facade backed by ContextEngine.

```
┌─────────────────────────────────────────────────────────┐
│ ContextEngine (Single Entity Owner)                      │
│  ├─ GoalNode (goals with execution metrics)              │
│  ├─ StepNode (step execution records)                    │
│  └─ LedgerManager (unified message ledger)               │
└─────────────────────────────────────────────────────────┘
                          │
                          │ Properties
                          ▼
┌─────────────────────────────────────────────────────────┐
│ ExecutionState (Thin Facade)                             │
│  ├─ loop_id: str (execution-only)                        │
│  ├─ max_iterations: int (config, not state)              │
│  ├─ wave_metrics: WaveMetrics (last wave only)           │
│  └─ Properties → CE GoalNode for shared fields           │
└─────────────────────────────────────────────────────────┘
```

### Action Items

1. **Complete RFC-626 Phase 3**: Implement ExecutionState facade
2. **ThreadState → CE integration**: ThreadState should reference CE GoalNode instead of duplicating workspace/activity tracking
3. **Checkpoint schema trimming**: Remove goal-level fields (already in CE), keep only execution checkpoint fields
4. **Delete LoopState class**: Replace with ExecutionState facade

### Benefits

- **Eliminates 3-way synchronization**: Single source of truth in ContextEngine
- **Reduces checkpoint size**: Only execution-only fields persisted separately
- **Simplifies recovery**: CE restores goal state, checkpoint restores execution state
- **Impact**: HIGH — affects core execution flow, persistence, and daemon isolation

---

## P0-2: Message Type Proliferation

### Current Problem

**At least 5 different message type definitions** across packages with overlapping concerns:

| Message Type | Location | Purpose | Overlapping Fields |
|--------------|----------|---------|-------------------|
| `ChannelMessage` | `soothe_daemon/channels/message.py` | Platform routing | content, metadata, streaming flags |
| `ChannelEvent` | `soothe_daemon/channels/events.py` | Channel events | content, metadata, routing |
| `MessageData` | `soothe_sdk/display/transcript_types.py` | TUI transcript | content, metadata, tool status |
| `LoopMessage` utils | `soothe/sloop/utils/messages.py` | StrangeLoop messages | content, phase, ledger recording |
| Wire messages | `soothe_cli/runtime/wire/messages.py` | LangChain normalization | content, role, metadata |

**Architecture Issue**: Message types fragmented across three layers:
1. **Wire layer**: LangChain message normalization
2. **Display layer**: TUI transcript rendering
3. **Channel layer**: Platform delivery and routing

### Consolidation Strategy

**Unify message schema in SDK**, with layer-specific views:

```python
# soothe_sdk/messages/base.py (NEW)
@dataclass
class BaseMessage:
    """Unified message base for all layers."""
    id: str
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    metadata: dict[str, Any]
    timestamp: float
    
    # Layer-specific views
    def as_channel_message(self) -> ChannelMessage: ...
    def as_transcript_entry(self) -> MessageData: ...
    def as_wire_message(self) -> dict: ...
```

**Migration Path**:
1. Create `soothe_sdk.messages` module with unified types
2. Layer-specific adapters convert to/from base type
3. Deprecate layer-specific types gradually (RFC-413 migration pattern)

### Action Items

1. **Design unified message schema**: Define `BaseMessage` in SDK
2. **Create adapter functions**: Convert between layers
3. **Phase migration**: Start with display layer, then channel layer
4. **Document canonical source**: SDK as message type authority

### Benefits

- **Eliminates conversion complexity**: Single message format with layer-specific views
- **Reduces serialization bugs**: No more cross-layer field mapping errors
- **Simplifies testing**: One message type to test, multiple views
- **Impact**: HIGH — affects all message passing across daemon/CLI/SDK

---

## P1-1: Configuration Inheritance Hierarchy

### Current Problem

**Two top-level configuration classes** with overlapping structure:

| Config Class | Location | Focus | Shared Concerns |
|--------------|----------|-------|-----------------|
| `SootheConfig` | `soothe/config/settings.py` | Agent execution | observability, persistence, security |
| `SootheDaemonConfig` | `soothe_daemon/config/settings.py` | Daemon server | transports, concurrency, logging |

**Duplication Evidence**:
- Both have logging/observability settings
- Both define persistence configuration
- Both specify security parameters
- Daemon loads agent config separately via `load_soothe_config()`

### Consolidation Strategy

**Extract shared base configuration to SDK**:

```python
# soothe_sdk/config/base.py (NEW)
class BaseSootheConfig(BaseSettings):
    """Shared configuration for agent and daemon."""
    observability: ObservabilityConfig
    persistence: PersistenceConfig
    security: SecurityConfig
    
# soothe/config/settings.py
class SootheConfig(BaseSootheConfig):
    """Agent-specific configuration."""
    agent: AgentConfig
    tools: ToolsConfig
    mcp_servers: dict[str, MCPServerConfig]
    
# soothe_daemon/config/settings.py  
class SootheDaemonConfig(BaseSootheConfig):
    """Daemon-specific configuration."""
    transports: TransportConfig
    channels: ChannelsConfig
    worker_pool: WorkerPoolConfig
```

### Action Items

1. **Create `soothe_sdk.config.base`**: Extract shared config models
2. **Refactor SootheConfig**: Inherit from BaseSootheConfig
3. **Refactor SootheDaemonConfig**: Inherit from BaseSootheConfig
4. **Update config loading**: Daemon loads both daemon config and agent config

### Benefits

- **DRY principle**: Shared settings defined once
- **Consistent defaults**: Same observability/security settings across agent/daemon
- **Simpler testing**: One base config fixture for tests
- **Impact**: MEDIUM — affects configuration loading, but straightforward refactor

---

## P1-2: Persistence Protocol Consolidation

### Current Problem

**Two overlapping persistence protocols** with unclear boundaries:

| Protocol | Location | Purpose | Overlap |
|----------|----------|---------|---------|
| `DurabilityProtocol` | `soothe/protocols/durability.py` | Thread lifecycle management | create_thread, list_threads, metadata |
| `AsyncPersistStore` | `soothe_sdk/protocols/persistence.py` | Async key-value persistence | save, load, delete, list_keys |

**Boundary Confusion**:
- DurabilityProtocol manages thread metadata (lifecycle)
- AsyncPersistStore manages arbitrary key-value data (storage)
- Both could be backed by same SQLite/PostgreSQL database
- No clear protocol for "thread-scoped persistence"

### Consolidation Strategy

**Create unified persistence hierarchy in SDK**:

```python
# soothe_sdk/protocols/persistence.py (EXTENDED)

@runtime_checkable
class AsyncPersistStore(Protocol):
    """Base async key-value persistence (unchanged)."""
    async def save(self, key: str, data: Any) -> None: ...
    async def load(self, key: str) -> Any | None: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self, namespace: str | None = None) -> list[str]: ...

@runtime_checkable  
class ThreadAwarePersistStore(AsyncPersistStore, Protocol):
    """Extended protocol with thread-scoped operations."""
    async def save_for_thread(self, thread_id: str, key: str, data: Any) -> None:
        """Save with automatic thread namespacing."""
        ...
    async def load_thread_metadata(self, thread_id: str) -> ThreadMetadata | None:
        """Load thread metadata (replaces DurabilityProtocol thread ops)."""
        ...
```

**Migration**:
- DurabilityProtocol's thread operations → ThreadAwarePersistStore
- Keep DurabilityProtocol for thread *lifecycle* (create, archive, delete)
- Use ThreadAwarePersistStore for thread-scoped *data*

### Action Items

1. **Extend AsyncPersistStore**: Add thread-scoped methods
2. **Refactor DurabilityProtocol**: Focus on lifecycle, delegate storage
3. **Create ThreadAwarePersistStore**: Composition of lifecycle + storage
4. **Update implementations**: SqlitePersistStore, PgsqlPersistStore

### Benefits

- **Clear separation of concerns**: Lifecycle vs. storage
- **Unified protocol hierarchy**: One persistence protocol family
- **Easier testing**: Mock storage without lifecycle complexity
- **Impact**: MEDIUM — affects protocol implementations but not public API

---

## P2: Context Class Convergence

### Current Problem

**Two context classes with overlapping purpose**:

| Context Class | Location | Purpose | Overlap |
|---------------|----------|---------|---------|
| `PluginContext` | `soothe_sdk/plugin/context.py` | Plugin runtime context | config access, logger, services |
| `CLIContext` | `soothe_cli/tui/_cli_context.py` | CLI runtime context | model overrides, params |

**Both provide**:
- Configuration access
- Runtime overrides
- Service access

**Difference**: PluginContext is heavier (logger, emit_event, services dict), CLIContext is lighter (TypedDict for model params).

### Consolidation Strategy

**Create unified runtime context hierarchy**:

```python
# soothe_sdk/context/base.py (NEW)
@dataclass
class RuntimeContext:
    """Base runtime context for all execution contexts."""
    config: SootheConfigProtocol
    model_overrides: dict[str, Any] = field(default_factory=dict)
    
# soothe_sdk/plugin/context.py
@dataclass
class PluginContext(RuntimeContext):
    """Extended context for plugins."""
    logger: logging.Logger
    emit_event: Callable[[str, dict], None]
    services: dict[str, Any] = field(default_factory=dict)
    
# soothe_cli/tui/_cli_context.py
class CLIContext(TypedDict, total=False):
    """Lightweight CLI context (unchanged)."""
    model: str | None
    model_params: dict[str, Any]
```

### Action Items

1. **Create RuntimeContext base**: Extract common fields
2. **Refactor PluginContext**: Inherit from RuntimeContext
3. **Keep CLIContext separate**: TypedDict for performance, different use case
4. **Document relationship**: CLIContext is CLI-specific view

### Benefits

- **Shared abstraction**: RuntimeContext as base for future contexts
- **Consistent config access**: Same protocol pattern
- **Low impact**: Minimal code changes, mostly documentation
- **Impact**: LOW — nice to have, but not critical

---

## Implementation Priorities

### Phase 1: High Impact (Q3 2026)

**P0-1: State Container Unification**
- Follow RFC-626 implementation plan
- Blocker for other consolidations (CE as entity owner)
- Estimated effort: 3-4 weeks
- Dependencies: RFC-624 (CE), RFC-625 (AutopilotMonitor)

**P0-2: Message Type Proliferation**
- Create SDK message types module
- Migrate display layer first
- Estimated effort: 2-3 weeks
- Dependencies: None

### Phase 2: Medium Impact (Q4 2026)

**P1-1: Configuration Inheritance**
- Extract shared config to SDK
- Refactor agent and daemon configs
- Estimated effort: 1 week
- Dependencies: None

**P1-2: Persistence Protocol Consolidation**
- Extend AsyncPersistStore
- Refactor DurabilityProtocol
- Estimated effort: 1-2 weeks
- Dependencies: P0-1 (CE as entity owner affects thread storage)

### Phase 3: Low Impact (Backlog)

**P2: Context Class Convergence**
- Create RuntimeContext base
- Refactor PluginContext
- Estimated effort: 2-3 days
- Dependencies: None

---

## Additional Observations

### Already Consolidated (Good Patterns)

1. **Filesystem abstraction** (IG-453): Unified filesystem layer with security
2. **Protocol layer**: Well-defined protocols in `soothe/protocols/`
3. **SDK types**: Transcript types moved to SDK (RFC-413 migration in progress)

### Technical Debt Identified

1. **Adapter pattern proliferation**: IG-483 documents adapter hardening needed due to dual ownership
2. **Backward compatibility shims**: soothe-cli has 6 shim modules for RFC-413 migration
3. **Dead code**: workspace module has dead ContextVar and deprecated functions (workspace-module-dead-code-analysis.md)

### Related RFCs

- **RFC-624**: Context Engine (entity owner)
- **RFC-625**: AutopilotMonitor and ContextEngine Unification
- **RFC-626**: Entity Model and State Management Consolidation (this report's P0-1)
- **RFC-413**: Server-Owned Display Card Ledger (message type authority)

---

## Conclusion

The highest-priority consolidations (P0-1 and P0-2) address fundamental architectural issues that cause ongoing maintenance burden. **State container unification** (P0-1) is already planned in RFC-626 and should be completed first as it enables other consolidations. **Message type unification** (P0-2) will eliminate cross-layer conversion complexity and establish the SDK as the canonical source for shared types.

The medium-priority consolidations (P1-1 and P1-2) are straightforward refactors that can proceed in parallel with RFC-626 work. The low-priority context convergence (P2) can be addressed opportunistically or deferred.

**Recommendation**: Prioritize RFC-626 completion, then initiate message type unification with a new RFC to document the consolidation strategy.
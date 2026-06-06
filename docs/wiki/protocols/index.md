# Protocol Layer: Core Abstractions

**Status**: Implemented  
**Philosophy**: Protocol-first, runtime-second (RFC-000 Principle 1)  

## Overview

The Protocol Layer defines Soothe's core abstractions as **runtime-agnostic interfaces**. Every Soothe module is defined as a Protocol (abstract interface), enabling backend swappability without runtime dependencies.

**Key Principle**: Protocols define **what** operations are available, backends define **how** they are implemented. This separation enables:
- Development backends (SQLite, in-memory) for rapid iteration
- Production backends (PostgreSQL, vector databases) for scale
- Plugin backends for custom implementations
- Zero code changes when switching backends

## Protocol Taxonomy

Soothe's 9+ core protocols organize into three categories:

### Persistence Protocols

| Protocol | Purpose | Backend | Documentation |
|----------|---------|---------|---------------|
| **MemoryProtocol** | Cross-thread long-term memory | MemU, (planned: KeywordMemory, VectorMemory) | [memory.md](memory.md) |
| **DurabilityProtocol** | Thread lifecycle management | PostgreSQL, SQLite | [durability.md](durability.md) |
| **VectorStoreProtocol** | Vector database abstraction | PGVector, SQLiteVec, Weaviate | [vector-store-persistence.md](vector-store-persistence.md) |
| **AsyncPersistStore** | Key-value persistence | PostgreSQL, SQLite | [vector-store-persistence.md](vector-store-persistence.md) |

### Cognition Protocols

| Protocol | Purpose | Backend | Documentation |
|----------|---------|---------|---------------|
| **PlannerProtocol** | Goal decomposition into plans | LLMPlanner | [planner.md](planner.md) |
| **LoopPlannerProtocol** | AgentLoop Plan phase | LLMPlanner (two-phase) | [planner.md](planner.md) |
| **PolicyProtocol** | Permission-based access control | ConfigDrivenPolicy | [policy.md](policy.md) |

### Execution Protocols

| Protocol | Purpose | Backend | Documentation |
|----------|---------|---------|---------------|
| **LoopRunnerProtocol** | AgentLoop orchestration | SootheRunner | [execution-protocols.md](execution-protocols.md) |
| **RemoteAgentProtocol** | Remote agent invocation | ACP, A2A, LangGraph Remote | [execution-protocols.md](execution-protocols.md) |
| **ToolkitProtocol** | Tool collection interface | Built-in + Plugin toolkits | [execution-protocols.md](execution-protocols.md) |

### Loop-Level Protocols

| Protocol | Purpose | Documentation |
|----------|---------|---------------|
| **LoopWorkingMemoryProtocol** | Bounded Plan prompt scratchpad | [loop-protocols.md](loop-protocols.md) |
| **OperationSecurityProtocol** | Operation-level security context | [loop-protocols.md](loop-protocols.md) |

### Future Protocols

| Protocol | Status | RFC |
|----------|---------|-----|
| **ContextProtocol** | Draft (RFC-400) | Unbounded knowledge accumulator |

## Protocol Relationships

```
┌─────────────────────────────────────────────────────────┐
│  GoalEngine (autonomous goal management)                 │
│  - Delegates to AgentLoop for single-goal execution     │
└─────────────────────────────────────────────────────────┘
                          ↓ PERFORM delegation
┌─────────────────────────────────────────────────────────┐
│  AgentLoop (agentic goal execution)                      │
│  - LoopPlannerProtocol: Plan phase                      │
│  - LoopWorkingMemoryProtocol: Bounded memory            │
│  - LoopRunnerProtocol: Orchestration                    │
└─────────────────────────────────────────────────────────┘
                          ↓ EXECUTE step
┌─────────────────────────────────────────────────────────┐
│  CoreAgent (runtime)                                     │
│  - ToolkitProtocol: Tool invocation                     │
│  - PolicyProtocol: Permission checks                    │
│  - RemoteAgentProtocol: Remote delegation               │
└─────────────────────────────────────────────────────────┘
                          ↓ Persistence
┌─────────────────────────────────────────────────────────┐
│  Persistence Layer                                       │
│  - DurabilityProtocol: Thread lifecycle                 │
│  - MemoryProtocol: Long-term knowledge                  │
│  - VectorStoreProtocol: Semantic search                 │
│  - AsyncPersistStore: Key-value storage                 │
└─────────────────────────────────────────────────────────┘
```

## Protocol Interface Patterns

All Soothe protocols follow consistent patterns:

### Runtime-Agnostic Signatures

```python
@runtime_checkable
class MyProtocol(Protocol):
    """Protocol for [purpose].
    
    No runtime types (LangGraph, langchain) in signatures.
    """

    async def operation(self, arg: str) -> Result:
        """Operation description.
        
        Args:
            arg: Parameter description.
            
        Returns:
            Result data model.
        """
        ...
```

**Key Features**:
- `@runtime_checkable`: Enable `isinstance()` checks
- Async operations: Concurrent-safe execution
- Pydantic data models: Structured inputs/outputs
- No runtime dependencies: Pure protocol definitions

### Data Model Organization

Each protocol defines associated data models:

```python
# Protocol in protocols/my_protocol.py
class MyProtocol(Protocol):
    async def operation(self, request: MyRequest) -> MyResult: ...

# Data models in same file
class MyRequest(BaseModel):
    """Request model."""
    field: str

class MyResult(BaseModel):
    """Result model."""
    data: Any
```

### Backend Implementation Pattern

Backends implement protocols:

```python
# Backend in backends/my_backend/my_implementation.py
class MyImplementation(MyProtocol):
    """Backend implementation using [storage backend]."""

    def __init__(self, config: Config) -> None:
        self._store = resolve_store(config)

    async def operation(self, request: MyRequest) -> MyResult:
        data = await self._store.load(request.field)
        return MyResult(data=data)
```

## Protocol Resolution

Protocols are resolved via configuration:

```python
from soothe.core.resolver import resolve_protocol

# Resolve protocol from config
memory = resolve_protocol("memory", config)  # → MemoryProtocol
durability = resolve_protocol("durability", config)  # → DurabilityProtocol
planner = resolve_protocol("planner", config)  # → PlannerProtocol

# Backend determined by configuration
config.persistence.memory_backend  # "memu" → MemUMemory
config.persistence.durability_backend  # "postgresql" → PostgreSQLDurability
```

**Resolution Flow**:
```
Config → Resolver → Backend Instance → Protocol Interface

1. Config specifies backend name
2. Resolver loads backend implementation
3. Backend initialized with config
4. Returns protocol-compatible instance
```

## Configuration Architecture

### Protocol Configuration Schema

```yaml
# config/config.template.yml
agent:
  protocols:
    memory:
      enabled: true
      backend: memu
      persist_dir: ~/.soothe/memory
      llm_chat_role: memory
    
    durability:
      backend: postgresql  # or sqlite
    
    planner:
      enabled: true
      llm_role: planner
      max_iterations: 8
    
    policy:
      enabled: true
      default_profile: standard

persistence:
  # Backend-specific settings
  postgres_base_dsn: postgresql://user:pass@host:port
  postgres_databases:
    metadata: soothe_metadata
    vectors: soothe_vectors
    checkpoints: soothe_checkpoints
  
  vector_store_backend: pgvector
  metadata_sqlite_path: ~/.soothe/metadata.db
```

### Backend Selection

Backends are selected via configuration:

```yaml
# Development configuration
persistence:
  durability_backend: sqlite
  vector_store_backend: sqlite_vec
  memory_backend: memu

# Production configuration
persistence:
  durability_backend: postgresql
  vector_store_backend: pgvector
  postgres_base_dsn: ${POSTGRES_DSN}
```

## Protocol Integration Guide

### Cross-Protocol Communication

Protocols collaborate through well-defined boundaries:

#### Memory ↔ Durability Integration

```python
# Thread creation triggers memory scope
thread = await durability.create_thread(
    metadata=ThreadMetadata(...)
)

# Memory items reference thread
memory_item = MemoryItem(
    content="Important finding",
    source_thread=thread.thread_id  # Durability provides thread ID
)
await memory.remember(memory_item)
```

#### Policy ↔ Execution Integration

```python
# Policy checks before tool execution
tool_request = OperationSecurityRequest(
    kind=OperationKind.tool_call,
    target="shell_execute"
)

decision = await security.check_operation(tool_request, context)
if decision.allowed:
    # Toolkit provides tools
    tools = toolkit.get_tools()
    result = await execute_tool("shell_execute", tools)
```

#### Planner ↔ Runner Integration

```python
# Runner orchestrates planner
request = LoopRunRequest(
    user_input="Optimize database",
    thread_id="thread_abc123"
)

async for chunk in runner.run(request):
    # Planner decisions drive execution
    if chunk.mode == "plan_result":
        plan_result = PlanResult.from_chunk(chunk)
        # Execute based on plan_result.decision
```

### Protocol Lifecycle

Protocol instances have distinct lifecycles:

#### Singleton Protocols

Some protocols are singleton (shared across threads):

- **MemoryProtocol**: Shared cross-thread memory
- **VectorStoreProtocol**: Shared vector database
- **DurabilityProtocol**: Shared thread management
- **PolicyProtocol**: Shared permission profiles

```python
# Singleton protocols
memory = resolve_memory(config)  # One instance
durability = resolve_durability(config)  # One instance
```

#### Thread-Scoped Protocols

Some protocols are thread-scoped (per-thread instance):

- **LoopWorkingMemoryProtocol**: Per-thread scratchpad
- **ContextProtocol** (future): Per-thread ledger

```python
# Thread-scoped protocols
working_memory = DefaultWorkingMemory()  # Per-thread instance
```

#### Request-Scoped Protocols

Some protocols are request-scoped (per-request instance):

- **OperationSecurityContext**: Per-operation context
- **PlanContext**: Per-planning context

```python
# Request-scoped contexts
context = OperationSecurityContext(
    thread_id=current_thread,
    policy_profile=current_profile
)
```

## Backend Development Guide

### Creating New Backend

To create a new backend for existing protocol:

#### 1. Choose Protocol

```python
# protocols/my_protocol.py
class MyProtocol(Protocol):
    async def operation(self, arg: str) -> str: ...
```

#### 2. Implement Backend

```python
# backends/my_backend/my_implementation.py
class MyImplementation(MyProtocol):
    """Custom backend for MyProtocol."""

    def __init__(self, config: Config) -> None:
        self._config = config

    async def operation(self, arg: str) -> str:
        # Implementation logic
        return f"Processed: {arg}"
```

#### 3. Add Resolver

```python
# core/resolver/_resolver_infra.py
def resolve_my_protocol(config: Config) -> MyProtocol:
    """Resolve MyProtocol from config."""
    backend = config.my_backend
    
    if backend == "my_implementation":
        return MyImplementation(config)
    
    raise ConfigurationError(f"Unknown backend: {backend}")
```

#### 4. Add Configuration

```yaml
# config/config.template.yml
my_protocol:
  backend: my_implementation
  custom_option: value
```

#### 5. Add Tests

```python
# tests/unit/backends/my_backend/test_my_implementation.py
def test_operation():
    impl = MyImplementation(test_config)
    result = await impl.operation("test")
    assert result == "Processed: test"
```

### Backend Interface Contracts

All backends must satisfy:

1. **Protocol compliance**: Implement all protocol methods
2. **Async operations**: All methods must be async
3. **Error handling**: Raise appropriate exceptions (KeyError, ConfigurationError)
4. **Resource cleanup**: Implement cleanup/close methods
5. **Thread safety**: Support concurrent operations

## Specification Reference

### Primary RFCs

| RFC | Title | Protocols Covered |
|-----|-------|-------------------|
| RFC-000 | System Conceptual Design | Protocol philosophy |
| RFC-001 | Core Modules Architecture | All protocols overview |
| RFC-402 | Memory Protocol Architecture | MemoryProtocol |
| RFC-408 | Durability Protocol Architecture | DurabilityProtocol |
| RFC-406 | Policy Protocol Architecture | PolicyProtocol |
| RFC-404 | Planner Protocol Architecture | PlannerProtocol |
| RFC-604 | Reason Phase Robustness | LoopPlannerProtocol |
| RFC-203 | AgentLoop State Memory | LoopWorkingMemoryProtocol |
| RFC-221 | Loop Runner Protocol | LoopRunnerProtocol |

### Related RFCs

| RFC | Title | Protocol Integration |
|-----|-------|---------------------|
| RFC-612 | Persistence Architecture Refactor | Multi-database |
| RFC-222 | Autopilot Goal Engine Architecture | LoopRunner + AutopilotJob |
| RFC-617 | Operation Security Protocol | OperationSecurityProtocol |

## Implementation Status

| Protocol | Implemented | Backend(s) | RFC Status |
|----------|-------------|------------|------------|
| MemoryProtocol | ✅ | MemU | RFC-402 |
| DurabilityProtocol | ✅ | PostgreSQL, SQLite | RFC-408 |
| VectorStoreProtocol | ✅ | PGVector, SQLiteVec, Weaviate | RFC-000 Module 8 |
| AsyncPersistStore | ✅ | PostgreSQL, SQLite | RFC-300 |
| PlannerProtocol | ✅ | LLMPlanner | RFC-404 |
| LoopPlannerProtocol | ✅ | LLMPlanner (two-phase) | RFC-604 |
| PolicyProtocol | ✅ | ConfigDrivenPolicy | RFC-406 |
| LoopRunnerProtocol | ✅ | SootheRunner | RFC-221 |
| RemoteAgentProtocol | ✅ | Direct access | RFC-000 Module 6 |
| ToolkitProtocol | ✅ | Built-in + Plugins | RFC-101 |
| LoopWorkingMemoryProtocol | ✅ | Default implementation | RFC-203 |
| OperationSecurityProtocol | ✅ | Default implementation | RFC-617 |
| ContextProtocol | ⚠️ Draft | RFC-400 draft | RFC-400 |

## Protocol Documentation Index

### Persistence Protocols

- **[Memory Protocol](memory.md)**: Cross-thread long-term memory with MemU backend
- **[Durability Protocol](durability.md)**: Thread lifecycle management with PostgreSQL/SQLite backends
- **[VectorStore & Persistence](vector-store-persistence.md)**: Vector database and key-value persistence

### Cognition Protocols

- **[Policy Protocol](policy.md)**: Permission-based access control with structured permissions
- **[Planner Protocol](planner.md)**: Goal decomposition and AgentLoop Plan phase

### Execution Protocols

- **[Execution Protocols](execution-protocols.md)**: LoopRunner, RemoteAgent, Toolkit protocols

### Loop-Level Protocols

- **[Loop Protocols](loop-protocols.md)**: LoopWorkingMemory and OperationSecurity protocols

## Quick Reference

### Protocol Resolution

```python
from soothe.core.resolver import (
    resolve_memory,
    resolve_durability,
    resolve_planner,
    resolve_loop_planner,
    resolve_policy,
    resolve_vector_store,
)

memory = resolve_memory(config)
durability = resolve_durability(config)
planner = resolve_planner(config)
loop_planner = resolve_loop_planner(config)
policy = resolve_policy(config)
vector_store = resolve_vector_store(config)
```

### Protocol Imports

```python
from soothe.protocols import (
    # Memory
    MemoryProtocol, MemoryItem,
    
    # Durability
    DurabilityProtocol, ThreadInfo, ThreadMetadata, ThreadFilter,
    
    # Planner
    PlannerProtocol, Plan, PlanStep, PlanContext, StepResult,
    
    # LoopPlanner
    LoopPlannerProtocol, PlanResult, StatusAssessment,
    
    # Policy
    PolicyProtocol, Permission, PermissionSet, ActionRequest,
    
    # VectorStore
    VectorStoreProtocol, VectorRecord,
    
    # Persistence
    AsyncPersistStore,
    
    # Runner
    LoopRunnerProtocol, LoopRunRequest,
    
    # Remote
    RemoteAgentProtocol,
    
    # Toolkit
    ToolkitProtocol,
)
```

## Related Documentation

- [RFC-000: System Conceptual Design](../specs/RFC-000-system-conceptual-design.md)
- [RFC-001: Core Modules Architecture](../specs/RFC-001-core-modules-architecture.md)
- [Backend Implementation Guide](../backends.md)
- [Configuration Reference](../configuration.md)
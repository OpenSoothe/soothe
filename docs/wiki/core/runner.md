# SootheRunner

Protocol-orchestrated agent runner for thread lifecycle management.

---

## Overview

SootheRunner (`soothe.core.runner`) wraps `create_soothe_agent()` with protocol pre/post-processing and yields the canonical event stream with `soothe.*` custom events for protocol observability.

**RFC**: [RFC-001](../../specs/RFC-001-core-modules-architecture.md)

---

## Architecture

### Runner Pattern

SootheRunner orchestrates the entire execution flow:

```
SootheRunner.run(query)
    ├─ Pre-Stream Phase
    │  ├─ Thread creation/resumption
    │  ├─ Policy validation
    │  ├─ Memory restoration
    │  ├─ Context projection
    │  └─ Plan bootstrap
    ├─ Agentic Loop (StrangeLoop)
    │  ├─ Plan phase
    │  ├─ Execute phase (CoreAgent)
    │  ├─ Reflect phase
    │  └─ Progressive checkpoint
    └─ Post-Stream Phase
       ├─ Context persistence
       ├─ Memory persistence
       ├─ Artifact storage
       └─ Final checkpoint
```

---

## Core Responsibilities

### 1. Thread Lifecycle Management
Create, resume, and manage execution threads:

```python
# Thread creation
thread_id = generate_thread_id()

# Thread resumption
runner.restore_thread(thread_id)

# Thread lifecycle
runner.checkpoint_thread(thread_id)
```

### 2. Protocol Pre/Post Processing

Execute protocol operations around agent execution:

**Pre-Stream**:
- Policy validation
- Memory restoration
- Context projection
- Plan bootstrap

**Post-Stream**:
- Context persistence
- Memory persistence
- Artifact storage
- Final checkpoint

### 3. Agentic Loop Orchestration

Orchestrate StrangeLoop's Plan → Execute loop:

```python
# Run agentic loop
async for event in runner.run_agentic_loop(query):
    yield event
```

### 4. Event Stream

Yield canonical event stream with protocol observability:

```python
# Event stream
async for event in runner.run(query):
    # Event types:
    # - soothe.thread.created
    # - soothe.plan.created
    # - soothe.step.started
    # - soothe.step.completed
    # - soothe.context.ingested
    # - ...
    print(event)
```

---

## Implementation Structure

### Mixin Decomposition

SootheRunner is decomposed into focused mixins:

```python
class SootheRunner(
    PhasesMixin,           # Pre-stream helpers
    StrangeLoopMixin,          # Agentic loop
    AutopilotWorkerMixin,  # Single-goal worker
    CheckpointMixin        # Progressive checkpoint
):
    """Protocol-orchestrated agent runner."""
```

#### PhasesMixin
Pre-stream helpers:
- Thread creation/resumption
- Policy validation
- Memory restoration
- Context projection

#### StrangeLoopMixin
Agentic loop orchestration:
- StrangeLoop integration
- Plan phase handling
- Execute phase delegation

#### AutopilotWorkerMixin
Single-goal worker entry:
- Goal dispatch handling
- Worker lifecycle

#### CheckpointMixin
Progressive checkpoint:
- Artifact storage
- State checkpointing
- Report generation

---

## Execution Flow

### 1. Pre-Stream Phase

```python
async def pre_stream_phase(self, query: str, thread_id: str):
    # Thread creation/resumption
    thread = await self.create_or_resume_thread(thread_id)
    
    # Policy validation
    policy_result = await self.policy.validate(query)
    
    # Memory restoration
    memory_restored = await self.memory.restore(thread_id)
    
    # Context projection
    context_projection = await self.context.project(query)
    
    # Plan bootstrap
    initial_plan = await self.planner.bootstrap(query)
    
    return {
        "thread": thread,
        "policy": policy_result,
        "memory": memory_restored,
        "context": context_projection,
        "plan": initial_plan
    }
```

### 2. Agentic Loop

```python
async def agentic_loop_phase(self, query: str, state: dict):
    # Run StrangeLoop Plan → Execute
    loop = StrangeLoop(self.config)
    
    async for event in loop.run_with_progress(query):
        # Yield events
        yield event
        
        # Progressive checkpoint
        await self.checkpoint_progress(event)
```

### 3. Post-Stream Phase

```python
async def post_stream_phase(self, thread_id: str, result: dict):
    # Context persistence
    await self.context.persist(thread_id)
    
    # Memory persistence
    await self.memory.persist(thread_id)
    
    # Artifact storage
    await self.store_artifacts(thread_id, result)
    
    # Final checkpoint
    await self.checkpoint_final(thread_id, result)
```

---

## Event Types

### Thread Events
- `soothe.thread.created` - Thread creation
- `soothe.thread.resumed` - Thread resumption
- `soothe.thread.completed` - Thread completion

### Plan Events
- `soothe.plan.created` - Plan creation
- `soothe.plan.updated` - Plan update
- `soothe.plan.completed` - Plan completion

### Step Events
- `soothe.step.started` - Step execution started
- `soothe.step.completed` - Step execution completed
- `soothe.step.failed` - Step execution failed

### Protocol Events
- `soothe.context.ingested` - Context ingestion
- `soothe.context.persisted` - Context persistence
- `soothe.memory.remembered` - Memory storage
- `soothe.memory.recalled` - Memory retrieval

---

## Usage Patterns

### Basic Execution

```python
from soothe.core.runner import SootheRunner
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
runner = SootheRunner(config)

# Execute query
async for event in runner.run("Analyze the codebase"):
    print(event)
```

### Thread-Based Execution

```python
# Resume existing thread
async for event in runner.run(
    "Continue analysis",
    thread_id="thread-123"
):
    print(event)
```

### Autopilot Worker

```python
# Run as autopilot worker
result = await runner.run_autopilot_worker(
    goal="Implement feature",
    goal_id="goal-123"
)
```

---

## Protocol Integration

### ContextProtocol Integration

```python
# Context projection before execution
projection = await runner.context.project(
    query="goal",
    token_budget=4000
)

# Context persistence after execution
await runner.context.persist(thread_id)
```

### MemoryProtocol Integration

```python
# Memory restoration before execution
await runner.memory.restore(thread_id)

# Memory persistence after execution
await runner.memory.persist(thread_id)

# Memory recall during execution
items = await runner.memory.recall("previous context")
```

### PlannerProtocol Integration

```python
# Plan bootstrap before execution
plan = await runner.planner.bootstrap(query)

# Plan update during execution
await runner.planner.update(plan, new_step)
```

### PolicyProtocol Integration

```python
# Policy validation before execution
result = await runner.policy.validate(query)

if not result.allowed:
    raise PolicyViolation(result.reason)
```

---

## Thread Management

### Thread Creation

```python
# Generate new thread ID
thread_id = generate_thread_id()

# Create thread
thread = await runner.create_thread(thread_id, query)
```

### Thread Resumption

```python
# Resume existing thread
thread = await runner.resume_thread(thread_id)

# Check thread state
state = await runner.get_thread_state(thread_id)
```

### Thread Lifecycle

```python
# Thread states
ThreadState.CREATED      # Initial state
ThreadState.RUNNING      # Executing
ThreadState.PAUSED       # Paused
ThreadState.COMPLETED    # Finished
ThreadState.FAILED       # Failed
```

---

## Checkpoint System

### Progressive Checkpoint

```python
async def checkpoint_progress(self, event: Event):
    """Checkpoint after each significant event."""
    # Store state checkpoint
    await self.checkpointer.put(thread_id, state)
    
    # Store artifacts
    await self.artifact_store.put(thread_id, artifact)
```

### Final Checkpoint

```python
async def checkpoint_final(self, thread_id: str, result: dict):
    """Final checkpoint after execution."""
    # Store final state
    await self.checkpointer.put(thread_id, final_state)
    
    # Generate report
    report = await self.generate_report(thread_id)
    
    # Store report
    await self.artifact_store.put(thread_id, report)
```

---

## Configuration

### Runner Settings

```yaml
runner:
  max_iterations: 8      # Maximum StrangeLoop iterations
  checkpoint_interval: 5 # Checkpoint every N steps
  artifact_storage: true # Enable artifact storage
```

### Protocol Settings

```yaml
# Context protocol
context_backend: keyword
context_persist_dir: ~/.soothe/context

# Memory protocol
memory_backend: keyword
memory_persist_dir: ~/.soothe/memory

# Planner protocol
planner_routing: auto

# Policy protocol
policy_backend: config
```

---

## Error Handling

### Protocol Errors

```python
try:
    await runner.context.persist(thread_id)
except ContextPersistenceError as e:
    logger.error(f"Context persistence failed: {e}")
    # Fallback or recovery
```

### Execution Errors

```python
try:
    async for event in runner.run(query):
        yield event
except ExecutionError as e:
    # Store error in thread state
    await runner.store_error(thread_id, e)
    
    # Yield error event
    yield ErrorEvent(error=str(e))
```

---

## Performance Considerations

### Protocol Efficiency

- Use efficient backends (Keyword vs Vector)
- Batch context ingestion
- Optimize memory queries

### Checkpoint Optimization

- Progressive checkpoint interval
- Async checkpoint operations
- Minimal state checkpoint

### Thread Concurrency

```yaml
thread:
  max_concurrent: 10    # Maximum concurrent threads
  rate_limit: 100/min   # Rate limit per minute
```

---

## Related Documentation

- **[Agent Factory](agent-factory.md)** - CoreAgent creation
- **[StrangeLoop](strangeloop.md)** - Plan-Execute loop
- **[Protocol Resolver](resolver.md)** - Protocol wiring
- **[Thread Management](../user-guide/thread-management.md)** - User guide
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Architecture spec

---

## API Reference

### SootheRunner Class

```python
class SootheRunner:
    """Protocol-orchestrated agent runner."""
    
    def __init__(self, config: SootheConfig):
        """Initialize runner with configuration."""
    
    async def run(
        self,
        query: str,
        thread_id: str | None = None
    ) -> AsyncIterator[Event]:
        """Execute query with protocol orchestration."""
    
    async def run_agentic_loop(
        self,
        query: str,
        thread_id: str
    ) -> AsyncIterator[Event]:
        """Run StrangeLoop with protocol handling."""
    
    async def run_autopilot_worker(
        self,
        goal: str,
        goal_id: str
    ) -> Result:
        """Run as autopilot single-goal worker."""
```

### Helper Functions

```python
def generate_thread_id() -> str:
    """Generate unique thread identifier."""
```

---

## See Also

- **[Event System](events.md)** - Event infrastructure
- **[Workspace Management](workspace.md)** - Workspace handling
- **[Persistence](../modules/backends/persistence.md)** - Persistence backends
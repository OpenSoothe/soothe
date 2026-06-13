# Core Modules Architecture

Soothe's core framework provides the foundational runtime for autonomous agent execution.

---

## Overview

The core package (`soothe.core`) implements Soothe's protocol-orchestrated agent runtime with no transport or UI dependencies. It sits between the CLI/daemon layer and the protocol/backend layer.

```
┌─────────────────────────────────────────────────────┐
│  CLI Layer (soothe_cli, soothe_daemon)             │
└──────────────────────┬──────────────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────────────┐
│  Core Framework (soothe.core)                      │
│                                                     │
│  • agent/        CoreAgent factory                 │
│  • runner/       SootheRunner orchestration        │
│  • loop/         StrangeLoop (Plan-Execute)          │
│  • goal_engine/  GoalEngine (autonomous management)│
│  • events/       Event system                      │
│  • workspace/    Workspace resolution              │
│  • context/      Tool context & model override     │
│  • persistence/  Artifact store & policy           │
│  • resolver/     Protocol wiring                   │
│  • middleware/   5-middleware stack                │
└──────────────────────┬──────────────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────────────┐
│  Protocol Layer (soothe.protocols)                 │
│  Backend Layer (soothe.backends)                   │
│  LangChain / DeepAgents / LangGraph                │
└─────────────────────────────────────────────────────┘
```

---

## Three-Level Execution Model

Soothe's execution architecture is organized into three hierarchical levels:

### Level 3: GoalEngine - Autonomous Goal Management
**RFC**: [RFC-200](../../specs/RFC-200-autonomous-goal-management.md)
**Scope**: Long-running complex workflows, multi-goal DAGs
**Loop**: Goal/Goals → PLAN → PERFORM → REFLECT → Update → repeat
**Module**: `goal_engine/`

### Level 2: StrangeLoop - Agentic Goal Execution
**RFC**: [RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md)
**Scope**: Single-goal execution through iterative refinement
**Loop**: Plan → Execute (max ~8 iterations)
**Module**: `loop/`

### Level 1: CoreAgent - Runtime
**RFC**: [RFC-100](../../specs/RFC-100-coreagent-runtime.md)
**Scope**: Foundation runtime with tools, subagents, middlewares
**Loop**: Model → Tools → Model (LangGraph native)
**Module**: `agent/`

---

## Core Modules

### Agent Factory
**Module**: `soothe.core.agent`
**Purpose**: CoreAgent factory and construction logic

Key components:
- `create_soothe_agent()` - Main factory function
- `AgentBuilder` - Construction logic encapsulation
- `CoreAgent` - CompiledStateGraph wrapper

**Documentation**: [Agent Factory](agent-factory.md)

---

### SootheRunner
**Module**: `soothe.core.runner`
**Purpose**: Protocol-orchestrated agent runner

Key responsibilities:
- Protocol pre/post processing
- Thread lifecycle management
- Agentic loop orchestration
- Checkpoint and artifact handling

**Documentation**: [SootheRunner](runner.md)

---

### StrangeLoop
**Module**: `soothe.core.loop`
**Purpose**: Plan-Execute loop for single-goal execution

Key responsibilities:
- LLM-driven planning via PlanResult
- Evidence accumulation
- Goal-directed evaluation
- Adaptive execution

**Documentation**: [StrangeLoop](agent-loop.md)

---

### GoalEngine
**Module**: `soothe.core.goal_engine`
**Purpose**: Autonomous goal management for complex workflows

Key responsibilities:
- Goal DAG orchestration
- Goal lifecycle management
- Backoff reasoning
- Dynamic goal restructuring

**Documentation**: [GoalEngine](goal-engine.md)

---

### Event System
**Module**: `soothe.core.events`
**Purpose**: Centralized event system infrastructure

Key components:
- Event constants (60+ types)
- Event models and registry
- `register_event()` public API
- Visibility controls

**Documentation**: [Event System](events.md)

---

### Workspace Management
**Module**: `soothe.core.workspace`
**Purpose**: Unified workspace resolution and validation

Key responsibilities:
- Daemon/client workspace validation
- Workspace-aware backend wrapper
- FrameworkFilesystem singleton

**Documentation**: [Workspace Management](workspace.md)

---

### Protocol Resolver
**Module**: `soothe.core.resolver`
**Purpose**: Wire protocols from configuration

Key responsibilities:
- Checkpointer resolution
- Durability setup
- Goal engine instantiation
- Tools/subagents wiring

**Documentation**: [Protocol Resolver](resolver.md)

---

## Supporting Modules

### Context Management
**Module**: `soothe.core.context`
**Purpose**: Tool context registry and model override

Key components:
- Tool context registry
- Trigger registry (system message injection)
- Stream model override

---

### Persistence
**Module**: `soothe.core.persistence`
**Purpose**: Artifact store and policy implementation

Key responsibilities:
- Run artifact storage
- Configuration-driven policy
- Persistence backends

---

### Middleware Stack
**Module**: `soothe.core.middleware`
**Purpose**: 5 Soothe-specific middlewares

Middlewares:
- `SoothePolicyMiddleware`
- `SystemPromptMiddleware`
- `ExecutionHintsMiddleware`
- `WorkspaceContextMiddleware`
- `SubagentContextMiddleware`

---

### Prompts
**Module**: `soothe.core.prompts`
**Purpose**: System prompt building

Key components:
- `PromptBuilder`
- Context XML generation
- Template loading

---

## Key RFCs

| RFC | Title | Module |
|-----|-------|--------|
| [RFC-100](../../specs/RFC-100-coreagent-runtime.md) | CoreAgent Runtime | `agent/` |
| [RFC-200](../../specs/RFC-200-autonomous-goal-management.md) | Autonomous Goal Management | `goal_engine/` |
| [RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md) | StrangeLoop Plan-Execute Loop | `loop/` |
| [RFC-001](../../specs/RFC-001-core-modules-architecture.md) | Core Protocol Modules | Multiple |

---

## Quick Reference

### Create Agent
```python
from soothe.core.agent import create_soothe_agent
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
agent = create_soothe_agent(config)

# Execute
async for chunk in agent.astream("query", config={"thread_id": "test"}):
    print(chunk)
```

### SootheRunner
```python
from soothe.core.runner import SootheRunner
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
runner = SootheRunner(config)

# Execute with protocols
async for event in runner.run("query"):
    print(event)
```

### StrangeLoop
```python
from soothe.core.loop import StrangeLoop
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
loop = StrangeLoop(config)

# Run plan-execute loop
result = await loop.run_with_progress(goal="Analyze codebase")
```

---

## Additional Resources

- **[Protocol Layer](../architecture/protocol-first.md)** - Protocol definitions
- **[Backend Layer](../modules/backends/README.md)** - Protocol implementations
- **[RFC Index](../../specs/README.md)** - All RFCs
- **[API Reference](api/README.md)** - Detailed API docs
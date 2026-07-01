# Core Modules Architecture

Soothe's core framework provides the foundational runtime for autonomous agent execution. This is an index of the core module knowledge articles — each linked page distills the architecture, design decisions, and integration points you won't find by reading source code alone.

---

## Where Core Fits

The foundation package (`soothe.foundation`) implements a protocol-orchestrated agent runtime with **no transport or UI dependencies**. It sits between the CLI/daemon layer and the protocol/backend layer:

```
CLI / Daemon layer  →  Core Framework (foundation)  →  Protocols / Backends / LangGraph
```

The core package is intentionally decoupled from how queries arrive (CLI, WebSocket, autopilot dispatch) and from where state is stored (SQLite, PostgreSQL). This separation lets the same runtime power one-shot CLI commands, long-running daemon sessions, and autonomous multi-goal workflows.

---

## Three-Level Execution Model

Soothe organizes execution into three hierarchical levels. Understanding this layering is the key to navigating the core modules:

| Level | Module | Scope | Loop Pattern |
|-------|--------|-------|--------------|
| **3 — ContextEngine** | [goal-engine.md](goal-engine.md) | Long-running multi-goal DAGs | Goal → PLAN → PERFORM → REFLECT → Update |
| **2 — StrangeLoop** | [strangeloop.md](strangeloop.md) | Single-goal iterative refinement | Plan → Execute (max ~8 iterations) |
| **1 — CoreAgent** | [agent-factory.md](agent-factory.md) | Model → Tools → Model turn loop | LangGraph native execution |

Each level delegates downward: ContextEngine dispatches goals to StrangeLoop, which delegates step execution to CoreAgent. Levels communicate via **advisory hints** (passed through `config.configurable`) rather than tight coupling — Layer 1 never knows about goals, it only executes prompts with optional execution hints.

---

## Core Module Index

### Execution Runtime

- **[Agent Factory](agent-factory.md)** — CoreAgent construction. The `create_soothe_agent()` factory assembles tools, subagents, middlewares, and protocol instances into a compiled LangGraph. Covers the builder pattern, lazy initialization, and the Layer 1/Layer 2 contract.
- **[SootheRunner](runner.md)** — Top-level execution coordinator. Wraps CoreAgent with protocol pre/post-processing (policy validation, memory restore, context projection, checkpointing) and yields the canonical `soothe.*` event stream.
- **[StrangeLoop](strangeloop.md)** — Plan-Execute loop for single goals. The middle tier: LLM-driven planning via structured `PlanResult`, evidence accumulation, DAG-style step scheduling, and convergence detection.

### Goal & Context Management

- **[ContextEngine (Goal Engine)](goal-engine.md)** — Autonomous goal management. Manages goal DAGs with dependencies, priorities, dynamic restructuring, backoff reasoning, and dreaming. The top tier for complex workflows.

### Infrastructure

- **[Event System](events.md)** — Centralized event infrastructure. Covers the `soothe.<domain>.<component>.<action>` naming convention, the internal vs. client-facing namespace split, visibility tiers, and the registry pattern.
- **[Protocol Resolver](resolver.md)** — Wires protocols from configuration to runtime instances. Handles checkpointer/durability resolution, the no-in-memory-fallback rule, and tool/subagent registry assembly.
- **[Workspace Management](workspace.md)** — Unified workspace resolution, path validation, and sandbox boundaries. Covers the `SOOTHE_WORKSPACE` priority chain, virtual mode semantics, thread/goal isolation, and the `FrameworkFilesystem` singleton.

---

## Supporting Modules

These modules don't have dedicated knowledge articles but are referenced throughout:

- **Middleware Stack** (`soothe.middleware`) — Five Soothe-specific middlewares: policy enforcement, system prompt injection, execution hints, workspace context, and subagent context isolation.
- **Persistence** (`soothe.foundation.persistence`) — Artifact store and configuration-driven policy for run outputs.
- **Prompts** (`soothe.foundation.sloop.prompts`) — System prompt building via `PromptBuilder`, context XML generation, and template loading.

---

## Key RFCs

| RFC | Title | Primary Module |
|-----|-------|----------------|
| [RFC-100](../../specs/RFC-100-coreagent-runtime.md) | CoreAgent Runtime | agent |
| [RFC-200](../../specs/RFC-200-autonomous-goal-management.md) | Autonomous Goal Management | context |
| [RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md) | StrangeLoop Plan-Execute Loop | loop |
| [RFC-001](../../specs/RFC-001-core-modules-architecture.md) | Core Protocol Modules | multiple |

---

## Quick Start

The two entry points for using the core framework:

```python
# Direct agent execution (Layer 1 only)
from soothe.foundation.core.agent import create_soothe_agent
agent = create_soothe_agent(config)
async for chunk in agent.astream("query", config={"thread_id": "t1"}):
    process(chunk)

# Protocol-orchestrated execution (full stack)
from soothe.runner import SootheRunner
runner = SootheRunner(config)
async for event in runner.run("query"):
    process(event)
```

Use `create_soothe_agent` directly for Layer 1 execution (tests, CLI one-shots). Use `SootheRunner` when you need protocol orchestration — thread lifecycle, policy validation, memory persistence, and the `soothe.*` event stream.

---

## Additional Resources

- **[Protocol Layer](../architecture/protocol-first.md)** — Protocol definitions
- **[Backend Layer](../modules/backends/README.md)** — Protocol implementations
- **[RFC Index](../../specs/README.md)** — All RFCs

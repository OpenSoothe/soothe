---
title: "SootheRunner"
parent: Core Modules
grand_parent: Wiki
nav_order: 2
description: Protocol-orchestrated agent runner for thread lifecycle and event streaming.
---

# SootheRunner

Protocol-orchestrated agent runner for thread lifecycle and event streaming.

---

## What This Module Is

SootheRunner (`soothe.runner`) is the top-level execution coordinator. It wraps `create_soothe_agent()` with protocol pre/post-processing and yields the canonical event stream — the `(namespace, mode, data)` tuples extended with `soothe.*` custom events for protocol observability.

The runner is where all the layers meet: it resolves the checkpointer, creates the CoreAgent, runs intent classification, dispatches to StrangeLoop, and handles thread/workspace lifecycle. It's the single entry point for protocol-orchestrated execution.

**RFC**: [RFC-001](../../specs/RFC-001-core-modules-architecture.md)
**Source**: `packages/soothe/src/soothe/runner/__init__.py`, `_runner_phases.py`, `_runner_strange_loop.py`, `_runner_autopilot_worker.py`, `_runner_checkpoint.py`

---

## The Mixin Decomposition

SootheRunner is composed of four focused mixins rather than a monolithic class:

| Mixin | Responsibility |
|-------|---------------|
| `PhasesMixin` | Pre-stream helpers: thread creation/resumption, workspace resolution, policy validation |
| `StrangeLoopMixin` | StrangeLoop execution: the agentic loop (RFC-201) |
| `AutopilotWorkerMixin` | Single-goal worker entry (RFC-222 revised) |
| `CheckpointMixin` | Progressive checkpointing, artifact storage, report generation |

This decomposition keeps each concern in a testable, readable file. The runner itself is just the composition point — `__init__` wires everything together.

---

## The Three-Phase Execution Flow

When you call `runner.run(query)`, execution flows through three phases:

### Pre-Stream Phase

1. **Thread creation/resumption** — generates or restores a thread ID for state persistence.
2. **Workspace resolution** — resolves the thread-specific workspace path (RFC-103) via `resolve_workspace_for_stream()`.
3. **Intent classification** — the `IntentClassifier` (using the `fast` model) classifies the query to route execution (e.g., `quiz` short-circuits, `agentic` goes to StrangeLoop).
4. **Checkpointer initialization** — if using PostgreSQL, the checkpointer is lazily created from the shared pool in async context.

### Agentic Loop Phase

Delegates to StrangeLoop (RFC-201) for the Plan → Execute iterative refinement loop. The runner passes Layer 2 hints (workspace, intent, routing classification) through `config.configurable`. StrangeLoop yields progress events; the runner forwards them as `soothe.*` custom events.

### Post-Stream Phase

- **Checkpoint** — final state checkpoint via the LangGraph checkpointer.
- **Artifact storage** — run artifacts persisted via the artifact store.
- **Report generation** — final report for the thread.

---

## Lazy CoreAgent Initialization

A significant optimization: when `config.agent.runtime.lazy_core_agent` is `True`, the runner wraps CoreAgent in `LazyCoreAgent`. This defers the expensive graph compilation (tool assembly, middleware wiring, LangGraph compilation) until the first actual execution call.

The trade-off: protocol properties (`agent.memory`, `agent.planner`) may be `None` until materialization. The runner handles this by resolving planner/policy independently in `__init__` and only falling back to the agent's properties after materialization.

The runner also has a `materialize_hook` that ensures the checkpointer is initialized before the agent is used.

---

## Intent Classification — Always Enabled

Intent classification (IG-226) is **always enabled** when a `fast` model is available. The runner creates an `IntentClassifier` in `__init__` using the fast model. If the fast model can't be created, classification is disabled with a warning — execution proceeds without routing optimization.

The classifier determines whether a query is a `quiz` (short-answer, short-circuited by the runner), `agentic` (goes to StrangeLoop), or other intent types. This classification is passed to StrangeLoop and CoreAgent middleware.

---

## Checkpointer Lifecycle

The runner owns the checkpointer lifecycle:

- **Resolution** — `resolve_checkpointer(config)` returns either a checkpointer (SQLite) or a `(None, pool)` tuple (PostgreSQL).
- **Deferred initialization** — for PostgreSQL, the actual `AsyncPostgresSaver` is created from the `SharedCheckpointerPool` in async context (`_ensure_checkpointer_initialized()`).
- **Cleanup** — `runner.cleanup()` must be called to close PostgreSQL connection pools. This is the caller's responsibility.

The `_checkpointer_initialized` flag prevents double-initialization in concurrent async contexts. A `_context_restore_lock` (asyncio.Lock) serializes context restoration.

---

## Concurrency Control

The runner instantiates a `ConcurrencyController` from the config's concurrency policy:

```yaml
agent:
  loop:
    concurrency:
      max_parallel_goals: ...
      max_parallel_steps: ...
      max_parallel_subagents: ...
      global_max_llm_calls: ...
      step_parallelism: ...
```

This controls parallelism within StrangeLoop execution — how many goals, steps, and subagents can run concurrently, and a global LLM call budget.

---

## Autopilot Worker Path (RFC-222)

The legacy in-process autonomous multi-goal loop has been **removed** (RFC-222 Phase D). Autopilot is now daemon-owned. Goals dispatched by the daemon arrive through `LoopRunRequest.autopilot_job` and route to the single-goal worker path (`run_autopilot_worker`).

This means the runner no longer manages multi-goal orchestration internally — that's the daemon's job. The runner executes one goal at a time via StrangeLoop and reports back.

---

## Model Roles

The runner resolves multiple model instances for different purposes:

- **`fast`** — intent classification (falls back to disabled if unavailable)
- **`think`** — consensus loop for goal validation (RFC-204); falls back to suspending goals if unavailable
- **`default`** — quiz fallback and planner resolution

Each model is created in a try/except — if a role isn't configured, the runner degrades gracefully rather than failing at startup.

---

## Minimal Usage

```python
from soothe.runner import SootheRunner
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("config.yml")
runner = SootheRunner(config)

async for event in runner.run("Analyze the codebase"):
    process(event)  # (namespace, mode, data) stream chunks

# For PostgreSQL, always clean up:
await runner.cleanup()
```

To resume an existing thread, pass `thread_id`:
```python
async for event in runner.run("Continue analysis", thread_id="thread-123"):
    process(event)
```

---

## Event Stream

The runner yields the canonical stream format — tuples of `(namespace, mode, data)`. The stream includes:

- **LangGraph message chunks** (`mode: "messages"`) — assistant text, tool I/O
- **LangGraph updates** (`mode: "updates"`) — state transitions
- **Custom events** (`mode: "custom"`) — `soothe.*` protocol events (goal lifecycle, plan, steps, context, memory)

Custom events are built via `custom_event(data)` from the event system. See [Event System](events.md) for the full catalog and visibility rules.

---

## Gotchas

- **PostgreSQL requires `cleanup()`** — if you use PostgreSQL and don't call `runner.cleanup()`, you leak connection pool resources. This won't cause immediate errors but will exhaust connections under load.
- **Intent classification needs the `fast` model** — without it, all queries go through the agentic loop, including simple questions that could be answered directly.
- **The consensus model (`think`) affects goal validation** — if unavailable, goal validation suspends goals rather than validating them. This can cause goals to stall.
- **Thread workspace is per-stream** — `resolve_workspace_for_stream()` resolves a workspace for each stream, not globally. Anonymous users get ephemeral TEMP workspaces.

---

## Related

- **[Agent Factory](agent-factory.md)** — CoreAgent creation
- **[StrangeLoop](strangeloop.md)** — the agentic loop
- **[Protocol Resolver](resolver.md)** — protocol/checkpointer wiring
- **[Event System](events.md)** — the event stream
- **[Workspace Management](workspace.md)** — workspace resolution
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** — architecture spec

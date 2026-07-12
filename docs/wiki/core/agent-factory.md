---
title: "Agent Factory"
parent: Core Modules
grand_parent: Wiki
nav_order: 1
description: >-
  CoreAgent construction and the runtime foundation, covering the builder pipeline and compiled graph.
---

# Agent Factory

CoreAgent construction and the runtime foundation.

---

## What This Module Is

The agent factory (`soothe.foundation.core.agent`) builds Soothe's CoreAgent — a thin wrapper around a LangGraph `CompiledStateGraph` with typed protocol properties and a streaming execution interface. CoreAgent is the **execution tier** of the three-level model: a pure execution runtime for tools, subagents, and middlewares with **no goal infrastructure** (that's StrangeLoop/ContextEngine's job).

The central entry point is `create_soothe_agent(config)`, which delegates to an `AgentBuilder` that resolves protocols, assembles tools/subagents, wires middlewares, compiles the LangGraph, and attaches protocol instances as typed properties.

**RFC**: [RFC-100](../../specs/RFC-100-coreagent-runtime.md)
**Source**: `packages/soothe/src/soothe/foundation/core/agent/_builder.py`, `_core.py`

---

## Why a Factory + Builder?

CoreAgent construction is genuinely complex — it touches config resolution, protocol instantiation, tool registries, MCP server loading, middleware ordering, and LangGraph compilation. The design separates this into two concerns:

- **`AgentBuilder`** owns all construction logic (protocol resolution, middleware assembly, backend init). This keeps the construction complexity in one testable place.
- **`CoreAgent`** is a thin runtime interface — just typed properties (`memory`, `planner`, `policy`, `subagents`) and the `astream()` execution method. No construction logic leaks into the runtime class.

This separation means you can reason about *what the agent does* (CoreAgent) independently from *how it's assembled* (AgentBuilder).

---

## Construction Pipeline

The builder assembles components in a deliberate order:

1. **Config propagation** — `config.propagate_env()` applies environment overrides before anything reads config values.
2. **Protocol resolution** — delegates to `soothe.runner.resolver` for memory (MemU), planner (LLMPlanner), and policy (ConfigDrivenPolicy). Each can return `None` if disabled.
3. **Tool/subagent assembly** — built-in tools (execution, websearch, research) plus configured subagents (planner, deep_research, academic_research, browser_use, veritas) plus plugin and MCP tools. Semantic skill search uses the daemon `SkillifyService` via `search_skills`.
4. **Middleware wiring** — `build_soothe_middleware_stack()` assembles the Soothe middleware stack (identity, policy, system prompt, rate limiting, workspace context, per-turn model, filesystem, code interpreter, MCP tool search, tool timeout — see [Core Modules](index.md) for the full list).
5. **Graph compilation** — calls `create_deep_agent()` with the assembled model, tools, subagents, middlewares, and checkpointer.
6. **Protocol attachment** — protocol instances are attached as typed properties on the resulting `CoreAgent`.

A key design decision: protocol resolution is **delegated to the resolver module**, not duplicated in the builder. This means the same resolution logic serves both direct agent creation and the SootheRunner.

---

## The CoreAgent / StrangeLoop Contract

CoreAgent is designed for a specific integration pattern with StrangeLoop (the middle tier):

**StrangeLoop provides** (via `config.configurable`):
- `thread_id` — for persistence and state isolation
- `workspace` — thread-specific workspace path (RFC-103)
- `soothe_step_subagent` — when set, the first model hop delegates via `task` tool only (IG-386)
- `soothe_step_expected_output` — advisory text describing the expected result

**CoreAgent provides**:
- `astream(input, config)` — streaming execution
- Typed protocol property access (`agent.memory`, `agent.planner`, `agent.policy`)
- Thread-aware execution via checkpointer

The hints are **advisory** — CoreAgent doesn't enforce goals or planning. It just executes prompts, optionally honoring a suggested subagent or expected-output hint. This keeps CoreAgent reusable for direct CLI usage and tests.

---

## Input Normalization

CoreAgent accepts either a bare string or a LangGraph state dict. A bare string is normalized to `{"messages": [HumanMessage(content=...)]}` before invoking the graph. StrangeLoop and the runner pass full state dicts with pre-built message lists; string input exists for convenience and tests.

---

## Execution Graph Twin (IG-477)

A non-obvious design: CoreAgent can hold **two** compiled graphs:

- **Primary graph** — has a checkpointer attached, used for normal execution and state persistence.
- **Execute graph** — a checkpointer-free twin, used for StrangeLoop's ACT-phase streaming during high-volume execution.

The twin avoids per-chunk checkpoint memory spikes. When ephemeral execute is enabled (`ephemeral_execute_stream_enabled()`), ACT-phase streaming uses the twin via `execution_astream()`. The twin is compiled **lazily** on first access (IG-506) to avoid paying compilation cost if never needed.

The `durability` parameter on `astream()` controls LangGraph checkpoint durability — use `"exit"` during high-volume streaming to defer checkpoint writes.

---

## Protocol Properties

After construction, protocols are accessible as typed properties — **not** as `soothe_*` prefixed attributes (that was the old pattern). The current API:

```python
agent = create_soothe_agent(config)
agent.memory     # MemoryProtocol | None
agent.planner    # PlannerProtocol | None
agent.policy     # PolicyProtocol | None
agent.subagents  # list[SubAgent | CompiledSubAgent]
agent.graph      # CompiledStateGraph (for advanced LangGraph ops)
agent.checkpointer  # BaseCheckpointSaver | None
```

`aget_state()` returns `None` gracefully when no checkpointer is configured, avoiding LangGraph's `ValueError`.

---

## Minimal Usage

```python
from soothe.foundation.core.agent import create_soothe_agent
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("config.yml")
agent = create_soothe_agent(config)

async for chunk in agent.astream("Analyze the codebase",
                                  config={"configurable": {"thread_id": "t1"}}):
    process(chunk)
```

For protocol-orchestrated execution (policy validation, memory persistence, event stream), use [SootheRunner](runner.md) instead — it wraps `create_soothe_agent()` with pre/post-processing.

---

## Integration Points

- **StrangeLoop** — delegates step execution to `agent.astream()` or `agent.execution_astream()`, passing hints via `config.configurable`.
- **SootheRunner** — calls `create_soothe_agent()` internally (lazily, if `lazy_core_agent` is enabled in config) and wires the checkpointer.
- **CLI/Daemon** — direct factory usage for one-shot execution; daemon wraps in WebSocket event delivery.

---

## Gotchas

- **Lazy CoreAgent** — when `config.agent.runtime.lazy_core_agent` is `True`, the runner wraps CoreAgent in `LazyCoreAgent` that defers graph compilation until first use. This speeds startup but means protocol properties may be `None` until materialization.
- **Model override** — per-execution model override is available via `config.configurable["model_override"]`, handled by middleware, not CoreAgent itself.
- **Host execution only** — deepagents registers a sandbox-backed `execute` tool by default; Soothe strips it at builder construction and via a `FilesystemMiddleware` init patch (`_execute_filter.py`). Shell access is only through host tools (`run_command`, `run_background`, etc.) from `toolkits.execution`.

---

## Related

- **[SootheRunner](runner.md)** — protocol orchestration around CoreAgent
- **[Protocol Resolver](resolver.md)** — how protocols are resolved from config
- **[StrangeLoop](strangeloop.md)** — the middle tier that delegates to CoreAgent
- **[RFC-100](../../specs/RFC-100-coreagent-runtime.md)** — full specification

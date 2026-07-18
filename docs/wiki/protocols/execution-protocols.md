---
title: "Execution Protocols"
parent: Protocols
grand_parent: Wiki
nav_order: 8
description: LoopRunner and Autopilot dispatch protocols for protocol-orchestrated agent execution.
---

# Execution Protocols

**RFC**: 221 (LoopRunner), 222 revised (Autopilot dispatch)
**Location**: `packages/soothe/src/soothe/protocols/runner.py`
**Status**: Implemented

## What the Execution Layer Is

Execution protocols define how agent runs are launched, orchestrated, and streamed back to consumers. The central abstraction is `LoopRunnerProtocol` — the interface that runs complete StrangeLoop (Plan → Execute) cycles and streams results in real time.

The execution layer sits between high-level orchestration (the daemon's `QueryEngine`) and low-level agent execution (the StrangeLoop graph). Consumers depend only on `LoopRunnerProtocol`; the concrete runner — `LocalLoopRunner` (multiprocessing) or `RayLoopRunner` (Ray actor) — is selected by the daemon's `LoopRunnerFactory` based on config.

## LoopRunnerProtocol

### Role

`LoopRunnerProtocol` is a two-method interface:

- **`run(request)`** — execute the StrangeLoop, yielding `StreamChunk` tuples until completion. This is an `AsyncIterator` — results stream in real time, they don't arrive all at once.
- **`cancel()`** — request cancellation of a running loop.

The deliberately tiny surface (two methods) is a design choice: all execution complexity is encapsulated in `LoopRunRequest` and the streaming protocol, keeping the interface stable as internals evolve.

### The StreamChunk Contract

```python
StreamChunk = tuple[tuple[str, ...], str, Any]
# (namespace, mode, data)
```

This is the deepagents-canonical streaming format:

- **namespace** — a path tuple (e.g., `("agent", "loop")`) identifying which subgraph produced the chunk
- **mode** — the stream mode (`"messages"`, `"updates"`, `"custom"`)
- **data** — the payload (message dict, event object, etc.)

Consumers parse chunks by mode and namespace to render TUI output, extract plan results, or detect completion. The runner streams multiple modes simultaneously (`subgraphs=True`), so a single run interleaves message tokens, state updates, and custom events.

## LoopRunRequest: The Execution Envelope

`LoopRunRequest` is a dataclass consolidating *everything* needed to run one agent loop. It replaced ad-hoc parameters previously passed to `SootheRunner.astream()`, including thread/workspace binding that was once mutated on a shared singleton.

Key fields and their purposes:

- **`loop_id` / `thread_id`** — bind the run to a durable thread (DurabilityProtocol) and a unique loop instance.
- **`user_input`** — the user's query or instruction.
- **`client_workspace` / `user_id` / `client_workspace_id`** — workspace resolution. If `client_workspace` is set, it's used directly; otherwise the runner computes `$SOOTHE_HOME/workspaces/<normalized_user_id>/ws_<hash>`.
- **`autonomous` / `max_iterations`** — control autonomous goal management and loop iteration limits.
- **`timeout_seconds`** — worker pool timeout for cancellation.
- **`intent_hint`** — daemon-only non-agent turns (``text_completion``, ``image_to_text``, ``ocr``, ``embed``).
- **`clarification_mode` / `clarification_answer` / `clarification_answers`** (RFC-622) — when `clarification_answer=True`, the runner treats `user_input` as the answer to a pending clarification interrupt and resumes the graph via `Command(resume=...)` rather than starting a new turn. The runner verifies against the loop's persisted `pending_clarification` state.
- **`autopilot_job`** (RFC-222 revised) — when set, this request is dispatched by the daemon's `AutopilotService`; the worker hydrates from a context bundle instead of `user_input`.

### GoalDispatchEnvelope

When `autopilot_job` is set, it carries a `GoalDispatchEnvelope` — a **transient wire message** (not a persistent entity). Created by the daemon when dispatching a goal to a subprocess worker, consumed by the worker's hydration path:

- `goal_id` — daemon's canonical goal ID
- `goal_description` — frozen at dispatch time
- `merged_context` — pre-projected hydration bundle from the daemon's `ContextProjector`; the worker treats it as opaque
- `deadline_seconds` — wall-clock budget (`None` = no cap)
- `attempt` — 1 on first dispatch, N on retry/backoff

> **Terminology gotcha**: "Job" in Desktop UX = user-facing term for a *root Goal* (persistent). `GoalDispatchEnvelope` = transient dispatch *message* (not stored). `AutopilotJob` is a deprecated alias — use `GoalDispatchEnvelope` in new code.

## Execution Flow

The runner orchestrates the full StrangeLoop cycle:

```
LoopRunner.run(request)
  → resolve workspace path
  → configure agent loop (model, concurrency, subagents)
  → initialize StrangeLoop
  → loop iteration:
      a. LoopPlanner.plan() → PlanResult
      b. execute decision via CoreAgent (tools/subagents)
      c. collect StepResult, update LoopState
  → stream StreamChunks to consumer throughout
  → persist final state
```

The runner streams chunks *during* execution, not after. This is why `run()` is an `AsyncIterator` — consumers (TUI, API) render progress incrementally.

## Backends

| Backend | Status | Use Case |
|---------|--------|----------|
| `LocalLoopRunner` | Current | Multiprocessing-based subprocess execution |
| `RayLoopRunner` | Available | Ray actor-based distributed execution |

Both implement `LoopRunnerProtocol`. The daemon's `LoopRunnerFactory` selects between them via `SootheDaemonConfig`. Consumers (`QueryEngine`) see only the protocol.

## Integration Points

### Runner ↔ LoopPlanner

Each StrangeLoop iteration calls `LoopPlannerProtocol.plan()` to get a `PlanResult`. If `plan_action == "new"`, the runner executes the new decision; if `status == "complete"`, the goal is achieved and the loop ends. See [planner.md](planner.md).

### Runner ↔ Policy

Before executing any tool or subagent, the runtime consults `PolicyProtocol` for permission. Denied actions raise `PermissionError`; `need_approval` actions pause for user input. See [policy.md](policy.md).

### Runner ↔ Durability

The run binds to a `thread_id` (DurabilityProtocol). Thread metadata — including `policy_profile` — flows from durability into the runner's configuration. On completion, state persists to the thread.

## Gotchas

- **`autopilot_job` vs `user_input` are mutually exclusive paths** — when `autopilot_job` is set, the worker ignores `user_input` and hydrates from `merged_context`. When `None`, the worker runs solo-mode (today's default path).
- **Clarification resume is state-verified** — the runner checks persisted `pending_clarification` state before treating input as an answer. If no clarification is pending, it falls back to a normal turn.
- **Streaming is multi-mode** — the runner streams `messages`, `updates`, and `custom` modes simultaneously with `subgraphs=True`. Consumers must handle interleaved chunk types.
- **`resolve_workspace_path()` has fallback logic** — when `client_workspace` is absent, it derives a path from `user_id` (or `"anonymous"`) hashed with `client_workspace_id` or `loop_id`. Don't assume a specific path without calling this method.

## Related Documentation

- [Planner Protocol](planner.md) — `LoopPlannerProtocol` drives each iteration
- [Loop Protocols](loop-protocols.md) — working memory and operation security within loops
- [Policy Protocol](policy.md) — permission checks during execution
- [StrangeLoop Architecture](../core/strangeloop.md)

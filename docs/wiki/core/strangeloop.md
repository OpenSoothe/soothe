---
title: "StrangeLoop"
parent: Core Modules
grand_parent: Wiki
nav_order: 3
description: Plan-Execute loop for single-goal agentic execution — the middle tier of the execution model.
---

# StrangeLoop

Plan-Execute loop for single-goal agentic execution — the middle tier of the execution model.

---

## What This Module Is

StrangeLoop (`soothe.sloop`) is the **middle tier** of Soothe's three-level execution architecture. Where ContextEngine owns the StepDAG for a goal, StrangeLoop drives a *single* goal through DISPATCH ⇄ EXECUTE → RECONCILE → ROOT_EVAL. It delegates actual tool execution to CoreAgent.

The name comes from the core insight: the agent decomposes, executes, reconciles, and re-dispatches in a loop — a "strange loop" of self-referential refinement. The loop is bounded (default max iterations from config) and converges when the StepDAG is green.

**RFC**: [RFC-904](../../specs/RFC-904-sloop-recursive-decomposition.md) (topology); [RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md) (historical Plan-Execute framing)
**Source**: `packages/soothe/src/soothe/sloop/engine/strange_loop.py`, `state/schemas.py`, `orchestrator/`

---

## The Loop Graph — Not a Hand-Rolled Loop

StrangeLoop is implemented as a **compiled LangGraph** (RFC-220 Loop Graph,
topology per RFC-904), not a Python `while` loop. The graph's configurable
checkpoint key is `loop_id`, allowing loop state to persist across interruptions
and resume from checkpoints.

The graph orchestrates a clear **main stem**:

1. **Preprocess** — `intake` → `enter_loop` (Pass-1 social vs task + branch).
2. **Dispatch** — claim CE ready steps (root StepNode on first entry).
3. **Execute** — CoreAgent thread wave; optional `decompose_task` proposals.
4. **Record → Reconcile** — persist wave outcomes; commit proposals into the StepDAG.
5. **Root eval** — tree-green → **finalize**, or gap re-dispatch; else loop back to DISPATCH.

Stage modules live under
`sloop/stages/{preprocess,decompose,execute,complete,sidecars}/`
(plus `stages/plan/phase_status.py` for status cards). Canonical station IDs
and ledger dual-read tags are in `sloop/orchestrator/stations.py`.

Primary diagram: [strange_loop_stem.mmd](../../diagrams/strange_loop_stem.mmd).

Routing (`route_after_preprocess`): chitchat → END; wired intake specialist →
`delegate`; all task labels → `dispatch`.

---

## PlanResult — The Structured Decision

DISPATCH (and trivial one-step helpers) produce a `PlanResult` that carries the
in-flight `AgentDecision` into execute.

Key fields and their design rationale:

- **`status`** — `continue` | `replan` | `done`. Drives the loop graph's routing. Notably, there's no `failed` status here — failure is handled by ContextEngine.
- **`goal_progress`** — descriptive level (`none` | `low` | `medium` | `high` | `complete`), **not** numeric. IG-399 replaced numeric progress with descriptive levels because LLMs are bad at precise numeric estimation but good at categorical assessment.
- **`plan_action`** — `keep` | `new`. Whether to reuse the in-flight `AgentDecision` or supply a new one. A validator enforces that `new` requires a `decision` when status isn't `done`.
- **`require_goal_completion`** — optimization flag. When `False`, the last AIMessage can be used directly, skipping an extra goal-completion LLM call.
- **`terminal_after_execute`** (RFC-226) — when `True`, the plan asserts its single step IS the goal completion. The graph routes directly from `record_progress` to `finalize`.

---

## Recursive Decomposition (RFC-904)

There is no separate assess/generate plan-spine. Decomposition is owned by the
CE StepDAG:

1. **DISPATCH** claims ready steps (or grounds an Approve plan / creates the root).
2. Threads may call executor-bound **`decompose_task`**; completions land immediately.
3. **RECONCILE** commits proposals; **ROOT_EVAL** finalizes when the tree is green.

Budgets: `agent.loop.decompose.*` (always on for step THREADS).

---

## Step Kinds — Action vs. Ask-User

Steps have a `kind` field: `action` or `ask_user` (RFC-622, IG-462).

- **`action`** steps run through CoreAgent — normal tool execution.
- **`ask_user`** steps do **not** invoke CoreAgent. Instead, they route `questions` through the configured `ClarificationPolicy` and record a synthesized successful step result containing the answers.

This lets the loop request clarification mid-execution without breaking the Plan-Execute cycle. The `ask_user` validator enforces that questions are non-empty.

---

## Evidence Accumulation

Evidence is tracked as `EvidenceEntry` rows with a `kind` classification: `tool` (from tool execution), `bootstrap` (initial context), or `ledger` (from history). Each entry has a stable `evidence_id` and a compact `summary` for prompt injection.

Evidence persists across iterations within the loop and is included in the `PlanResult.evidence_summary`. This gives execute / synthesis accumulated context about what's been learned.

---

## Execution Modes — Parallel vs. Dependency

Steps can execute in two modes (the `ExecutionMode` literal):

- **`parallel`** — all steps in a wave run concurrently (up to concurrency limits).
- **`dependency`** — steps execute in dependency order; a step waits until its `dependencies` are satisfied.

The `StepScheduler` / `Executor` (inside the execute phase) handles DAG-style multi-step execution. This is **not** a separate runner mixin — DAG execution is internal to StrangeLoop's execute phase.

### Dependency Token Expansion

Step dependencies use the same token expansion as ContextEngine's StepDAG: composite IDs like `KFA-01` can be referenced as `01` or `1`, resolved unambiguously. This handles LLM shorthand.

---

## Context Isolation

Each StrangeLoop run assembles goal-specific context before the first iteration:

- **Context projection** — bounded projection from ContextEngine (goals, steps, ledger, lineage within token limits).
- **Memory recall** — relevant memories retrieved from the memory protocol.
- **Goal history** — prior iterations' evidence and reasoning.

This context is injected into execute / synthesis prompts, giving the LLM awareness of the broader workflow without unbounded context growth.

---

## Convergence and Iteration Bounds

The loop is bounded by `agent.loop.max_iterations` (default **99**, from `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS`). The same budget applies to Autopilot workers. Convergence is detected when **ROOT_EVAL** sees a green StepDAG (or a terminal one-step `PlanResult` routes `record_progress` → `finalize`).

The `terminal_after_execute` flag (RFC-226) provides an optimization: when a one-step plan asserts it completes the goal, the graph skips RECONCILE / ROOT_EVAL for that turn.

---

## Integration Points

- **ContextEngine** — StrangeLoop is instantiated with a `core_agent`. ContextEngine owns the StepDAG; StrangeLoop DISPATCH / RECONCILE / ROOT_EVAL drive it. StrangeLoop reports goal completion via finalize / CE goal APIs.
- **SootheRunner** — the runner's `StrangeLoopMixin` creates and drives StrangeLoop, passing intent classification, workspace, and routing hints.
- **CoreAgent** — step execution delegates to `agent.astream()` or `agent.execution_astream()` (the checkpointer-free twin for high-volume streaming).

### Skill Handling

A non-obvious behavior: StrangeLoop parses slash-skill invocations from the goal text (`parse_slash_skill_user_line`). When a skill is addressed, it syncs only that skill to the workspace (targeted sync, not full sync). If no skill is addressed, sync is skipped entirely — skills are synced on-demand via middleware.

---

## Minimal Usage

```python
from soothe.sloop.engine.strange_loop import StrangeLoop

loop = StrangeLoop(core_agent=agent, config=config)
async for event_type, event_data in loop.run_with_progress(
    goal="Analyze the codebase structure",
    thread_id="thread-123",
):
    if event_type == "completed":
        result = event_data["result"]  # PlanResult
```

In practice, you rarely instantiate StrangeLoop directly — the runner handles it. The runner passes `intent`, `routing_classification`, `workspace`, and `clarification_policy`.

---

## Gotchas

- **`run()` vs `run_with_progress()`** — `run()` is a convenience wrapper that consumes `run_with_progress()` and returns the final `PlanResult`. If you need streaming events, use `run_with_progress()`.
- **Loop state persistence uses `loop_id`** — not `thread_id`. The loop graph checkpoints under `loop_id`, which is separate from the CoreAgent's `thread_id` checkpoint. Both are needed for full resumption.
- **`status="replan"` with `plan_action="new"` requires a `decision`** — the validator enforces this. If the LLM returns `replan` + `new` without steps, it's a schema error.
- **Bootstrap actions** — the first iteration may have `terminal_after_execute=True`, meaning the plan asserts its single step is the answer. This skips the second assessment, which is correct for simple goals but wrong if the step fails.
- **SharedPostgreSQLPool** — for high-concurrency deployments, StrangeLoop accepts a `shared_pool` parameter (IG-406) for state persistence. Without it, each loop creates its own connection.

---

## Related

- **[ContextEngine](context-engine.md)** — goal management (top tier)
- **[Agent Factory](agent-factory.md)** — execution runtime (CoreAgent)
- **[SootheRunner](runner.md)** — runner that drives StrangeLoop
- **[RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md)** — full specification

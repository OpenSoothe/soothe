---
title: "StrangeLoop"
parent: Core Modules
grand_parent: Wiki
nav_order: 3
description: Plan-Execute loop for single-goal agentic execution — Layer 2 of the execution model.
---

# StrangeLoop

Plan-Execute loop for single-goal agentic execution — Layer 2 of the execution model.

---

## What This Module Is

StrangeLoop (`soothe.foundation.sloop`) is the **middle tier** of Soothe's three-level execution architecture. Where ContextEngine (Layer 3) decides *which* goals to pursue, StrangeLoop executes a *single* goal through iterative Plan → Execute refinement. It delegates actual tool execution to CoreAgent (Layer 1).

The name comes from the core insight: the LLM plans, executes, assesses progress, and re-plans in a loop — a "strange loop" of self-referential refinement. The loop is bounded (default max 8 iterations) and converges based on progress assessment.

**RFC**: [RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md)
**Source**: `packages/soothe/src/soothe/foundation/sloop/engine/strange_loop.py`, `state/schemas.py`, `orchestrator/`

---

## The Loop Graph — Not a Hand-Rolled Loop

StrangeLoop is implemented as a **compiled LangGraph** (RFC-220 Loop Graph), not a Python `while` loop. The graph's configurable checkpoint key is `loop_id`, allowing loop state to persist across interruptions and resume from checkpoints.

The graph orchestrates a multi-phase iteration:

1. **Plan-Assess** — a quick status check (RFC-604): lightweight schema (~50-80 tokens) that decides whether to continue, replan, or finish.
2. **Plan-Generate** — if replanning, the LLM generates new steps with structured output.
3. **Execute** — runs steps via CoreAgent, either in parallel or dependency-ordered waves.
4. **Record Iteration** — logs evidence, updates progress.
5. **Goal Completion** — when the plan asserts completion, a final LLM call synthesizes the answer.

The graph nodes live in `orchestrator/nodes/` — each node is a discrete phase (e.g., `plan_assess.py`, `plan_generate.py`, `execute_steps.py`, `iteration_gate.py`).

---

## PlanResult — The Structured Decision

The Plan phase produces a `PlanResult`, which is the central data structure. It combines planning, progress assessment, and goal-distance estimation in a single structured LLM response.

Key fields and their design rationale:

- **`status`** — `continue` | `replan` | `done`. Drives the loop graph's routing. Notably, there's no `failed` status here — failure is handled by ContextEngine.
- **`goal_progress`** — descriptive level (`none` | `low` | `medium` | `high` | `complete`), **not** numeric. IG-399 replaced numeric progress with descriptive levels because LLMs are bad at precise numeric estimation but good at categorical assessment.
- **`plan_action`** — `keep` | `new`. Whether to reuse the in-flight `AgentDecision` or supply a new one. A validator enforces that `new` requires a `decision` when status isn't `done`.
- **`require_goal_completion`** — optimization flag. When `False`, the last AIMessage can be used directly, skipping an extra goal-completion LLM call.
- **`terminal_after_execute`** (RFC-226) — when `True`, the plan asserts its single step IS the goal completion. The graph routes directly from `record_iteration` to `goal_completion`, skipping the next `plan_assess`. Set for bootstrap actions where the first step is obviously the answer.

---

## The Two-Phase Plan (RFC-604)

Planning is split into two phases with different token budgets:

1. **StatusAssessment** (~50-80 tokens) — minimal fields: just `status` and `progress`. This is a cheap "are we done?" check. 60% token reduction vs. the old monolithic plan (IG-264).
2. **PlanGeneration** (full schema) — only runs when assessment says `replan`. Generates `PlanGenerateStep` entries with description, full_description, expected_output, and dependencies.

This split means most iterations only pay the cost of the assessment phase. Full planning only happens when the plan needs to change.

---

## Step Kinds — Action vs. Ask-User

Steps have a `kind` field: `action` or `ask_user` (RFC-622, IG-462).

- **`action`** steps run through CoreAgent — normal tool execution.
- **`ask_user`** steps do **not** invoke CoreAgent. Instead, they route `questions` through the configured `ClarificationPolicy` and record a synthesized successful step result containing the answers.

This lets the loop request clarification mid-execution without breaking the Plan-Execute cycle. The `ask_user` validator enforces that questions are non-empty.

---

## Evidence Accumulation

Evidence is tracked as `EvidenceEntry` rows with a `kind` classification: `tool` (from tool execution), `bootstrap` (initial context), or `ledger` (from history). Each entry has a stable `evidence_id` and a compact `summary` for prompt injection.

Evidence persists across iterations within the loop and is included in the `PlanResult.evidence_summary`. This gives the planner accumulated context about what's been learned, preventing re-exploration of already-answered questions.

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

This context is injected into the Plan phase prompts, giving the LLM awareness of the broader workflow without unbounded context growth.

---

## Convergence and Iteration Bounds

The loop is bounded by `max_iterations` (default 8, from `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS`). Convergence is detected by the Plan-Assess phase returning `status="done"`.

There's no separate convergence threshold — the LLM decides when the goal is achieved based on evidence and progress. The `terminal_after_execute` flag (RFC-226) provides an optimization: when the plan asserts a single step completes the goal, the graph skips the next assessment.

---

## Integration Points

- **ContextEngine** — StrangeLoop is instantiated with a `core_agent` and `loop_planner`. ContextEngine activates goals and assigns them to StrangeLoop via `loop_id`. StrangeLoop reports back via `complete_goal`/`fail_goal`.
- **SootheRunner** — the runner's `StrangeLoopMixin` creates and drives StrangeLoop, passing intent classification, workspace, and routing hints.
- **CoreAgent** — step execution delegates to `agent.astream()` or `agent.execution_astream()` (the checkpointer-free twin for high-volume streaming).

### Skill Handling

A non-obvious behavior: StrangeLoop parses slash-skill invocations from the goal text (`parse_slash_skill_user_line`). When a skill is addressed, it syncs only that skill to the workspace (targeted sync, not full sync). If no skill is addressed, sync is skipped entirely — skills are synced on-demand via middleware.

---

## Minimal Usage

```python
from soothe.foundation.sloop.engine.strange_loop import StrangeLoop

loop = StrangeLoop(core_agent=agent, loop_planner=planner, config=config)
async for event_type, event_data in loop.run_with_progress(
    goal="Analyze the codebase structure",
    thread_id="thread-123",
):
    if event_type == "completed":
        result = event_data["result"]  # PlanResult
```

In practice, you rarely instantiate StrangeLoop directly — the runner handles it. The runner passes `intent`, `routing_classification`, `workspace`, `clarification_policy`, and `proposal_queue` (RFC-204 Group C for Layer 2 tool proposals).

---

## Gotchas

- **`run()` vs `run_with_progress()`** — `run()` is a convenience wrapper that consumes `run_with_progress()` and returns the final `PlanResult`. If you need streaming events, use `run_with_progress()`.
- **Loop state persistence uses `loop_id`** — not `thread_id`. The loop graph checkpoints under `loop_id`, which is separate from the CoreAgent's `thread_id` checkpoint. Both are needed for full resumption.
- **`status="replan"` with `plan_action="new"` requires a `decision`** — the validator enforces this. If the LLM returns `replan` + `new` without steps, it's a schema error.
- **Bootstrap actions** — the first iteration may have `terminal_after_execute=True`, meaning the plan asserts its single step is the answer. This skips the second assessment, which is correct for simple goals but wrong if the step fails.
- **SharedPostgreSQLPool** — for high-concurrency deployments, StrangeLoop accepts a `shared_pool` parameter (IG-406) for state persistence. Without it, each loop creates its own connection.

---

## Related

- **[ContextEngine](goal-engine.md)** — Layer 3 goal management
- **[Agent Factory](agent-factory.md)** — Layer 1 execution
- **[SootheRunner](runner.md)** — runner that drives StrangeLoop
- **[RFC-201](../../specs/RFC-201-strangeloop-plan-execute-loop.md)** — full specification

# PlannerProtocol & LoopPlannerProtocol

**RFCs**: 304 (Planner), 604 (LoopPlanner two-phase), 226 (continuation routing)
**Locations**:
- `packages/soothe/src/soothe/protocols/planner.py`
- `packages/soothe/src/soothe/protocols/loop_planner.py`
**Status**: Implemented

## What the Planner Protocols Are

Soothe defines two planner protocols for goal decomposition and execution planning. Both implement the **plan-driven execution** principle (RFC-000 Principle 6): complex goals are decomposed into structured, executable steps with dependency tracking — not executed ad hoc.

1. **`PlannerProtocol`** — goal decomposition into structured plans with steps, reflection, and revision. The "create a plan from a goal" interface.
2. **`LoopPlannerProtocol`** — the StrangeLoop Plan phase: assess progress each iteration and decide the next executable fragment. The "what should I do next in this loop?" interface.

They serve different lifecycles: `PlannerProtocol` creates the initial decomposition; `LoopPlannerProtocol` drives iterative re-planning within a running loop.

## PlannerProtocol

### Role

`PlannerProtocol` takes a goal and available context, then decomposes it into a `Plan` — an ordered list of `PlanStep`s with DAG dependencies and concurrency configuration. It also handles:

- **`create_plan(goal, context) → Plan`** — decompose a goal into steps.
- **`revise_plan(plan, reflection, thread_id?) → Plan`** — revise a plan based on reflection feedback (e.g., a step failed). Optional `thread_id` for Langfuse session correlation.
- **`reflect(plan, step_results, goal_context?, sloop_result?) → Reflection`** — evaluate progress and recommend goal changes, including goal directives for autonomous management.

### DAG-Based Step Dependencies

Steps declare dependencies via `depends_on` (a list of step IDs). This forms a DAG that the executor respects:

```
S1 (research) → S2 (design) → S3 (implement) ─┐
                              S4 (write tests) ─┘→ S5 (integration tests)
```

Steps with no unmet dependencies can run in parallel. The DAG enables parallel execution *where safe* while preventing invalid orderings (you can't write tests before the design exists).

### Execution Hints

Each `PlanStep` carries an `execution_hint` guiding how it should run:

- **`tool`** — direct tool invocation
- **`subagent`** — delegate to a named subagent
- **`remote`** — delegate to a remote agent
- **`auto`** — planner/runtime selects the appropriate method (default)

This lets the planner encode routing intent ("this step needs the research subagent") without the executor hardcoding logic.

### ConcurrencyPolicy

Every `Plan` carries a `ConcurrencyPolicy` controlling parallelism at multiple levels:

- `max_parallel_goals` — concurrent goals in autonomous mode
- `max_parallel_steps` — concurrent plan steps in one batch
- `max_parallel_subagents` — concurrent subagents
- `global_max_llm_calls` — cross-level circuit breaker for LLM invocations
- `step_parallelism` — scheduling strategy: `sequential`, `dependency` (DAG-aware), or `max`

A special value: `0` means "unlimited." The `global_max_llm_calls` circuit breaker prevents rate-limit exhaustion across all concurrency levels simultaneously.

## LoopPlannerProtocol

### Role

`LoopPlannerProtocol` is the StrangeLoop Plan phase. Each loop iteration, it answers: "is the goal complete? If not, what's the next executable fragment?" It returns a unified `PlanResult` with a `plan_action` of either `'keep'` (use existing plan) or `'new'` (here's a new decision).

### The Two-Phase Architecture (RFC-604)

The key design decision: **assessment and generation are separate phases**.

- **Phase 1 — `assess_status(goal, state, context) → StatusAssessment`**: a lightweight check: is the goal complete, incomplete, or failed? Should we continue, retry, or abort?
- **Phase 2 — `generate_from_assessment(...) → PlanResult`**: expensive plan generation, *only when assessment says work remains*.

If Phase 1 returns `complete`, Phase 2 is skipped entirely. This saves tokens — you don't generate a new plan when the goal is already done.

The unified `plan()` method orchestrates both phases: assess first, generate only if needed.

### Continuation Routing (RFC-226, coordinated with RFC-630 intake)

Mid-loop follow-ups coordinate **intake label** with optional **continuation-assess**:

| Intake (continuation turn) | Route | Continuation-assess LLM |
|----------------------------|-------|-------------------------|
| `trivial` | `plan_assess` → bootstrap or `plan_generate` | Only for ambiguous trivial goals |
| `simple` | `plan_generate` (lightweight) | Skipped |
| `complex` | `bounded_evidence_gather` → full spine | Skipped |
| `continue` keyword | deterministic bootstrap | Skipped |

`assess_continuation()` remains the trivial-path discriminator (`bootstrap` vs `plan_generate`). Simple/complex intake never bootstraps.

### Progressive Planning with PlanManager

Both `plan()` and `generate_from_assessment()` accept an optional `plan_manager` parameter for **DAG-aware progressive planning**. Instead of regenerating the entire plan each iteration, `PlanManager` evolves the existing plan graph — adding/removing steps as understanding grows. This is more token-efficient and preserves execution continuity.

### PlanResult

The unified return carries:
- `status` — `complete` / `incomplete` / `failed`
- `plan_action` — `keep` (use existing plan) or `new` (new decision provided)
- `decision` — the new execution decision (only when `plan_action='new'`)
- `ux_preview` / `evidence_summary` — user-facing and structured summaries

## Backend: LLMPlanner

A single unified implementation (`LLMPlanner`) implements **both** protocols. Key characteristics:

- Two-phase architecture (RFC-604): `StatusAssessment` → conditional `PlanGeneration`
- Model-agnostic (works with any LangChain chat model)
- Progressive planning via `PlanManager`
- Continuation routing (RFC-226)
- Token-efficient schema trimming (IG-329) — strips unnecessary fields from LLM-bound schemas

> **History note**: Earlier versions had multiple planner tiers (`AutoPlanner`, `ClaudePlanner`, `SubagentPlanner`). IG-150 consolidated these into the unified `LLMPlanner`.

## Integration Points

### Planner ↔ StrangeLoop

The Plan → Execute cycle:

```
Plan phase (LoopPlanner):
  1. assess_status() → StatusAssessment
  2. generate_from_assessment() → PlanResult (if incomplete)
  3. Return decision (keep/new)

Execute phase (CoreAgent):
  1. Execute decision via tools/subagents
  2. Collect results into StepResult
  3. Update plan/step status

→ next iteration → Plan phase again
```

### Planner ↔ Context

`PlanContext` carries `capabilities` (available tools/subagents), `workspace`, `thread_id`, and `completed_steps` (a summary dict of step ID → result). The planner uses completed-step summaries to make informed decisions about what to do next — it doesn't re-examine raw outputs.

### Planner ↔ Working Memory

`LoopPlannerProtocol` receives `LoopState` which includes `step_results` and the prior plan. `LoopWorkingMemoryProtocol.render_for_reason()` provides a bounded view of recent outcomes injected into the planner's prompt. See [loop-protocols.md](loop-protocols.md).

## Design Rationale

### Why Two-Phase Architecture?

Token efficiency. Phase 1 (assessment) is a lightweight structured LLM call; Phase 2 (generation) is expensive. Skipping Phase 2 when the goal is complete avoids wasteful plan generation. In a multi-iteration loop, this compounds — most iterations after completion are cheap assessments, not full replans.

### Why DAG Dependencies?

Complex goals require ordered execution: design before implementation, implementation before tests. But naive sequential execution wastes time when steps are independent. The DAG enables parallel execution where safe while preventing invalid orderings.

### Why Concurrency Limits?

Uncontrolled parallelism exhausts LLM rate limits and causes resource contention. `ConcurrencyPolicy` makes limits configurable per deployment — a dev machine caps at 2 parallel steps; a production cluster allows more. The `global_max_llm_calls` cross-level breaker is the safety net that prevents cascading rate-limit failures.

## Gotchas

- **`plan_action='keep'` means no new decision** — when the assessment says "keep existing plan," `PlanResult.decision` is `None`. Consumers must check `plan_action` before accessing `decision`.
- **`revise_plan` is separate from `reflect`** — reflection evaluates progress and recommends changes; revision actually produces a new plan. They're often chained but are distinct operations.
- **`execution_hint='auto'` is a suggestion, not a guarantee** — the runtime may override based on available capabilities.
- **Concurrency `0` means unlimited** — not "disabled." This is a footgun if you expect `0` to mean "no parallelism."

## Configuration

```yaml
agent:
  protocols:
    planner:
      enabled: true
      llm_role: planner
      max_iterations: 8
      concurrency:
        max_parallel_goals: 1
        max_parallel_steps: 2
        max_parallel_subagents: 4
        global_max_llm_calls: 5
        step_parallelism: dependency
```

Resolved via `resolve_planner(config)` and `resolve_loop_planner(config)` — both return `LLMPlanner` instances.

## Specification Reference

- **RFC-304**: Planner Protocol Architecture
- **RFC-604**: Two-phase architecture (Reason Phase Robustness)
- **RFC-226**: Continuation-Aware Plan Assessment
- **RFC-211**: Layer2 Tool Result Optimization (outcome metadata)
- **RFC-200**: Autonomous Goal Management

## Related Documentation

- [StrangeLoop Architecture](../core/strangeloop.md)
- [Execution Protocols](execution-protocols.md) — runner orchestrates the planner
- [Loop Protocols](loop-protocols.md) — working memory feeds the planner

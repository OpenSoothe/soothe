# RFC-226: Continuation-Aware plan_assess and Post-Execute Fast Exit

**RFC**: 226
**Title**: Continuation-Aware plan_assess and Post-Execute Fast Exit
**Status**: Draft
**Kind**: Architecture Design
**Authors**: xiaming
**Created**: 2026-05-29
**Last Updated**: 2026-05-29
**Depends on**: RFC-220, RFC-225
**Related**: RFC-214 (loop-message surface), RFC-217 (goal-context management), RFC-604 (reason-phase split)
**Supersedes**: ---

---

## 1. Abstract

RFC-225 made `continue_loop` the default for follow-up agentic queries in an existing loop. The Loop Graph (RFC-220) still runs the full planning topology for every query, mediated by a structural heuristic (`continue_loop_plan_bootstrap_allowed`) that installs a synthetic single-step "bootstrap" plan on iter=0 and then invokes a redundant iter=1 status-check LLM call. The heuristic mis-routes multi-step continuations and the iter=1 LLM call is wasted work. This RFC promotes `plan_assess` to the single LLM-driven discriminator on iter=0 of a continuation: it reads the new query against the persisted prior goals (RFC-225 enrichment) and routes to either a terminal bootstrap path or the full `plan_generate` flow. A new `PlanResult.terminal_after_execute` field plus one new conditional edge (`record_iteration → goal_completion`) eliminate the iter=1 status check on the bootstrap path.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

- The continuation-aware behavior of `plan_assess` on iter=0 when `continue_loop_mode` is True and `goal_history` has at least one completed prior goal.
- A new structured-output schema `ContinuationAssessment` and prompt template `LOOP_CONTINUATION_ASSESS_PROMPT` for the discriminator LLM call.
- A new `PlanResult.terminal_after_execute: bool` field that marks a plan whose single step IS the goal completion.
- A single new conditional edge in the Loop Graph from `record_iteration` to `goal_completion` when the active plan is terminal.
- Removal of the `continue_loop_plan_bootstrap_allowed()` structural heuristic — the LLM owns the bootstrap-vs-plan decision.

### 2.2 Non-Goals

This RFC does **not** change:

- The Loop Graph topology for fresh goals (no prior history). That path is unchanged.
- The `plan_generate` node or its prompts.
- `plan_assess` behavior for iter ≥ 1 on the `plan_generate` path (multi-step continuations still receive the existing status-check assess).
- The executor's `loop_messages` injection mechanism for the bootstrap step (RFC-225 / IG-445 §Fix D).
- The seeded-ledger seeding by `seed_loop_ledger_from_prior_goal()`.
- The off-graph intent classifier (RFC-225).
- The persistence schema for `StrangeLoopCheckpoint` or `GoalExecutionRecord` (beyond an additive default-False field on `PlanResult`).

---

## 3. Background and Motivation

### 3.1 Current behavior

After RFC-225, the Loop Graph runs the following topology for every agentic query:

```
init_or_resume → iteration_gate → iteration_start → bounded_evidence_gather
  → plan_assess → resolve_decision → validate_evidence_bindings
  → execute → record_iteration → iteration_gate
  → plan_assess → goal_completion → END
```

For continuation queries (RFC-225 §5.2), `plan_assess` on iter=0 short-circuits the planner LLM when a structural heuristic fires:

```
continue_loop_plan_bootstrap_allowed :=
    continue_loop_mode
    AND state.iteration == 0
    AND not state.step_results
    AND (not recovery_valid_resume OR goal_record is clean)
```

When True, `plan_assess` constructs a single-step `PlanResult` via `build_continue_loop_bootstrap_plan(goal)` whose step description embeds the user request and prior-loop framing. The executor injects the seeded `loop_messages` from the prior goal as **full prior-goal execute-step Human/AI ledger replay** (`prior_loop_execute_messages()` — distinct from same-goal dependent steps, which use envelope `PRIOR STEP EVIDENCE` only per RFC-214 §3.1), and the step runs. iter=1 `plan_assess` then invokes the planner LLM to assess "are we done?" — which, on a one-step bootstrap, almost always returns `done`.

### 3.2 Observed defects

A representative continuation (loop id ending `…99d9`, second query "translate the result to chinese"):

| Phase | LLM call | Input tokens | Output tokens | Latency |
|---|---|---|---|---|
| intent_classify (off-graph) | think model | 620 | 47 | 2.3 s |
| iter=0 plan_assess (bootstrap) | skipped | — | — | <1 ms |
| execute bootstrap step | think model | 12 863 | 24 | 2.9 s |
| iter=1 plan_assess (status) | think model | 1 170 | 60 | 3.5 s |

Two structural problems:

1. **Heuristic mis-routing.** The discriminator is purely structural; it has no view of the new query's semantics or the prior goals' content. Continuations that genuinely need additional steps (e.g., "translate the result and email it to bob") are nonetheless routed to the synthetic single-step bootstrap, degrading the answer.
2. **Wasted iter=1 LLM call.** The bootstrap path commits to "one step IS the answer." The iter=1 status check that follows is pure overhead — a 1 170-token / 3.5 s call to confirm a decision the bootstrap path already implied.

### 3.3 Proposed direction

Promote `plan_assess` to be the LLM-driven discriminator on iter=0 of continuations. One LLM call evaluates the new query against the prior goals (RFC-225 enrichment makes the prior plan, step results, and goal completion durably available) and emits a structured decision: either a terminal bootstrap or escalation to `plan_generate`. Mark the bootstrap `PlanResult` with `terminal_after_execute=True`; route `record_iteration → goal_completion` when set. The graph topology changes by exactly one conditional edge.

---

## 4. Design Principles

1. **One LLM does the routing.** `plan_assess` on iter=0 of a continuation makes the bootstrap-vs-plan decision in a single LLM call that also produces the assessment fields. No structural heuristic.
2. **Bootstrap is a terminal commitment.** When the discriminator chooses `action="bootstrap"`, the resulting plan asserts "one step is the answer." The graph honors that by routing directly to `goal_completion` after `record_iteration`, with no second `plan_assess` call.
3. **`plan_generate` path is unchanged.** Multi-step continuations and fresh goals run the standard planner flow. The new behavior is strictly additive on the bootstrap path.
4. **Topology changes by exactly one edge.** All routing semantics flow through `PlanResult.terminal_after_execute` carried on the existing `LoopRuntimeContext.scratch.plan_result`. No new nodes, no parallel sub-graphs.
5. **Correctness first, cost second.** LLM call count on the bootstrap path stays at two (assess + execute), the same as today; the win is correctness — the assess LLM sees prior-goal context AND the new query and can correctly identify when `plan_generate` is needed instead of forcing bootstrap.

---

## 5. Architecture

### 5.1 plan_assess decision tree (iter=0)

```
plan_assess(state, iter=0):
  if continue_loop_mode AND len(checkpoint.goal_history) >= 2:
      assessment = await continuation_assess(
          current_goal = state.goal,
          prior_goals  = _prior_goal_summaries(checkpoint),
          capabilities = state.available_capabilities,
      )
      if assessment.action == "bootstrap":
          plan = build_continue_loop_bootstrap_plan(
              goal = state.goal,
              terminal_after_execute = True,
              reasoning = assessment.reasoning,
              goal_progress = assessment.goal_progress,
          )
          ctx.scratch.plan_result = plan
          route → resolve_decision
      else:  # action == "plan_generate"
          # Stash the assessment so plan_generate reuses reasoning + goal_progress
          # via the existing ctx.scratch.plan_assessment carrier.
          ctx.scratch.plan_assessment = assessment
          route → plan_generate
  else:
      # Fresh goal: existing assess flow (unchanged)
      assessment = await plan_assess_existing(state)
      route → (goal_completion | plan_generate) per existing rules
```

For iter > 0 (multi-step continuations and ongoing `plan_generate` paths), `plan_assess` runs the existing status-check assess unchanged. The bootstrap path never reaches iter > 0 because `terminal_after_execute=True` short-circuits to `goal_completion` after the single execute step.

### 5.2 PlanResult schema addition

```python
class PlanResult(BaseModel):
    # ... existing fields ...
    terminal_after_execute: bool = Field(
        default=False,
        description=(
            "When True, the plan asserts that its single step IS the goal "
            "completion. The Loop Graph routes from record_iteration directly "
            "to goal_completion, skipping the iter=1 plan_assess status check. "
            "Set by the continuation-aware plan_assess for bootstrap actions."
        ),
    )
```

Default `False` preserves existing behavior for every other code path. Existing persisted `PlanResult` rows deserialize unchanged.

### 5.3 Loop Graph topology — one new conditional edge

Today (single transition):

```python
graph.add_conditional_edges(
    "record_iteration",
    route_after_record_iteration,
    {"iteration_gate": "iteration_gate", END: END},
)
```

New:

```python
graph.add_conditional_edges(
    "record_iteration",
    route_after_record_iteration,
    {
        "iteration_gate": "iteration_gate",
        "goal_completion": "goal_completion",   # NEW (RFC-226)
        END: END,
    },
)
```

`route_after_record_iteration` reads `terminal_after_execute` off the active plan via `LoopRuntimeContext.scratch.plan_result`:

```python
def route_after_record_iteration(ctx, state) -> str:
    plan = getattr(ctx.scratch, "plan_result", None)
    if plan is not None and getattr(plan, "terminal_after_execute", False):
        return "goal_completion"
    return existing_route(ctx, state)
```

The carrier is the same `ctx.scratch.plan_result` slot that `plan_assess` writes and `resolve_decision` reads — no new state field is required beyond `PlanResult.terminal_after_execute` itself.

### 5.4 ContinuationAssessment schema

```python
class ContinuationAssessment(BaseModel):
    """Iter=0 routing decision for continuation queries (RFC-226)."""

    action: Literal["bootstrap", "plan_generate"] = Field(
        description=(
            "bootstrap: a single execute step using prior loop context can answer "
            "the query directly (no new tools needed). plan_generate: the query "
            "requires multiple steps, new tools, or cross-domain work — escalate "
            "to the full planner."
        ),
    )
    reasoning: str = Field(
        default="", max_length=400,
        description="One-sentence justification for the chosen action.",
    )
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = Field(
        default="low",
        description="Initial progress estimate (matches PlanResult.goal_progress).",
    )
```

### 5.5 LOOP_CONTINUATION_ASSESS_PROMPT

```
You are deciding how to handle a follow-up query in an in-progress conversation loop.

CURRENT REQUEST:
{state.goal}

PRIOR GOALS IN THIS LOOP:
{prior_goals_table}
  goal_id | goal_text                       | completion (≤200 chars)        | steps
  ────────┼─────────────────────────────────┼────────────────────────────────┼──────
  goal_0  | count all file types            | There are 12 file types …      | 1
  goal_1  | summarize them                  | The repo is mostly Python …    | 1

AVAILABLE CAPABILITIES: {capabilities[:30]}

DECISION CRITERIA:
- Choose **bootstrap** when the current request can be answered using prior conversation
  context alone (e.g., "translate that", "summarize the result", "explain it in chinese")
  with no new tools or cross-domain work.
- Choose **plan_generate** when the current request needs multiple steps, new tool calls,
  or addresses a topic not covered by prior goals.

Return a ContinuationAssessment JSON object.
```

The model role mirrors today's `plan_assess`: the `think` role from the configured planner. Latency budget: comparable to today's iter=1 `plan_assess` call (~3 s, 1–2 K input tokens for typical short conversations).

### 5.6 _prior_goal_summaries helper

```python
def _prior_goal_summaries(checkpoint: StrangeLoopCheckpoint) -> list[dict]:
    """Compact summary of completed prior goals for the continuation assess prompt."""
    out: list[dict] = []
    for g in checkpoint.goal_history[:-1]:  # exclude the active new goal
        if g.status != "completed":
            continue
        out.append({
            "goal_id": g.goal_id,
            "goal_text": g.goal_text,
            "completion": preview_first(g.goal_completion, 200),
            "step_count": len(g.step_results),
            "current_plan_action": (
                g.current_plan.next_action if g.current_plan else ""
            ),
        })
    return out
```

The helper draws directly from `GoalExecutionRecord` fields persisted under RFC-225: `current_plan`, `step_results`, and `goal_completion`.

### 5.7 Data flow

```
User query (continuation)
       │
       ▼
intent_classifier  ─── (off-graph; quiz vs agentic, RFC-225)
       │
       ▼ agentic
StrangeLoop.run_with_progress()
       │  derives continue_loop_mode (RFC-225 §5.2)
       ▼
init_or_resume → iteration_gate → iteration_start → bounded_evidence_gather
       │
       ▼
plan_assess
       │
       ├── (continue_loop AND goal_history ≥ 2):
       │       continuation_assess_llm()
       │       │
       │       ├── action="bootstrap":
       │       │     build_continue_loop_bootstrap_plan(terminal_after_execute=True)
       │       │     → resolve_decision → execute (seeded loop_messages, IG-445 §Fix D)
       │       │     → record_iteration → goal_completion → END
       │       │
       │       └── action="plan_generate":
       │             → plan_generate → resolve_decision → execute
       │             → record_iteration → iteration_gate
       │             → plan_assess (iter=1+, existing status-check)
       │             → goal_completion (when done)
       │
       └── (fresh goal):
             → plan_generate (existing flow, unchanged)
```

---

## 6. Cost and Behavior

| Scenario | LLM in graph (today) | LLM in graph (RFC-226) | Routing quality |
|---|---|---|---|
| Continuation, chat-like (translate, summarize, explain) | 2 (execute + iter1-assess) | 2 (continuation-assess + execute) | Better — assess sees prior context and new query before deciding; no generic step |
| Continuation, multi-step ("translate AND email") | 2 (mis-routed bootstrap → degraded) | 3+ (assess + generate + execute + …) | Correct — LLM escalates to plan_generate |
| Continuation, needs new tool (no prior coverage) | 2 (mis-routed bootstrap → degraded) | 3+ (assess + generate + execute + …) | Correct — LLM escalates to plan_generate |
| Fresh goal (first query in loop) | 3+ (assess + generate + …) | 3+ (assess + generate + …) | Unchanged |
| Goal recovery / valid resume | unchanged | unchanged | Unchanged |

The bootstrap path's LLM call count is unchanged. The win is correctness and elimination of a redundant status check.

---

## 7. Invariants

- **(I-1)** When `continue_loop_mode` is False, `plan_assess` MUST NOT invoke the continuation discriminator. The existing assess flow runs unchanged.
- **(I-2)** `terminal_after_execute=True` MAY only be set by `build_continue_loop_bootstrap_plan` (or its direct callers) and MUST NOT be set on any plan produced by `plan_generate`.
- **(I-3)** When `terminal_after_execute=True`, the bootstrap plan MUST have exactly one step.
- **(I-4)** `route_after_record_iteration` MUST route to `goal_completion` whenever `ctx.scratch.plan_result.terminal_after_execute` is True AND the step succeeded. Failure of the step routes through the existing failure path (max_iterations_terminal or status="failed" → goal_completion).
- **(I-5)** The continuation discriminator MUST only consider completed prior goals (`status == "completed"`). Failed or cancelled goals do not contribute to the assess prompt.

---

## 8. Migration and Compatibility

Clean cut — no backward-compatibility shims.

- `PlanResult.terminal_after_execute` defaults to `False`; old persisted `PlanResult` rows deserialize without change.
- The new `"goal_completion"` value in `record_iteration`'s conditional-edges map is purely additive. The existing route function continues to return the same value space; only the bootstrap path returns the new value.
- Live daemons mid-deploy: until the new code rolls out, continuations still use the existing structural bootstrap heuristic. After rollout, continuations use LLM-driven discrimination.
- No persisted schema changes beyond the additive `PlanResult` field.

---

## 9. Examples

### 9.1 Continuation, chat-like → bootstrap path

```
Loop history: [goal_0("count all file types") → completion="There are 12 file types: …"]
User: "translate the result to chinese"

plan_assess(iter=0):
  continuation_assess_llm(...) → ContinuationAssessment(
      action="bootstrap",
      reasoning="Pure translation of prior result; no new tools needed.",
      goal_progress="low",
  )
  plan = build_continue_loop_bootstrap_plan(
      goal="translate the result to chinese",
      terminal_after_execute=True,
      reasoning="…",
  )
  → resolve_decision

resolve_decision → execute (LLM with seeded loop_messages of goal_0; 1 LLM call)
record_iteration → terminal_after_execute=True → goal_completion → END

In-graph LLM calls: 2 (assess + execute).
Result: agent returns Chinese translation of the 12 file-types list.
```

### 9.2 Continuation, multi-step → plan_generate path

```
Loop history: [goal_0("count all file types") → completion="There are 12 file types: …"]
User: "translate the result and email it to bob@example.com"

plan_assess(iter=0):
  continuation_assess_llm(...) → ContinuationAssessment(
      action="plan_generate",
      reasoning="Requires a new email-send step in addition to translation.",
      goal_progress="none",
  )
  → plan_generate

plan_generate → resolve_decision → execute → record_iteration → iteration_gate
  → plan_assess (iter=1) → (continue|done) → …

In-graph LLM calls: 3+ (assess + generate + execute + iter1-assess + …).
Result: agent runs translate step, then email step, marks goal done.
```

### 9.3 Fresh goal → existing flow, unchanged

```
Loop history: []
User: "set up a redis cache for the user-session table"

plan_assess(iter=0):
  continue_loop_mode is False — existing assess flow
  → plan_generate

(unchanged from today)
```

---

## 10. Relationship to Other RFCs

- **RFC-220 (LangGraph Agent Loop Orchestrator)** — Defines the Loop Graph topology this RFC extends with one new conditional edge. The plan / execute / assess node identities are unchanged.
- **RFC-225 (Loop Continuity and Goal Record Enrichment)** — Provides the persisted per-goal data (`current_plan`, `step_results`, `goal_completion`) that the continuation discriminator consumes. Also provides the seeded `loop_messages` ledger consumed by the executor for the bootstrap step.
- **RFC-214 (StrangeLoop Loop-Message Surface)** — Defines unified planner assembly (§4, P6): `assemble_planner_prompt`, two projection modes, task envelope format. RFC-226 continuation discriminator consumes this assembler instead of a standalone inline prompt. Prior-goal narrative comes from projected ledger + `PRIOR GOALS` tree; checkpoint `goal_completion` is fallback when ledger caps drop completion turns.
- **RFC-217 (Goal Context Management)** — Unaffected. `thread_switch_pending` and `GoalContextManager` continue to operate as specified.
- **RFC-604 (Reason-Phase Robustness)** — The `assess` / `generate` split persists; this RFC adds a third structured-output schema (`ContinuationAssessment`) sitting alongside the existing `StatusAssessment` and `PlanGeneration` schemas.

---

## 11. Open Questions

1. **Dedicated `assess_continuation()` method vs extending `assess()`.** Today's planner exposes `assess()` returning `StatusAssessment`. The cleanest separation is a parallel `assess_continuation()` returning `ContinuationAssessment`. An alternative — making `assess()` polymorphic on a context flag — couples two concerns. Recommendation: dedicated method.
2. **Cap on `_prior_goal_summaries` length.** Long loops with many prior goals could bloat the discriminator prompt. A future config knob `loop.continuation_assess.max_prior_goals` can cap (default: last 5 completed goals). Out of scope for the initial implementation.
3. **Inline answer in the discriminator.** A future optimization: when `action="bootstrap"` AND the prior context already contains the answer, the discriminator could emit the answer inline, removing even the execute LLM call. Not in scope for this RFC.

---

## 12. Conclusion

`plan_assess` becomes the single decision-maker for continuation queries: one LLM call evaluates the new query against persisted prior goals (RFC-225) and routes to either a terminal bootstrap or the full `plan_generate` flow. The bootstrap path commits to a one-shot answer and skips the iter=1 status check by routing `record_iteration → goal_completion` directly. The `plan_generate` path is unchanged. The change is additive — one `PlanResult` field, one new graph edge, one new prompt and schema — preserves all RFC-225 invariants, and replaces a heuristic mis-router with an LLM-informed one.

> Let the planner decide whether to plan.

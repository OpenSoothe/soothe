# Continuation-Aware plan_assess + Post-Execute Fast Exit

**Date:** 2026-05-29
**Status:** Draft (Platonic Brainstorming output)
**Builds on:** RFC-220 (LangGraph Agent Loop Orchestrator), RFC-225 (Loop Continuity and Goal Record Enrichment), RFC-604 (Reason-phase robustness)
**Scope:** Make `plan_assess` the single LLM-driven discriminator that, for any continuation query in an existing loop, decides between a one-shot bootstrap path or full plan generation; eliminate the redundant iter=1 status-check LLM call on the bootstrap path.

---

## 1. Motivation

RFC-225 made `continue_loop` the default for follow-up queries in a loop. The Loop Graph today still executes the planning-first topology for every query:

```
init_or_resume → iteration_gate → iteration_start → bounded_evidence_gather
  → plan_assess → resolve_decision → validate_evidence_bindings
  → execute → record_iteration → iteration_gate
  → plan_assess → goal_completion → END
```

For continuation queries (RFC-225 §5.2), the existing optimization is a synthetic bootstrap: `plan_assess` on iter=0 skips the planner LLM and installs a single-step `PlanResult` whose step description is `"Address the user's request using prior conversation context from earlier goals in this loop: {goal}"`. The execute step then runs the agent with seeded prior `loop_messages`, and iter=1 `plan_assess` invokes the planner LLM to ask "are we done?" — which almost always returns `done`.

Trace of a real continuation (`trace-db8128ed7650ffc9150400cdb7086182.json`, loop `…99d9`, query "translate the result to chinese"):

| Phase | LLM call | Input tokens | Output tokens | Latency |
|---|---|---|---|---|
| Intent classify | gpt-style 1 | 620 | 47 | 2.3s |
| iter=0 plan_assess | (skipped, bootstrap) | — | — | <1ms |
| execute bootstrap step | gpt-style 1 | 12863 | 24 | 2.9s |
| iter=1 plan_assess | gpt-style 1 | 1170 | 60 | 3.5s |

Two LLM calls inside the loop graph (execute + iter=1 status-check) and an off-graph intent classifier — for what is conceptually one chat turn. Two structural problems:

1. **Structural mis-routing.** The bootstrap path is gated on heuristic conditions (`continue_loop_plan_bootstrap_allowed`): `continue_loop_mode AND iter==0 AND no step_results`. It fires for every continuation query regardless of whether the query actually fits a one-step answer. A multi-step continuation ("translate AND email to bob") gets the same generic single-step plan and degrades quality.
2. **Wasted iter=1 LLM.** After the bootstrap step finishes, iter=1 `plan_assess` always runs the planner LLM to ask a question the bootstrap path already implied: "the step is the goal; we're done." The 1170-token / 3.5s call is pure overhead in this case.

The fix is to make `plan_assess` an LLM-driven discriminator on iter=0 of continuations and skip the post-execute status check when the decision was bootstrap.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This design defines:

- The continuation-aware behavior of `plan_assess` on iter=0 when `continue_loop_mode` is True.
- A new structured-output schema (`ContinuationAssessment`) and prompt for the discriminator LLM call.
- A new `PlanResult.terminal_after_execute: bool` field that marks a plan whose single step IS the goal completion.
- A single new conditional edge in the Loop Graph from `record_iteration` to `goal_completion` when the active plan is terminal.
- Removal of the structural `continue_loop_plan_bootstrap_allowed()` heuristic — LLM owns the bootstrap-vs-plan decision now.

### 2.2 Non-Goals

This design does NOT change:

- The Loop Graph topology for fresh goals (no prior history) — that path is unchanged.
- The plan_generate path or its prompts.
- iter=1+ `plan_assess` behavior for the plan_generate path (multi-step continuations still get the standard status check).
- The executor's loop_messages injection (Fix D from RFC-225 implementation stays).
- The seeded-ledger seeding by `seed_loop_ledger_from_prior_goal()`.
- The intent classifier (off-graph, unchanged).

---

## 3. Design Principles

1. **One LLM does the routing.** `plan_assess` on iter=0 of a continuation makes the bootstrap-vs-plan decision in a single LLM call that also produces the assessment fields. No structural heuristic.
2. **Bootstrap is a terminal commitment.** When `plan_assess` chooses `action="bootstrap"`, the resulting plan asserts "one step is the answer." The graph honors that by routing directly to `goal_completion` after `record_iteration`, with no second `plan_assess` call.
3. **plan_generate path is unchanged.** Multi-step continuations and fresh goals run the standard planner flow. The new behavior is strictly additive on the bootstrap path.
4. **The graph topology changes by exactly one edge.** All routing semantics flow through `state.current_decision` / `PlanResult.terminal_after_execute`. No new nodes, no parallel sub-graphs.
5. **Quality first, cost second.** LLM call count in the bootstrap path stays at 2 (assess + execute), same as today. The win is correctness: the LLM sees prior-goal context AND the new query, and can correctly identify when plan_generate is needed instead of forcing bootstrap.

---

## 4. Architecture

### 4.1 plan_assess decision tree (iter=0)

```
plan_assess(state, iter=0):
  if continue_loop_mode AND len(checkpoint.goal_history) >= 2:
      # NEW: continuation-aware LLM call
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
      else:  # "plan_generate"
          # Stash the assessment so plan_generate can reuse the reasoning + goal_progress
          # via the existing ctx.scratch.plan_assessment carrier.
          ctx.scratch.plan_assessment = assessment
          route → plan_generate
  else:
      # Existing assess flow (fresh goal, no prior context)
      assessment = await plan_assess_existing(state)
      route → (goal_completion | plan_generate) per existing rules
```

For iter > 0 (multi-step continuations and ongoing plan_generate paths), `plan_assess` runs the existing status-check assess. The bootstrap path never reaches iter > 0 because `terminal_after_execute=True` short-circuits to `goal_completion`.

### 4.2 PlanResult schema addition

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

Default `False` preserves existing behavior for every other code path.

### 4.3 Loop Graph topology — one conditional edge

Today:

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
        "goal_completion": "goal_completion",   # NEW
        END: END,
    },
)
```

`route_after_record_iteration` reads `terminal_after_execute` off the active plan via `LoopRuntimeContext.scratch.plan_result` (the same carrier `resolve_decision` already uses):

```python
def route_after_record_iteration(ctx, state) -> str:
    plan = getattr(ctx.scratch, "plan_result", None)
    if plan is not None and getattr(plan, "terminal_after_execute", False):
        # Bootstrap step finished; this IS the goal completion.
        return "goal_completion"
    return existing_route(ctx, state)
```

`LoopRuntimeContext.scratch.plan_result` is the canonical carrier — `plan_assess` writes it, `resolve_decision` reads it, and this route reads `terminal_after_execute` off it. No new state field needed beyond `PlanResult.terminal_after_execute` itself.

### 4.4 Continuation assess LLM prompt + schema

New Pydantic model:

```python
class ContinuationAssessment(BaseModel):
    """Iter=0 routing decision for continuation queries (this design)."""
    action: Literal["bootstrap", "plan_generate"] = Field(
        description=(
            "bootstrap: a single execute step using prior loop context can answer "
            "the query directly (no new tools needed). plan_generate: the query "
            "requires multiple steps, new tools, or cross-domain work — escalate to "
            "the full planner."
        ),
    )
    reasoning: str = Field(
        default="", max_length=400,
        description="One-sentence justification for the chosen action.",
    )
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = Field(
        default="low",
        description="Initial progress estimate (matches existing PlanResult.goal_progress).",
    )
```

Prompt template `LOOP_CONTINUATION_ASSESS_PROMPT` body (sketch):

```
You are deciding how to handle a follow-up query in an in-progress conversation loop.

CURRENT REQUEST:
{state.goal}

PRIOR GOALS IN THIS LOOP:
{prior_goals_table}
  goal_id | goal_text                       | completion (≤200 chars)        | steps
  ────────┼─────────────────────────────────┼────────────────────────────────┼──────
  goal_0  | count all file types            | There are 12 file types ...    | 1
  goal_1  | summarize them                  | The repo is mostly Python ...  | 1

AVAILABLE CAPABILITIES: {capabilities[:30]}

DECISION CRITERIA:
- Choose **bootstrap** when the current request can be answered using prior conversation
  context alone (e.g., "translate that", "summarize the result", "explain it in chinese")
  with no new tools or cross-domain work.
- Choose **plan_generate** when the current request needs multiple steps, new tool calls,
  or addresses a topic not covered by prior goals.

Return a ContinuationAssessment JSON object.
```

LLM model role: `think` (the same role used by today's iter=0/iter=1 plan_assess).

### 4.5 _prior_goal_summaries helper

```python
def _prior_goal_summaries(checkpoint: AgentLoopCheckpoint) -> list[dict]:
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

RFC-225 enrichment guarantees `current_plan`, `step_results`, and `goal_completion` are persisted per goal — the summary draws directly from `GoalExecutionRecord` fields.

### 4.6 Data flow

```
User query (continuation)
       │
       ▼
intent_classifier  ─── (off-graph; quiz vs agentic)
       │
       ▼ agentic
AgentLoop.run_with_progress()
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
       │       │     → resolve_decision → execute (with seeded loop_messages)
       │       │     → record_iteration → goal_completion → END
       │       │
       │       └── action="plan_generate":
       │             → plan_generate → resolve_decision → execute
       │             → record_iteration → iteration_gate
       │             → plan_assess (iter=1+, existing status-check)
       │             → goal_completion (when done)
       │
       └── (fresh goal):
             → plan_generate (existing flow)
             → ... (existing flow) ...
```

---

## 5. Cost / Behavior Summary

| Scenario | LLM in graph (today) | LLM in graph (this design) | Routing quality |
|---|---|---|---|
| Continuation, chat-like (translate, summarize, explain) | 2 (execute + iter1-assess) | 2 (continuation-assess + execute) | Better: LLM sees prior context AND new query before deciding |
| Continuation, multi-step ("translate AND email") | 2 (mis-routed bootstrap → degraded) | 3+ (assess + generate + execute + ...) | Correct: LLM escalates to plan_generate |
| Continuation, needs new tool (no prior coverage) | 2 (mis-routed bootstrap → degraded) | 3+ (assess + generate + execute + ...) | Correct: LLM escalates to plan_generate |
| Fresh goal (first query in loop) | 3+ (assess + generate + ...) | 3+ (assess + generate + ...) | Unchanged |
| Goal recovery / valid resume | unchanged | unchanged | Unchanged |

The bootstrap path's LLM call count is the same as today — but the calls are placed where they do useful work. iter=1's redundant status check is gone.

---

## 6. Files Touched

| Area | File | Change |
|---|---|---|
| Orchestration | `core/loop/orchestrator/nodes/plan_assess.py` | New `_continuation_assess()` discriminator path; iter=0 entry split between continuation and fresh-goal modes; remove `continue_loop_plan_bootstrap_allowed()` heuristic gating |
| Orchestration | `core/loop/orchestrator/nodes/record_iteration.py` | New `route_after_record_iteration` discriminator that returns `"goal_completion"` when the active plan is `terminal_after_execute=True` |
| Orchestration | `core/loop/orchestrator/builder.py` | Add `"goal_completion"` to `record_iteration` conditional edges map |
| Schema | `core/loop/state/schemas.py` | Add `PlanResult.terminal_after_execute: bool = False` |
| Planner | `core/loop/planning/planner.py` | New `assess_continuation()` method (or extend existing planner with the new prompt + structured output schema) |
| Planner | `core/loop/planning/prompts.py` | New `LOOP_CONTINUATION_ASSESS_PROMPT` template |
| Planner | `core/loop/planning/models.py` (or wherever PlanResult lives) | New `ContinuationAssessment` Pydantic model |
| Bootstrap | `core/loop/orchestrator/nodes/plan_assess.py` | `build_continue_loop_bootstrap_plan(goal, *, terminal_after_execute=True, reasoning="", goal_progress="low")` — extend signature |
| Tests | new: `tests/unit/core/loop/planning/test_continuation_assess.py` | LLM-mocked tests of the discriminator: bootstrap vs plan_generate for representative queries |
| Tests | update: `tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continue_thread.py` | Remove `continue_loop_plan_bootstrap_allowed` checks; replace with continuation_assess assertions |
| Tests | new: `tests/unit/core/loop/orchestrator/test_record_iteration_routing.py` | terminal_after_execute → goal_completion vs default → iteration_gate |

---

## 7. What We Keep / Drop

### Keep

| Item | Role |
|---|---|
| `seed_loop_ledger_from_prior_goal()` | Seeds the new goal's `loop_messages` from the immediately prior completed goal; consumed by Fix D injection in executor |
| `build_continue_loop_bootstrap_plan(goal, ...)` | Constructor for the bootstrap PlanResult; called when LLM says `action="bootstrap"` |
| Fix C bootstrap step description (includes `state.goal`) | Agent sees the actual user request in the step query |
| Fix D executor `loop_messages` injection | Prepends prior-goal execute_step ledger so the agent has conversational context |
| `_LOOP_CONTINUATION_GUIDE` system prompt section | Still injected via `state["continue_loop_mode"]` in middleware |

### Drop

| Item | Reason |
|---|---|
| `continue_loop_plan_bootstrap_allowed()` heuristic gating | LLM-driven decision replaces structural heuristic |
| iter=1 `plan_assess` LLM call on bootstrap path | `terminal_after_execute=True` routes record_iteration → goal_completion directly |

---

## 8. Migration / Compatibility

Clean cut — no backward-compat shims.

- `PlanResult.terminal_after_execute` defaults to `False`; existing PlanResult records deserialize unchanged.
- The new conditional edge `"goal_completion"` is added to `record_iteration` — existing route function returns the same value space as today by default; only the bootstrap path returns the new `"goal_completion"` value.
- Live daemons mid-deploy: until the new code rolls out, continuations still use the existing bootstrap heuristic. After rollout, all new continuations use LLM-driven discrimination.
- No persisted schema changes beyond the additive `PlanResult` field.

---

## 9. Examples

### 9.1 Continuation (chat-like) → bootstrap path

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
      reasoning="...",
  )
  → resolve_decision

resolve_decision → execute (LLM with seeded loop_messages of goal_0; 1 LLM call)
record_iteration → terminal_after_execute=True → goal_completion → END

Total in-graph LLM calls: 2 (assess + execute).
Result: agent returns Chinese translation of the 12 file-types list.
```

### 9.2 Continuation (multi-step) → plan_generate path

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
  → plan_assess (iter=1) → (continue|done) → ...

Total in-graph LLM calls: 3+ (assess + generate + execute + iter1-assess + ...).
Result: agent runs translate step, then email step, marks goal done.
```

### 9.3 Fresh goal → existing flow, unchanged

```
Loop history: []
User: "set up a redis cache for the user-session table"

plan_assess(iter=0):
  # continue_loop_mode=False — existing assess flow
  → plan_generate

(unchanged from today)
```

---

## 10. Open Questions / Future Work

1. **Should `continuation_assess` reuse an existing planner LLM endpoint or get its own?** Today's `plan_assess` already calls the planner's `assess()` method. Extending it to return `ContinuationAssessment` when `continue_loop` is true (instead of the existing `StatusAssessment` schema) keeps one call site. Alternative: dedicated `assess_continuation()` method for clearer separation. Recommendation: dedicated method, mirroring the existing `assess()` shape.

2. **Capping `_prior_goal_summaries` length.** Long loops with many prior goals could bloat the prompt. A future config knob `loop.continuation_assess.max_prior_goals` can cap (default: last 5 completed goals). Out of scope for the initial implementation.

3. **Should the `bootstrap` action also include a goal completion preview from the LLM?** Currently the bootstrap step is execute-then-done; the LLM that did the discrimination could include the answer inline, eliminating the execute LLM call entirely. This is a follow-on optimization once the basic path is shipped.

---

## 11. Conclusion

`plan_assess` becomes the single decision-maker for continuation queries: one LLM call evaluates the new query against persisted prior goals (RFC-225) and routes to either a terminal bootstrap or the full plan_generate flow. The bootstrap path commits to a one-shot answer and skips the iter=1 status check by routing `record_iteration → goal_completion` directly. The plan_generate path is untouched. The change is additive (one PlanResult field, one new graph edge, one new prompt+schema), preserves all RFC-225 invariants, and replaces a heuristic mis-router with an LLM-informed one.

> Let the planner decide whether to plan.

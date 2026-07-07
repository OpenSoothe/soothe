# IG-446: Continuation-Aware plan_assess and Post-Execute Fast Exit

**RFC**: RFC-226
**Status**: Draft
**Created**: 2026-05-29
**Depends on**: RFC-220, RFC-225 (IG-445)

---

## Goal

Implement RFC-226:

1. New Pydantic schema `ContinuationAssessment` with `action: Literal["bootstrap","plan_generate"]`, `reasoning`, `goal_progress`.
2. New prompt template `LOOP_CONTINUATION_ASSESS_PROMPT` surfacing prior goals + capabilities.
3. New `LLMPlanner.assess_continuation(...)` method (parallel to existing `assess`).
4. Make `plan_assess` on iter=0 of continuations (`continue_loop_mode` AND `goal_history >= 2`) call `assess_continuation` and route to bootstrap or `plan_generate` based on `action`.
5. Add `PlanResult.terminal_after_execute: bool = False`.
6. Extend `build_continue_loop_bootstrap_plan(goal, *, terminal_after_execute=False, reasoning="", goal_progress="low")` signature.
7. Update `route_after_record_iteration` to return `"goal_completion"` when `ctx.scratch.plan_result.terminal_after_execute` is True.
8. Add `"goal_completion"` to `record_iteration` conditional edges map in builder.py.
9. Remove `continue_loop_plan_bootstrap_allowed()` and its usage — LLM owns the decision.

---

## Files to Touch

| File | Action |
|------|--------|
| `packages/soothe/src/soothe/core/loop/state/schemas.py` | ADD `PlanResult.terminal_after_execute: bool = False`; ADD `ContinuationAssessment` Pydantic model |
| `packages/soothe/src/soothe/core/loop/planning/prompts.py` | ADD `LOOP_CONTINUATION_ASSESS_PROMPT` template + `format_loop_continuation_assess_prompt` helper |
| `packages/soothe/src/soothe/core/loop/planning/planner.py` | ADD `LLMPlanner.assess_continuation(...)` returning `ContinuationAssessment`; reuse existing structured-output infrastructure |
| `packages/soothe/src/soothe/core/loop/orchestrator/nodes/plan_assess.py` | REPLACE `continue_loop_plan_bootstrap_allowed` heuristic with `_continuation_assess()` LLM call; rewire `node_plan_assess` dispatch; extend `build_continue_loop_bootstrap_plan` signature; ADD `_prior_goal_summaries` helper |
| `packages/soothe/src/soothe/core/loop/orchestrator/routing.py` | UPDATE `route_after_record_iteration` to return `"goal_completion"` when active plan is terminal |
| `packages/soothe/src/soothe/core/loop/orchestrator/builder.py` | ADD `"goal_completion"` to `record_iteration` conditional-edges map; pass `ctx` reference into router (via partial closure or LoopRuntimeContext lookup pattern already used) |
| `packages/soothe/src/soothe/core/loop/engine/agent_loop.py` | UPDATE call site `seed_loop_ledger_from_prior_goal` import (unchanged) — call `build_continue_loop_bootstrap_plan` is now via plan_assess only |
| Tests | NEW `tests/unit/core/loop/planning/test_continuation_assess.py`; NEW `tests/unit/core/loop/orchestrator/test_record_iteration_routing.py`; UPDATE `tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continue_thread.py` (rename to `test_plan_assess_continuation.py`, replace heuristic assertions with discriminator assertions) |

---

## Implementation Steps

### Step 1 — Schema additions (`state/schemas.py`)

```python
class PlanResult(BaseModel):
    # ... existing fields ...
    terminal_after_execute: bool = Field(
        default=False,
        description=(
            "When True, the plan asserts that its single step IS the goal completion "
            "(RFC-226). route_after_record_iteration routes directly to goal_completion."
        ),
    )

class ContinuationAssessment(BaseModel):
    """Iter=0 routing decision for continuation queries (RFC-226)."""
    action: Literal["bootstrap", "plan_generate"]
    reasoning: str = Field(default="", max_length=400)
    goal_progress: Literal["none", "low", "medium", "high", "complete"] = "low"
```

### Step 2 — Prompt + formatter (`planning/prompts.py`)

```python
LOOP_CONTINUATION_ASSESS_PROMPT = """\
You are deciding how to handle a follow-up query in an in-progress conversation loop.

CURRENT REQUEST:
{current_goal}

PRIOR GOALS IN THIS LOOP:
{prior_goals_block}

AVAILABLE CAPABILITIES:
{capabilities_block}

DECISION CRITERIA:
- Choose **bootstrap** when the current request can be answered using prior conversation
  context alone (e.g., "translate that", "summarize the result", "explain it in chinese")
  with no new tools or cross-domain work.
- Choose **plan_generate** when the current request needs multiple steps, new tool calls,
  or addresses a topic not covered by prior goals.

Return a ContinuationAssessment JSON object with fields: action, reasoning, goal_progress.
"""


def format_loop_continuation_assess_prompt(
    *,
    current_goal: str,
    prior_goals: list[dict],
    capabilities: list[str],
) -> str:
    rows = []
    for g in prior_goals:
        rows.append(
            f"  - {g['goal_id']} | text={g['goal_text'][:60]!r} | "
            f"completion={g['completion'][:120]!r} | steps={g['step_count']} | "
            f"last={g.get('current_plan_action','')[:60]!r}"
        )
    prior_block = "\n".join(rows) if rows else "  (none)"
    caps_block = ", ".join(capabilities[:30]) if capabilities else "(none)"
    return LOOP_CONTINUATION_ASSESS_PROMPT.format(
        current_goal=current_goal,
        prior_goals_block=prior_block,
        capabilities_block=caps_block,
    )
```

### Step 3 — Planner method (`planning/planner.py`)

Add `assess_continuation` alongside existing `assess`:

```python
async def assess_continuation(
    self,
    *,
    current_goal: str,
    prior_goals: list[dict],
    capabilities: list[str],
    observability_metadata: dict[str, str] | None = None,
) -> ContinuationAssessment:
    """RFC-226: discriminator LLM call routing continuations to bootstrap or plan_generate."""
    from soothe.core.loop.planning.prompts import format_loop_continuation_assess_prompt
    from soothe.core.loop.state.schemas import ContinuationAssessment

    prompt = format_loop_continuation_assess_prompt(
        current_goal=current_goal,
        prior_goals=prior_goals,
        capabilities=capabilities,
    )
    config = self._build_invoke_config(
        "assess_continuation",
        "planner.continuation_assess",
        observability_metadata=observability_metadata,
    )
    model = self._structured_model(ContinuationAssessment)
    try:
        result = await model.ainvoke(prompt, config=config)
    except Exception:
        logger.exception("[LLMPlanner] ContinuationAssessment LLM call failed; defaulting to plan_generate")
        return ContinuationAssessment(
            action="plan_generate",
            reasoning="LLM call failed; safe fallback to full planner.",
            goal_progress="none",
        )
    if result is None or result.action not in ("bootstrap", "plan_generate"):
        return ContinuationAssessment(
            action="plan_generate",
            reasoning="Invalid LLM output; safe fallback to full planner.",
            goal_progress="none",
        )
    return result
```

(`_structured_model` and `_build_invoke_config` follow the existing planner conventions; mirror the existing `assess()` method's structured-output pattern.)

### Step 4 — Refactor `plan_assess` (`orchestrator/nodes/plan_assess.py`)

Remove `continue_loop_plan_bootstrap_allowed`. Extend `build_continue_loop_bootstrap_plan`:

```python
def build_continue_loop_bootstrap_plan(
    goal: str,
    *,
    terminal_after_execute: bool = False,
    reasoning: str = "",
    goal_progress: Literal["none","low","medium","high","complete"] = "low",
) -> PlanResult:
    """Build a synthetic first PlanResult for loop continuation (RFC-225, RFC-226)."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(
                description=(
                    "Address the user's request using prior conversation context "
                    f"from earlier goals in this loop: {goal}"
                ),
                expected_output=(
                    "A response that addresses the current request while staying consistent "
                    "with earlier conversation context."
                ),
            )
        ],
        execution_mode="parallel",
        reasoning="Loop-continuation first-plan bootstrap (no planner LLM).",
    )
    return PlanResult(
        status="continue",
        goal_progress=goal_progress,
        assessment_reasoning=reasoning or "Loop-continuation bootstrap.",
        plan_reasoning="Single execute wave from prior loop context and current goal.",
        next_action=random.choice(_CONTINUE_THREAD_DESCRIPTIONS),
        plan_action="new",
        decision=decision,
        require_goal_completion=False,
        terminal_after_execute=terminal_after_execute,
    )


def _prior_goal_summaries(checkpoint: AgentLoopCheckpoint) -> list[dict]:
    """Compact summary of completed prior goals for continuation_assess (RFC-226)."""
    out: list[dict] = []
    for g in checkpoint.goal_history[:-1]:
        if g.status != "completed":
            continue
        out.append({
            "goal_id": g.goal_id,
            "goal_text": g.goal_text,
            "completion": g.goal_completion or "",
            "step_count": len(g.step_results),
            "current_plan_action": (
                g.current_plan.next_action if g.current_plan else ""
            ),
        })
    return out
```

Rewrite `node_plan_assess`:

```python
async def node_plan_assess(ctx: LoopRuntimeContext, _state: dict[str, Any]) -> dict[str, Any]:
    """RFC-226: continuation-aware iter=0 dispatch; existing assess for fresh-goal / iter>0."""
    agent_loop = ctx.agent_loop
    state = ctx.loop_state
    plan_manager = ctx.plan_manager
    context = agent_loop._build_plan_context(state)

    # RFC-226: continuation discriminator (iter=0 + continue_loop + prior completed goals)
    if (
        state.iteration == 0
        and ctx.continue_loop_mode
        and len(ctx.checkpoint.goal_history) >= 2
    ):
        assessment = await agent_loop.loop_planner.assess_continuation(
            current_goal=state.goal,
            prior_goals=_prior_goal_summaries(ctx.checkpoint),
            capabilities=context.available_capabilities,
        )
        if assessment.action == "bootstrap":
            logger.info(
                "[Plan] iter=0 continuation-assess: bootstrap (%s)",
                assessment.reasoning[:120] if assessment.reasoning else "",
            )
            plan_result = build_continue_loop_bootstrap_plan(
                state.goal,
                terminal_after_execute=True,
                reasoning=assessment.reasoning,
                goal_progress=assessment.goal_progress,
            )
            ctx.scratch.plan_result = plan_result
            ctx.scratch.plan_assessment = None
            await ctx.emit("plan", {
                "iteration": state.iteration,
                "status": plan_result.status,
                "progress": plan_result.goal_progress,
                # ... existing emit fields ...
            })
            return {"plan_route": "", "assess_route": "skip_generate"}
        # action == "plan_generate" — carry assessment forward
        ctx.scratch.plan_assessment = None  # don't reuse as StatusAssessment
        logger.info(
            "[Plan] iter=0 continuation-assess: plan_generate (%s)",
            assessment.reasoning[:120] if assessment.reasoning else "",
        )
        # Fall through to standard plan_generate (no skip_generate)
        return {"plan_route": "", "assess_route": "generate"}

    # Existing assess flow (fresh goal OR iter > 0)
    # ... (keep the existing code path verbatim) ...
```

### Step 5 — Routing (`orchestrator/routing.py`)

```python
def route_after_record_iteration(state: dict[str, Any]) -> str:
    """Continue outer iteration cycle, fast-exit terminal bootstrap, or finish (RFC-226)."""
    if state.get("after_record_route") == "goal_completion":
        return "goal_completion"
    if state.get("last_outcome") == "continue":
        return "iteration_gate"
    return END
```

The router reads a graph-state key `after_record_route` to know the terminal-exit decision. Set this key in `record_iteration` based on the active plan's `terminal_after_execute`:

In `nodes/record_iteration.py`:

```python
async def node_record_iteration(ctx, state):
    # ... existing body ...
    plan = ctx.scratch.plan_result
    terminal = bool(plan is not None and getattr(plan, "terminal_after_execute", False))
    return {
        # ... existing fields ...
        "after_record_route": "goal_completion" if terminal else "",
    }
```

### Step 6 — Builder (`orchestrator/builder.py`)

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

### Step 7 — Tests

`tests/unit/core/loop/planning/test_continuation_assess.py` (NEW):
- Mock LLM returns `action="bootstrap"` → assert ContinuationAssessment fields propagated.
- Mock LLM returns `action="plan_generate"` → assert fields.
- LLM raises → assert fallback to `action="plan_generate"` with reasoning.
- LLM returns invalid `action` → assert fallback.

`tests/unit/core/loop/orchestrator/test_record_iteration_routing.py` (NEW):
- `after_record_route="goal_completion"` → returns `"goal_completion"`.
- `last_outcome="continue"` → returns `"iteration_gate"`.
- Neither → returns END.

`tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continue_thread.py` (RENAME → `test_plan_assess_continuation.py`):
- Remove `continue_loop_plan_bootstrap_allowed` tests.
- ADD: `node_plan_assess` with `continue_loop_mode=True` + 2 prior goals + mocked planner.assess_continuation returning bootstrap → ctx.scratch.plan_result has `terminal_after_execute=True`.
- ADD: same with `plan_generate` → no plan_result; routes to plan_generate.
- ADD: `continue_loop_mode=True` but only 1 goal in history → falls through to existing assess flow (no continuation discriminator).
- ADD: `iter > 0` continuation → existing assess flow (continuation discriminator skipped).

`build_continue_loop_bootstrap_plan` direct tests: assert `terminal_after_execute` flag propagates; default False.

---

## Verification

```bash
cd packages/soothe
uv run --frozen pytest tests/unit/core/loop/planning/test_continuation_assess.py -v
uv run --frozen pytest tests/unit/core/loop/orchestrator/test_record_iteration_routing.py -v
uv run --frozen pytest tests/unit/core/loop/orchestrator/nodes/test_plan_assess_continuation.py -v
uv run --frozen pytest tests/unit/ -x --timeout=60
cd /Users/xiamingchen/Workspace/mirasurf/soothe && ./scripts/verify_finally.sh
```

Manual:
- Restart daemon. Run `/clear` → "count all file types" → "translate the result to chinese".
- Expect a single new in-graph LLM call labeled `assess_continuation` (look for `planner.continuation_assess` in Langfuse metadata).
- Expect log line `[Plan] iter=0 continuation-assess: bootstrap (…)`.
- Expect NO iter=1 `plan_assess` LLM call.
- Multi-step continuation (e.g., "translate and email to bob") should produce log line `[Plan] iter=0 continuation-assess: plan_generate (…)` and run the full planner.

---

## Migration / Compatibility

Clean cut — no backward-compat shims.

- `PlanResult.terminal_after_execute` defaults to False; existing persisted records deserialize unchanged.
- `continue_loop_plan_bootstrap_allowed` is removed entirely along with its caller. Existing tests that exercised it must be updated.
- The new `after_record_route` graph-state key is purely additive; absence is the existing default behavior.

---

## Risks

| Risk | Mitigation |
|---|---|
| LLM mis-routes (says bootstrap when plan_generate needed, or vice versa) | Prompt design + future few-shot examples; bootstrap path still produces an answer (just may be suboptimal); fallback paths inside planner default to `plan_generate` on errors. |
| `assess_continuation` LLM latency makes continuation slower than today's no-LLM bootstrap | Today's bootstrap saves the iter=0 LLM but pays for iter=1 status check; net call count unchanged. Quality gain justifies the swap. |
| State-key naming collision (`after_record_route`) | Prefix is unique; no other route function reads it. |
| `_prior_goal_summaries` prompt bloat for long loops | Out of scope; tracked in RFC-226 §11. Hard-cap can be added later via config. |

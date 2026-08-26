# IG-762: Fix Clarification-Resume Fatal and Failed-Step Card

**Created**: 2026-08-26
**Status**: Implemented
**Related**: RFC-622 (clarification relay), IG-760 (reentrant loop state)

## Problem

Observed on loop `01a03c3b-e8c1-78c1-9fac-245f2c656d51` (v0.10.37):

1. Step "Propose a question using ask_user" → **Failed · 5s**
2. "Awaiting your answer" prompt shown alongside the failed card
3. User answers → fatal **"Record iteration without plan/decision"**

Three root causes:

### RC1 — ask_user swallows empty questions as an error string

`_run_ask_user` returned `"Error: ask_user requires..."` for whitespace-only
question lists; the pydantic validator only rejected fully-empty lists. The
executor's metadata generator string-sniffs the `"Error:"` prefix to mark the
tool outcome errored, and the action-retry loop feeds it back to the LLM.

### RC2 — a captured clarification still scores the step failed

The LLM's retry call fires a real `interrupt()` which the executor captures.
But the earlier errored outcome stays in `stream_outcomes`, so
`all_tool_outcomes_failed` is true and `step_completed(success=False)` is
emitted — the user sees "Failed" next to "Awaiting your answer".

### RC3 — the resume synth path crashes record_iteration

On answer resume the graph jumps directly into EXECUTE with empty scratch.
The synth path (`elif planner_ask_answered_step_id is not None`, inside
`if decision is None or plan_result is None`) manually persisted the Q&A and
bumped `state.iteration`, then returned `last_outcome="continue"` — which
routes to RECORD_PROGRESS. `node_record_iteration` reads the still-empty
scratch and fatally errors with "Record iteration without plan/decision".

## Fix

### RC1 — structured tool errors

`_AskUserArgs._normalize` strips and filters questions, raising ValueError
for whitespace-only lists; `_run_ask_user` raises the same instead of
returning an error string. ToolNode converts the ValidationError into
`ToolMessage(status="error")` — a structured signal the LLM retries on,
no string sniffing needed. The `"Error:"` prefix convention in
`metadata_generator.py` stays (other tools may rely on it).

### RC2 — capture-aware step scoring

In `_execute_step_collecting_events`, when
`self._clarification_capture.pending_request` is set, the step scores as
success: the step is awaiting the user, not failed. The synth path emits the
definitive `step_completed(success=True)` on resume.

### RC3 — populate scratch, route through record_iteration

The synth path now synthesizes a minimal `AgentDecision` + `PlanResult`
(mirroring the resume-rebuild in the same node) and appends the synth
`StepExecutionRecord` to `ctx.scratch.step_results`. The manual
`_persist_planner_ask_step_outcome` call, inline iteration bump, and inline
checkpoint save are deleted — `node_record_iteration` owns plan-DAG
recording, CE persistence, iteration advance, and state persistence.

`_persist_planner_ask_step_outcome` is retained: the Branch 1 continuation
(answered planner-ask with a live decision) still calls it — with CE bound,
`LoopState.add_step_result` is a no-op, so the immediate `CE.complete_step`
is what stops the executor from re-dispatching the ask step on the resumed
wave, before record_iteration runs.

## Test coverage

- `test_ask_user_tool.py` — whitespace-only raises ValueError; validator
  strips entries; `query` alias accepted (observed on loop 85f2: the LLM's
  first call used `query=`, erroring before the retry).
- `test_execute_steps_ask_user.py` — synth-path tests assert scratch
  population (decision/plan_result/step_results), no inline persist/bump;
  regression runs `node_execute` → `node_record_iteration` and asserts
  no fatal, `iteration_completed` emitted, and the recreated CE step
  completed.
- `test_ask_user_and_interrupt_on_e2e.py` — captured clarification scores
  the step success despite all-errored outcomes; without capture the step
  still fails.
- `test_await_clarification.py` — the interactive pause saves the CE before
  the interrupt; the defer park saves it again; the resume turn skips the
  pre-pause save.

## Follow-up: answer submitted but the loop does not run (loops 85f2, c586)

After the fixes above, loop 85f2 progressed past the fatal but still died
silently: the user's answer was recorded, yet the graph ended at root_eval
with "action tree not green and no ready steps" → `root_eval_route=fatal`
→ END.

Root cause: the CE was only saved before the graph start
(`strange_loop.py`) and in `record_progress`. The execute→await_user park
path skips record_progress, so dispatch's step nodes (e.g. FCU-01) were
never persisted. The resume turn loaded a CE DAG with `"nodes": {}`
(verified in `context.db`), the synth's `complete_step` no-oped, and
`action_tree_green()` returned False on the empty tree.

Fixes:

1. **`await_user` CE save before the pause** — the interactive policy
   pauses on a LangGraph ``interrupt()`` inside ``policy.answer()`` (that
   is the real park mechanism for manual clarifications; the runner resumes
   it with ``Command(resume=...)``). The graph channels survive via the
   checkpointer, but dispatch's CE step DAG is in-memory only — save the CE
   right before the first-turn pause. Loop c586 confirmed the earlier
   ``_hard_defer``-only save (auto-defer paths) never runs for interactive
   pauses.
2. **`await_user._hard_defer`** — save the CE after parking (auto-defer
   paths), so the step DAG and the parked status survive the invocation
   boundary.
3. **`execute._ensure_ce_step_for_resume`** — recreate the CE root step
   when the parked checkpoint predates the saves above (stale DAGs), so
   record_iteration completes a real node and root_eval sees a green tree.
4. **`ask_user` `query` alias** — the LLM's first call on loop 85f2 used
   `ask_user(query=...)`, which failed schema validation and burned a hop
   before the retry succeeded.

## Verification

`./scripts/verify_finally.sh` green (lint, tests, vulture, boundaries).

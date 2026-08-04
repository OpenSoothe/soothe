# IG-684: Retry Resume From Successful Checkpoint

**Created**: 2026-08-04
**Status**: Implemented
**Related**: Loop 9e20 analysis; [IG-670](IG-670-daemon-auto-resume-interrupted-goals.md),
[RFC-225](../specs/RFC-225-loop-continuity-and-goal-record-enrichment.md),
RFC-214 `goal_interrupted` ledger

---

## Problem

After a user cancel mid-goal with several successful steps, typing `retry`
created a new CE goal titled `"retry"` with empty step inventory
(`steps total=0, done=0`) and regenerated the full plan from scratch.

Root causes:

1. `retry` was not a loop-control keyword (`continue` / `resume` / `proceed` only).
2. Interrupt resume always called `create_goal(resolve_planning_goal(...))`, so
   the literal word `retry` became a new CE goal.
3. Daemon cancel marked CE goals `cancelled` (terminal), blocking reactivation.
4. `continue`/`resume` on a running interrupted goal cancelled and replaced the
   StrangeLoop goal instead of resuming in place.

## Fix

1. Treat `retry` as an **interrupt-resume** signal (with continue/resume/proceed)
   when a checkpoint has resumable interrupted work.
2. On interrupt-resume: reuse the CE goal + step DAG, restore original goal text,
   hydrate `previous_plan`, keep StrangeLoop goal / iteration — do not
   `create_goal("retry")`.
3. On user cancel: **suspend** CE goals (resumable) instead of terminal cancel;
   allow `cancelled → pending` for goals already cancelled before this change.
4. Idle checkpoint with a still-`running` StrangeLoop goal + resume signal:
   re-enter that goal instead of `start_new_goal("retry")`.

## Files

| Area | Path |
|------|------|
| Keywords | `packages/soothe/src/soothe/sloop/utils/continue_keyword.py` |
| Structural | `packages/soothe/src/soothe/sloop/utils/structural_continuation.py` |
| CE resolve | `packages/soothe/src/soothe/sloop/goal_text.py` |
| CE lifecycle | `packages/soothe/src/soothe/context/engine.py` |
| StrangeLoop | `packages/soothe/src/soothe/sloop/engine/strange_loop.py` |
| Daemon interrupt | `packages/soothe-daemon/src/soothe_daemon/query/engine.py`
  (`_suspend_active_context_goals_for_interrupt`) |

## Acceptance

- [x] User `retry` / `resume` / `continue` after cancel reuses CE goal (no new
      goal titled `retry`)
- [x] Plan inventory reflects prior completed steps via reused CE step DAG
- [x] Original goal text restored for planning
- [x] Idle+interrupted StrangeLoop goal resumes in place
- [x] Unit tests for keyword, CE resolve/reactivate, hydrate, lifecycle
- [x] `./scripts/verify_finally.sh` green

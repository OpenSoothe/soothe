# IG-695: Rail wave idle / feedback deadlock

## Problem

Job `921c6d32` stalled after wave-1 makers completed:

1. **Pruned makers blocked integrate** — `all_implementation_completed` counted cancelled/pruned makers still tagged `implementation`, so `wave_makers_done` never fired.
2. **Premature feedback on `dag_idle`** — empty-root `dag_idle` matched `needs_feedback` before integrate/review/QA.
3. **Feedback self-dep on job root** — `spawn_feedback_cycle` set `depends_on=[job_id]`; rail roots are never scheduled → diagnose hung forever.

## Fix

- Exclude pruned and feedback-tagged goals from wave-maker completion facts.
- `dag_idle` + `wave_makers_done` → `spawn_integrate` when makers done and no integrate yet.
- `dag_idle` + `needs_feedback` only after completed QA/verify (not maker-only idle).
- Never wire feedback diagnose deps to the job root.

## Recovery (ops)

Cancel stuck feedback children, reset `feedback_round`, restart daemon so `dag_idle` can spawn integrate.

# IG-683: Reject Assess Keep After Failed Step

**Created**: 2026-08-04
**Status**: Complete
**Incident**: loop `019fca61-d252-7b63-93b9-6737ec4f9e20` (`9e20`)
**Related**: IG-671 (structural keep), IG-681 (tool-aware dispatch timeout)

## Problem

Loop `9e20` repeatedly failed steps (`LIS-04`, `TVQ-08`, `MVI-12`) with
`DispatchTimeoutError` (300s idle after tool results). After each failure:

1. `gather_evidence` correctly blocked **structural** keep (`last_step_failed`)
2. Assess LLM returned `status=continue` with remaining steps
3. `node_plan_assess` honored `plan_action=keep` → `skip_generate`
4. The same failed step was retried (DAG deps still unmet) → same stall

CE-backed `step_results` retain one execution per step node, so consecutive-failure
stuck detection (IG-454) never saw 3 distinct failures for the same step id.

Separately, `generate_plan_after_assess` short-circuits to keep whenever
`derive_plan_action(...) == "keep"`, so even routing to `continue_generate` without
forcing `status=replan` would still reuse the dead plan.

## Fix

1. **`assess_keep_block_reason`** — shared gate: last step failed, tool/subagent
   cap, or stuck-loop patterns. Aligns assess/`PlanGen` keep with structural-keep
   health rules (without requiring structural keep to be enabled).
2. **`node_plan_assess`** — when keep would apply but gate blocks: force
   `assessment.status=replan` and `assess_route=continue_generate`.
3. **`generate_plan_after_assess`** — refuse keep short-circuit when gate blocks;
   fall through to real generate.
4. **`detect_stuck_loop`** — also detect same `step_id` failing N times in a row
   (non-CE / multi-record paths).
5. **`DispatchTimeoutError`** → `error_type=timeout` for clearer planner evidence.

## Non-goals

- Raising idle timeout defaults (IG-681 already tool-aware)
- Changing CoreAgent stall root cause (provider/context); this stops thrash

## Test plan

- Unit: `assess_keep_block_reason` / same-step stuck
- Unit: assess keep rejected after failed last step → `continue_generate` + replan
- Unit: PlanGen keep short-circuit skipped when last step failed
- `./scripts/verify_finally.sh`

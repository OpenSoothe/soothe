# IG-376: Plan assess human context and LLM-only goal progress

**Status:** Completed  
**Scope:** AgentLoop plan phase UX and metrics

## Problem

- `_calculate_evidence_based_progress` blended LLM `goal_progress` with step/evidence heuristics, which often disagreed with user mental model and masked assess model output.
- Plan-context human text used a terse `iter=N/M | goal` form after iteration 0.

## Changes

1. **Remove** `_calculate_evidence_based_progress` and its application in `LLMPlanner.plan()`. `PlanResult.goal_progress` remains the value from `StatusAssessment` / `_combine_results` / completion fallback logic only.
2. **Plan human message** (`PromptBuilder._build_plan_context_human_text`): Always lead with `Goal: …` and a second line `Execute iteration: <1-based cycle>/<max_iterations>` (max shown as `?` if unknown).
3. **Polish** `plan_assess_instructions.xml` for clearer status/progress guidance aligned with the new human header.

**RFCs updated (this change):** RFC-603 (§3.2 superseded blend; abstract/problem 3; confidence path), RFC-604 (abstract `goal_progress` note), RFC-214 (plan-context human + dynamic fragments), `docs/specs/rfc-history.md`.

**Follow-up (same release window):** RFCs and index entries now point AgentLoop / planner / prompts / goal_engine / events at `packages/soothe/src/soothe/core/...` instead of legacy `cognition/` filesystem paths; event **type strings** remain `soothe.cognition.*` where still the wire contract (RFC-403, event-catalog).

## Verification

Run `./scripts/verify_finally.sh`.

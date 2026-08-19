# IG-753: Delete LLMPlanner / PlanPhase (+ prompt/config follow-up)

> Status: **Done**
> Spec: [RFC-904](../specs/RFC-904-sloop-recursive-decomposition.md)
> Depends: [IG-752](IG-752-delete-legacy-plan-spine.md)

---

## 1. Executive Summary

Removed ``LLMPlanner`` / ``PlanPhase``, then the leftover assess/generate/gap/
continuation prompt stack and unused ``plan_evaluate_*`` /
``plan_structural_keep_*`` config.

---

## 2. Done

| Item | Status |
|------|--------|
| StrangeLoop without planner; ``resolve_planner`` → None | Done |
| Delete cognition planner/wire/keep + Langfuse plan spans | Done |
| Trim GraphPromptWrapper to synthesis / step_completion | Done |
| Delete PromptBuilder + plan UserMessage builders + plan XML fragments | Done |
| Delete planner ledger projectors | Done |
| Remove plan-evaluate / structural-keep config + templates | Done |
| Remove ``LoopState.structural_keep_streak`` | Done |
| Delete ``StatusAssessment`` / ``PlanGapAnalysis`` / ``ContinuationAssessment`` | Done |
| Remove scratch ``plan_assessment`` / ``plan_gap`` | Done |

## 3. Kept

- ``trivial_plan``, Approve grounding, ``emit_plan_phase_status``
- ``PlanResult`` / ``AgentDecision`` / ``PriorProgressDigest``
- ``plan_prompt_ledger`` / ``execute_prompt_ledger`` / synthesis + execute prompts
- Historical ledger phase tags / clarification origin acceptance (resume → DISPATCH)

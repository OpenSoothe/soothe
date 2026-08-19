# IG-753: Delete LLMPlanner / PlanPhase

> Status: **Done**
> Spec: [RFC-904](../specs/RFC-904-sloop-recursive-decomposition.md)
> Depends: [IG-752](IG-752-delete-legacy-plan-spine.md)

---

## 1. Executive Summary

Removed ``LLMPlanner`` / ``PlanPhase`` and the plan-phase wire/Langfuse stack
after plan-spine stations were deleted. StrangeLoop constructs without a
planner; synthesis and step-brief models come from config / fast role.

---

## 2. Done

| Item | Status |
|------|--------|
| StrangeLoop ctor without ``loop_planner`` | Done |
| ``resolve_planner`` → ``None``; stop CoreAgent injection | Done |
| Delete cognition planner/wire/keep modules | Done |
| Delete evaluate/generate-plan Langfuse helpers | Done |
| Delete planner unit tests; fix StrangeLoop mocks | Done |

## 3. Follow-up (optional)

- Trim ``assess``/``generate``/``gap``/``continuation`` prompt kinds (still used by PromptBuilder tests)
- Drop unused ``plan_evaluate_*`` / ``plan_structural_keep_*`` config fields

## 4. Kept

- ``trivial_plan.py``, ``plans/grounding.py``, ``emit_plan_phase_status``
- ``PlanResult`` / ``AgentDecision``
- ``StrangeLoopPlanPhaseStatusEvent`` (status UX name)

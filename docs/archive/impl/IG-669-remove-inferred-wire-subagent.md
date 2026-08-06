# IG-669: Remove Inferred `wire_subagent` Routing

**Created**: 2026-07-31
**Status**: Implemented
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-599](../archive/impl/IG-599-pass2-wired-subagent-direct-route.md), [IG-601](IG-601-intake-only-subagent-dual-registry.md), [IG-656](IG-656-planner-intake-only.md)

---

## Executive Summary

Wired specialists are now reachable **only** through an explicit slash/daemon
`preferred_subagent`. Pass 2 no longer infers one, and the inert step-level
`wire_subagent` plumbing is gone. A `/skill:` submission additionally clears any
inbound routing hint so the skill body owns execution.

---

## Motivation

Loop `f861` submitted `/skill:omr-bootstrap begin to research on the seed
paper…`. The slash-skill line is stripped before classification, so Pass 2 saw
only `begin to research on the seed paper…`, returned
`wire_subagent="academic_research"`, and `init_or_resume` took the wired branch.
The OMR skill never reached CoreAgent — the loop ran a literature search instead.

Specialist selection is a content judgment the classifier cannot make reliably
from a stripped prompt, and it silently outranked the user's explicit
instruction. Per RFC-630 §9 (no keyword/inference content judgment for routing
controls), the decision moves entirely to the explicit slash surface.

Two layers carried the field:

- **Layer 1 — Pass 2 intake `wire_subagent`**: live, and the cause of the bug.
- **Layer 2 — planner/step-level `StepAction.wire_subagent`**: already inert
  after IG-656 (`resolve_step_wire_subagent()` always returned `None`,
  `strip_unrequested_step_delegates()` cleared every generated step), so
  `soothe_step_subagent` was always `None` in production.

---

## Design

### 1. `/skill:` guard (defense in depth)

`run_with_progress` normalizes both hint carriers once, right after the
slash-skill expansion block:

```python
if parsed_skill is not None and (preferred_subagent or routing_classification):
    preferred_subagent = None
    routing_classification = None
```

This single point covers `LoopState` construction,
`build_loop_routing_classification`, and `LoopRuntimeContext`, so `enter_loop`,
`delegate`, and the planner all agree. The condition is `parsed_skill`, not the
expanded skill env, so a `/skill:` line whose `SKILL.md` failed to load is also
protected.

### 2. Pass 2 inference removed (Layer 1)

- `intake_pass2_system.xml`: dropped the `wire_subagent` rule, the JSON contract
  field, and the specialist examples.
- `IntentClassification` / `IntakePass2LLMResult`: field removed; a stray key in
  model output is ignored by pydantic and cannot route.
- `build_loop_routing_classification` resolves only from `preferred_subagent`.
- `resolve_user_requested_wire_subagent` lost its `intent` parameter.

### 3. Step-level plumbing removed (Layer 2)

`resolve_step_wire_subagent`, `apply_step_wire_subagents`,
`resolve_wire_subagent_for_step`, `StepAction.wire_subagent`, and the planner's
`_apply_preferred_subagent_to_decision` / `_preferred_subagent_step_description`
are deleted. `strip_unrequested_step_delegates` stays (it still clears
LLM-emitted `execution_hint`/`subagent`) minus its ignored parameter.

Executor, `step_predecessor_context`, `step_wave_types`, and
`tool_call_enrichment` lose the threaded-through argument, including the dead
`- Suggested subagent:` envelope insert and the `[wire_subagent=%s]` log
suffixes.

### 4. `soothe_step_subagent` cleanse

Nothing can set the key once `StepAction.wire_subagent` is gone, and nano
derives `_subagent_routing_directive` independently in
`soothe_nano/middleware/tool_enforcement.py`. So
`SOOTHE_STEP_SUBAGENT_CONFIG_KEY`, its `configurable` entry, and the
step-subagent branch of `GoalStepGuardMiddleware` are removed; the
goal-synthesis branch stays.

Retained: `INTAKE_ONLY_WIRE_SUBAGENTS`, `resolve_wire_subagent`, and
`IntakeOnlyTaskGuardMiddleware` — the slash path and `task` catalog filtering
still need them.

---

## Cleanse

- `resolve_step_wire_subagent`, `apply_step_wire_subagents`,
  `resolve_wire_subagent_for_step`
- `LLMPlanner._preferred_subagent_step_description`,
  `LLMPlanner._apply_preferred_subagent_to_decision`
- `StepAction.wire_subagent`, `IntentClassification.wire_subagent`,
  `IntakePass2LLMResult.wire_subagent`
- `SOOTHE_STEP_SUBAGENT_CONFIG_KEY` and the `GoalStepGuardMiddleware` step branch
- `wire_subagent` / `workspace` / `step_subagent` parameters on
  `_compose_execute_step_envelope`, `_stream_and_collect`,
  `build_dependent_execution_hints`, `max_tool_calls_for_step`, and both
  `tool_call_enrichment` helpers
- Tests asserting the removed capability; RFC-630 and rfc-namings wording

---

## Acceptance

- [x] `/skill:` plus `preferred_subagent="academic_research"` does not take the
      wired branch (the `f861` regression)
- [x] `/deep_research` with no `/skill:` still routes to the wired specialist
- [x] Pass 2 output containing a stray `wire_subagent` key is ignored
- [x] No step can set `soothe_step_subagent`; the key is gone
- [x] `./scripts/verify_finally.sh` green

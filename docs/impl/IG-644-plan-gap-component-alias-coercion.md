# IG-644: Plan-Gap Component Alias Coercion

**IG**: 644  
**Title**: Plan-Gap Component Alias Coercion  
**Status**: Implemented  
**Created**: 2026-07-14  
**Related**: [IG-557](IG-557-mid-goal-plan-assess-accuracy.md), [IG-568](IG-568-plan-generate-wire-schema.md)

---

## Summary

Loop `e217` aborted mid-run with `turn_completed=False` after six successful steps. Root cause: `plan_gap_analysis` structured output used `"name"` instead of required `"component"` on `components[4]`; jsonschema raised `StructuredOutputError` and killed the graph.

## Fix

1. Wire normalizer `coerce_plan_gap_analysis_wire_dict` (via `coerce_goal_component_status_dict`) maps `name`/`title`/`label` → `component` before validation (same pattern as plan-generate wire coercion). Single path — no duplicate Pydantic alias validator.
2. `node_plan_gap_analysis` catches remaining `StructuredOutputError`, logs a warning, clears `scratch.plan_gap`, and continues to `plan_assess` so the loop is not aborted.

## Verification

- Unit tests for alias coercion and node soft-fail
- `./scripts/verify_finally.sh`

# IG-371: Omit working memory from Plan phase human message

## Status

Completed (`./scripts/verify_finally.sh`).

## Goal

Plan access uses `PromptBuilder._build_plan_context_human_text`: remove the `<WORKING_MEMORY>` block so the plan model relies on RFC-214 ledger messages and plan status instead of duplicating scratchpad text in the plan-context human turn.

## Changes

1. `PromptBuilder._build_plan_context_human_text` — drop WM section; update docstrings on `build_plan_messages`.
2. `CoreAgentLoop._build_plan_context` — stop computing `working_memory_excerpt` for Plan (field stays on `PlanContext` for callers/tests).
3. `PlanContext.working_memory_excerpt` — docstring notes it is not used in Plan human composition (IG-371).
4. Unit test — assert plan-context human omits `<WORKING_MEMORY>` when excerpt is provided.

## Verification

`./scripts/verify_finally.sh`

# IG-747: generate_plan station span on the goal-loop Langfuse trace

**RFCs**: RFC-220 (Loop Graph), RFC-604 (assess / generate)
**Related**: IG-663 (stem run names), IG-672 (evaluate parent span), IG-746 (intake span)

## Problem

`generate-plan` LLM calls used `_planner_langfuse_run_config(phase="generate-plan")`
but were absent from the goal-loop Langfuse trace.

`_pinned_trace_id` was set only inside `node_plan_evaluate` and restored when
evaluate exited. `node_plan_generate` never rebound the pin, so
`merge_langfuse_runnable_config` fell through to the process-wide cached
handler and opened a separate root trace. Fresh `simple` turns that skip
evaluate never set the pin at all.

IG-663 named the `generate-plan` suffix; IG-672 only wired the pin for evaluate.

## Approach

Same station pattern as evaluate:

| Piece | Behavior |
|---|---|
| `_station_span.station_langfuse_span` | Shared parent-span helper (evaluate + generate_plan) |
| `_generate_plan_span.generate_plan_langfuse_span_async` | Opens `generate-plan` on the goal-loop `trace_id` |
| `bind_planner_langfuse_trace` / `restore` | Pin for the duration of `node_plan_generate` (full + lightweight) |
| `generate_plan_langfuse_run_display_name` | Host display name `*:generate-plan` |
| Planner phase map | Exact `generate-plan` → display helper; retries keep `{trace}:{phase}` |

`evaluate` now delegates to the shared station helper (behavior unchanged).

## Call site

`node_plan_generate`: bind → open span → `generate_lightweight` /
`generate_from_assessment` → span output (status / steps) → restore pin.

## Cleanse (follow-up)

- Evaluate/generate_plan share `_station_span`; planner resolve helper is
  single-sourced via `stages/plan/_helpers.resolve_loop_planner`.
- Public package no longer re-exports sync-only span helpers (async + module
  paths remain for stations and tests).

## Validation

- `packages/soothe/tests/unit/core/loop/orchestrator/stages/test_generate_plan_langfuse.py`
- `packages/soothe/tests/unit/core/loop/orchestrator/stages/test_plan_evaluate_langfuse_ig672.py`
- `./scripts/verify_finally.sh`

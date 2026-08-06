# IG-666: Loop 7ea9 plan-generate FC thrash + Pass2 mis-scope

**Created**: 2026-07-31
**Status**: Complete
**Incident**: loop `019fb5fd-9df1-74e2-a606-00f83f847ea9` (`7ea9`)
**Related**: IG-665 (gap JSON methods + turn_id), IG-554 (two-pass intake)

## Problem

TUI looked frozen for ~112s after submit. Worker was healthy; silence was pre-execute LLM:

1. **Pass2** ~53s, then `scope=simple` for a multi-package parallel test/fix goal.
2. **Plan-generate** ~55s: structured invoke tried `function_calling` first (retriable error), then succeeded on a later method — empty method cache on fresh worker.

## Fix

| Area | Change |
|------|--------|
| Planner assess / continuation / generate / gap | Shared `_PLANNER_JSON_METHODS = (json_schema, json_mode)` — no FC walk |
| Pass2 prompt | Parallel multi-package suites → `complex`; example for soothe+daemon+cli+clients |
| Pass2 wire | Clip runaway `reasoning` before IntentClassification / TUI |

## Non-goals

- Changing default `_STRUCTURED_METHODS` in soothe-nano (submodule).
- Cap Pass2 thinking-token latency (provider-side).

# IG-507: Loop 3328 Log Analysis Fixes

**RFC**: N/A (Bug fixes from log analysis)
**Created**: 2026-06-26
**Status**: In Progress

## Problem Summary

Analysis of loop 3328 revealed:
1. Explore synthesis validation error: `'thoroughness' is a required property`
2. TUI shows 4 steps but logs recorded 6 steps (cumulative count mismatch)

## Changes

### 1. Remove Required Thoroughness from ExploreResult

The LLM synthesis sometimes omits `thoroughness` field, causing validation error.

**Files**:
- `packages/soothe/src/soothe/subagents/explore/schemas.py`
  - Make `thoroughness` optional with default "medium"
- `packages/soothe/src/soothe/subagents/explore/partial.py`
  - Update to use default thoroughness
- `packages/soothe/src/soothe/subagents/explore/prompts.py`
  - Remove thoroughness from SYNTHESIZE prompt requirements
- `packages/soothe/src/soothe/subagents/explore/middleware.py`
  - Use default thoroughness in fallback cases

### 2. TUI Cumulative Step Count

The `STRANGE_LOOP_PLAN_DECISION` event only contains NEW steps for current iteration.
TUI adapter needs to track cumulative step count across iterations.

**Files**:
- `packages/soothe/src/soothe/foundation/events/catalog.py`
  - Add `total_steps` and `done_steps` fields to `StrangeLoopPlanDecisionEvent`
- `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/resolve_decision.py`
  - Emit cumulative step counts in plan_decision event
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
  - Track and display cumulative step count (optional, cosmetic)

## Verification

1. Run explore subagent tests
2. Run TUI tests for step card handling
3. Verify `./scripts/verify_finally.sh` passes
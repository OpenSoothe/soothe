# IG-491: RFC-624 Phase 4 Deep Refinement

**Status**: Completed
**Created**: 2026-06-15
**RFC**: RFC-624 Phase 4 Stage 2 Post-Cleanup
**Design Draft**: `docs/archive/drafts/2026-06-15-ce-phase4-deep-refinement-design.md`

## Goal

Replace remaining `checkpoint.goal_history` reads in graph nodes with CE queries. Clean documentation references to deleted functions. Ensure conceptual clarity: checkpoint is metadata index, CE DAG is execution data.

## Scope

### In Scope

- `plan_assess.py:176`: Replace checkpoint read with CE query helper
- `bounded_evidence_gather.py:47-49`: Remove checkpoint fallback
- `plan_assess.py:113`: Update docstring to remove deleted function reference

### Out of Scope

- Pre-CE reads in `strange_loop.py` (checkpoint lifecycle before CE instantiation)
- GER mutations (`plan_revision_count`, etc.) — metadata, acceptable
- Cache fallbacks in `LoopState` — test convenience

## Implementation Steps

### Step 1: Add CE Query Helper to plan_assess.py

Add `_has_prior_completed_goal()` helper function that queries CE DAG.

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_assess.py`

**Verification:**
- Helper returns correct boolean from CE DAG
- Unit test for helper passes

### Step 2: Replace checkpoint read in continuation discriminator

Replace `len(ctx.checkpoint.goal_history) >= 2` with `_has_prior_completed_goal(ctx)`.

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_assess.py`

**Verification:**
- Continuation discriminator uses CE query
- Existing continuation tests pass

### Step 3: Remove checkpoint fallback in bounded_evidence_gather.py

Remove the `else` branch that reads `checkpoint.goal_history`.

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/bounded_evidence_gather.py`

**Verification:**
- `_is_fresh_loop()` has no checkpoint read
- Fresh-loop tests pass with CE sqlite backend

### Step 4: Update docstring in plan_assess.py

Remove reference to deleted `seed_loop_ledger_from_prior_goal` function.

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_assess.py`

**Verification:**
- No references to deleted function in docstrings/comments

### Step 5: Run verification

Run `./scripts/verify_finally.sh` to ensure all tests pass.

## Files Summary

| File | Change |
|------|--------|
| `plan_assess.py` | Add helper, replace read, update docstring |
| `bounded_evidence_gather.py` | Remove fallback |

## Acceptance Criteria

- `plan_assess.py` continuation discriminator uses CE query
- `bounded_evidence_gather.py` has no checkpoint fallback
- No docstring references to `seed_loop_ledger_from_prior_goal`
- All existing tests pass
- `./scripts/verify_finally.sh` succeeds
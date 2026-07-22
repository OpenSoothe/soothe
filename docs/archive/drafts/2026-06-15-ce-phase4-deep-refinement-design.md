# RFC-624 Phase 4 Deep Refinement Design

**Created**: 2026-06-15
**RFC**: RFC-624 Phase 4 Stage 2 Post-Cleanup
**Purpose**: Replace remaining checkpoint reads with CE queries; clean documentation

---

## Problem Statement

RFC-624 Phase 4 Stage 2 cleanup completed the CE-as-LoopState-backend migration, but residual `checkpoint.goal_history` reads remain in graph nodes that execute after CE is loaded. Additionally, some docstrings reference deleted functions.

---

## Timing Constraint Analysis

`checkpoint.goal_history` reads fall into two timing zones:

| Zone | Location | Timing | Replaceable? |
|------|----------|--------|--------------|
| **Pre-CE** | `strange_loop.py:253-356` | Before CE instantiation | No — CE doesn't exist yet |
| **Post-CE** | Graph nodes (`plan_assess.py`, `bounded_evidence_gather.py`) | After CE load | Yes — CE is available |

Pre-CE reads are checkpoint lifecycle operations:
- Recovery iteration pickup (`lines 257-265`)
- Orphaned running goal detection (`lines 266-278`)
- Goal ID generation (`line 674` in `sloop_manager.py`)

These must remain checkpoint-based because CE is instantiated at line 469.

---

## Post-CE Checkpoint Reads to Replace

### 1. `plan_assess.py:176` — Continuation Discriminator

**Current:**
```python
if (
    state.iteration == 0
    and ctx.continue_loop_mode
    and not state.step_results
    and len(ctx.checkpoint.goal_history) >= 2  # ← checkpoint read
    and (...)
):
```

**Issue:** `checkpoint.goal_history` is a metadata index after Stage 2 cleanup. The actual goal count with completion status is in CE DAG.

**Replacement:**
```python
if (
    state.iteration == 0
    and ctx.continue_loop_mode
    and not state.step_results
    and _has_prior_completed_goal(ctx)  # ← CE query helper
    and (...)
):
```

Helper function:
```python
def _has_prior_completed_goal(ctx: LoopRuntimeContext) -> bool:
    """Check CE DAG for at least one completed prior goal.

    RFC-624 Phase 4: CE is authoritative for goal state; checkpoint GER is metadata-only.
    """
    if ctx.ce is None:
        return False
    return any(g.status == "completed" for g in ctx.ce.get_all_goals())
```

**Why:** `ctx.ce` is guaranteed to be set when graph nodes execute (CE created at `strange_loop.py:469`, loaded at line 484). No fallback needed.

---

### 2. `bounded_evidence_gather.py:47-49` — Fresh-Loop Check Fallback

**Current:**
```python
if ctx.ce is not None:
    has_completed_goals = any(g.status == "completed" for g in ctx.ce.get_all_goals())
    if has_completed_goals:
        return False
else:
    # Fallback: no CE, use checkpoint.goal_history
    if len(ctx.checkpoint.goal_history) >= 2:
        return False
```

**Issue:** Fallback reads from checkpoint which is metadata-only. Since CE is always active in production (created before graph execution), fallback is unnecessary.

**Replacement:**
```python
if ctx.ce is not None:
    has_completed_goals = any(g.status == "completed" for g in ctx.ce.get_all_goals())
    if has_completed_goals:
        return False
# No fallback — CE is guaranteed active in production
# Tests without CE should use sqlite :memory: backend
```

**Verification:** Tests that need fresh-loop behavior should provide CE with sqlite backend. This aligns with Stage 2 cleanup where `_record_ledger_message` raises `ValueError` without CE.

---

## Documentation Cleanup

### 1. `plan_assess.py:113` — Deleted Function Reference

**Current docstring:**
```
... seeded into ``LoopState.loop_messages`` by ``seed_loop_ledger_from_prior_goal``) ...
```

**Issue:** `seed_loop_ledger_from_prior_goal` was deleted in Stage 2 cleanup. CE ledger spans all goals automatically via `ce.load()`.

**Replacement:**
```
... the executor prepends prior goal ledger entries from CE LedgerManager as graph_input_messages,
giving the agent the conversational context it needs to answer ...
```

---

## Files to Modify

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/sloop/nodes/plan_assess.py` | Replace `len(ctx.checkpoint.goal_history) >= 2` with CE query helper; update docstring |
| `packages/soothe/src/soothe/sloop/nodes/bounded_evidence_gather.py` | Remove checkpoint fallback |
| `docs/specs/RFC-624-context-engine.md` | Update §60 Stage 2 section with post-cleanup refinements |

---

## Acceptance Criteria

- `plan_assess.py` continuation discriminator uses CE query, not checkpoint
- `bounded_evidence_gather.py` has no checkpoint fallback
- No docstring references to `seed_loop_ledger_from_prior_goal`
- All existing tests pass
- `./scripts/verify_finally.sh` succeeds

---

## Why These Changes Matter

**Conceptual clarity:** The checkpoint is now purely metadata (goal ID index, lifecycle status). Execution data (goals, steps, ledger) lives in CE. Graph nodes should query CE for execution state, not checkpoint.

**Consistency:** Stage 2 cleanup already made CE the sole source for ledger writes. These changes align reads with writes.

**Test alignment:** Tests without CE binding need to update to provide sqlite backend, matching production behavior.
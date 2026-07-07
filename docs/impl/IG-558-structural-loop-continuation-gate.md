# IG-558: Structural Loop-Continuation Gate

**Created**: 2026-07-07
**Status**: Implemented
**Related**: [RFC-225](../specs/RFC-225-loop-continuity-and-goal-record-enrichment.md) §5.5, [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md)

---

## Problem

Loop `019f3b7b-16aa-7290-be1b-1113699c3c6d` (`[3c6d]`) could not be continued after iteration 1 was interrupted:

1. User sent `continue` / `continue this loop` while the wiki goal was still `running`.
2. Pass 1 classified these as **social** (`is_task=false`).
3. Pre-graph social fast-path returned before checkpoint recovery.
4. `_finalize_chitchat_loop()` marked the active goal `completed`, closing the loop incorrectly.

RFC-225 and RFC-630 already state that continuation is structural (checkpoint-derived), but Pass 1 social routing ran first and chitchat finalize mutated running checkpoints.

---

## Scope

### In scope

- Deterministic loop-control detection (`continue`, `resume`, `proceed`, loop-resume phrases).
- Pass 1 social fast-path bypass for loop-control signals.
- Chitchat finalize guard: no `finalize_goal` on `checkpoint.status == "running"`.
- Unit tests and RFC updates.

### Out of scope (follow-up)

- In-flight execute preemption policy (queue vs reject vs preempt).
- `/continue` slash command.
- Iteration integrity assertion before `finalize_goal` in the graph path.

---

## Implementation

### 1. `structural_continuation.py`

New module: `packages/soothe/src/soothe/foundation/sloop/utils/structural_continuation.py`

| Function | Purpose |
|----------|---------|
| `is_loop_continuation_phrase(text)` | Multi-word resume phrases |
| `is_loop_control_signal(text)` | Keyword + phrase union |
| `should_bypass_pass1_social_fast_path(checkpoint, text)` | Pre-graph bypass gate |
| `chitchat_may_finalize_checkpoint(checkpoint)` | Blocks finalize on running loops |
| `has_active_running_goal(checkpoint)` | Helper for guards |

### 2. `strange_loop.py`

After Pass 1 returns `is_task=false`, call `should_bypass_pass1_social_fast_path`. When true, coerce to `IntakePass1LLMResult(is_task=True)` and fall through to checkpoint recovery instead of yielding `intent_fast_path`.

### 3. `_runner_phases.py`

`_finalize_chitchat_loop()` loads checkpoint and returns early when `not chitchat_may_finalize_checkpoint(checkpoint)`.

---

## Tests

| File | Coverage |
|------|----------|
| `tests/unit/core/loop/utils/test_structural_continuation.py` | Phrase matcher, bypass, finalize guard |
| `tests/unit/core/loop/engine/test_strange_loop_structural_continuation.py` | `continue` bypasses social fast-path |
| `tests/unit/core/runner/test_chitchat_fast_path.py` | No finalize on running checkpoint |

---

## Verification

```bash
./scripts/verify_finally.sh
```

---

## Files changed

- `packages/soothe/src/soothe/foundation/sloop/utils/structural_continuation.py` (new)
- `packages/soothe/src/soothe/foundation/sloop/engine/strange_loop.py`
- `packages/soothe/src/soothe/runner/_runner_phases.py`
- `docs/specs/RFC-225-loop-continuity-and-goal-record-enrichment.md` §5.5
- `docs/specs/RFC-630-start-phase-llm-intake-and-branch-routing.md` §6.6, §7.1, §9

# IG-476: Fresh Loop Plan-Assess Skip Optimization

**Status**: In Progress
**Created**: 2026-06-09
**RFCs**: RFC-220 (Loop Graph), RFC-604 (Plan Phase)

## Problem

For fresh loops (iter=0, no prior messages, no step_results), `plan_assess` always returns `status="continue"` because:
1. No execution history exists to assess
2. Guard at `planner.py:1094-1098` rejects premature "done" status
3. Goal progress must start from "none"

This means every fresh loop makes an unnecessary `plan_assess` LLM call (~3-4 seconds latency) that deterministically returns `continue`, before proceeding to `plan_generate`.

## Solution

Skip the `plan_assess` node entirely for fresh loops by:
1. Detecting fresh-loop conditions in `bounded_evidence_gather` or adding a routing node
2. Shortcutting directly to `plan_generate` with a synthetic `StatusAssessment`
3. Updating graph topology to add the shortcut edge

### Fresh Loop Detection Conditions

A loop is "fresh" when ALL of:
- `state.iteration == 0`
- `not state.step_results` (no prior execution)
- `not ctx.continue_loop_mode` (not a continuation)
- `len(ctx.checkpoint.goal_history) < 2` (no prior completed goals)
- No recovery state that would require assessment

### Changes

1. **`routing.py`**: Add `route_after_evidence_gather()` with fresh-loop detection
2. **`builder.py`**: Replace edge `bounded_evidence_gather → plan_assess` with conditional edge
3. **`plan_generate.py`**: Accept synthetic assessment from routing when skipped
4. **`plan_assess.py`**: No changes needed (only called when assessment is required)

### Graph Flow Change

Before:
```
bounded_evidence_gather → plan_assess → plan_generate
```

After:
```
bounded_evidence_gather → [fresh?] → plan_generate (skip assess)
                         → [not fresh?] → plan_assess → plan_generate
```

## Files

- `packages/soothe/src/soothe/foundation/loop/orchestrator/routing.py`
- `packages/soothe/src/soothe/foundation/loop/orchestrator/builder.py`
- `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/plan_generate.py`

## Expected Impact

- **Latency**: ~3-4 seconds saved per fresh loop start
- **Tokens**: ~200-250 tokens saved per fresh loop (StatusAssessment call)
- **Behavior**: Identical outcomes (synthetic assessment matches actual LLM response for fresh loops)

## Testing

- Existing unit tests should pass (behavior unchanged for non-fresh loops)
- Add test for fresh-loop shortcut routing
- Add test for synthetic assessment handling in plan_generate

## Implementation Notes

The synthetic `StatusAssessment` should be:
```python
StatusAssessment(
    status="continue",
    goal_progress="none",
    assessment_reasoning="Fresh-loop bypass: no prior execution to assess.",
    require_goal_completion=False,
)
```

This matches what the LLM would return for a fresh loop with no execution history.
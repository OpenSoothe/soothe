# IG-265: Skip Redundant Goal Achieved Display

**Status**: Completed ✅
**Created**: 2026-04-27

---

## Objective

Remove verbose double-display and `[new]`/`[keep]` badges from CLI output for cleaner UX.

---

## Problem

For simple goals with default completion, CLI showed verbose lines:

```
Before:
● 🌟 [keep] Goal achieved successfully  ← Badge verbose
● 💭 Goal achieved successfully  ← REDUNDANT (duplicate)

After:
● 🌟 Goal achieved successfully  ← Clean, simple
```

Two issues:
1. Redundant reasoning line duplicating judgement
2. `[new]`/`[keep]` badges adding visual noise

---

## Solution

### Part 1: Skip Redundant Reasoning

Skip the 💭 reasoning line when it's exactly "Goal achieved successfully".

**File: packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py**

```python
# IG-265: Default goal completion message (skip display to avoid redundancy)
DEFAULT_GOAL_ACHIEVED_MESSAGE = "Goal achieved successfully"

# In _on_loop_agent_reason():
reasoning = event.get("reasoning", "").strip()
# IG-265: Skip redundant reasoning when it's the default goal message
if reasoning and reasoning != DEFAULT_GOAL_ACHIEVED_MESSAGE:
    lines.append(format_reasoning(...))
```

### Part 2: Remove Badge from CLI Display

Remove `[new]`/`[keep]` badge from CLI judgement display (kept in event data for logs).

**File: packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py**

```python
def format_judgement(
    judgement: str,
    action: str,
    *,
    plan_action: str | None = None,  # Ignored (kept for logs only)
    ...
) -> DisplayLine:
    """IG-265: Removed [new]/[keep] badge from CLI display."""
    # IG-265: Remove badge from CLI display
    content = f"🌟 {judgement}"
    # Badge still in event data (pipeline passes plan_action)
```

---

## Test Updates

**File: packages/soothe-cli/tests/unit/ux/cli/test_cli_stream_display_pipeline.py**

1. Updated IG-225 tests to reflect IG-257 changes (assessment removed)
2. Added IG-265 test verifying badge removal:

```python
def test_default_goal_achieved_skips_redundant_reasoning(self) -> None:
    """IG-265: Skip redundant reasoning, remove badge from CLI display."""
    ...
    # IG-265: Badge removed from CLI display (kept in event data for logs)
    assert "[keep]" not in lines[0].content
```

---

## Result

- Cleaner, simpler CLI display for all cases
- Badge removed from CLI (TUI still shows it for UI context)
- `plan_action` field remains in event data for log analysis
- Constant makes reasoning check consistent and maintainable

---

## Tests

All 4 reasoning-related tests pass ✅:
- `test_loop_agent_reason_shown_at_normal`
- `test_loop_agent_reason_done_shows_checkmark`
- `test_default_goal_achieved_skips_redundant_reasoning` (NEW)
- `test_loop_agent_reason_deduped_in_short_window`

---

## Notes

- Plan action (`new`/`keep`) remains in event data for logs
- Badge removed from CLI display (simpler UX)
- TUI still shows badge (provides UI context)
- Only affects reasoning display when `reasoning == DEFAULT_GOAL_ACHIEVED_MESSAGE`
- All other reasoning/judgement pairs display normally
- IG-225 test updates reflect prior IG-257 change

---

## Related

- IG-225: CLI assessment/plan flat display (split reasoning)
- IG-257: Tool tree display refactor (removed assessment reasoning)
- IG-264: Simplify planner schemas (different IG, number collision)
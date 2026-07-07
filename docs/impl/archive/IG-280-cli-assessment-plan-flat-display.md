# IG-225: CLI Assessment and Plan Flat Display

**Status**: ✅ Completed
**Date**: 2026-04-21
**Scope**: CLI display formatting

## Problem

Assessment and Plan reasoning messages displayed with unwanted indentation in CLI output, creating visual hierarchy that obscured their importance:

```
● 🚩 count all readme files
→ 🌟 [new] List workspace files and search for README files
  • 💭 Assessment: Need to find all readme files in the project. Will use glob to find files matching README pattern.
  • 💭 Plan: Simple counting task: explore structure, find READMEs, count them.
```

The 2-space indent (`  •`) made these messages look subordinate to the judgement line, reducing their prominence.

## Solution

Changed `format_plan_phase_reasoning()` in `src/soothe_cli/cli/stream/formatter.py` to use level=2 instead of level=3:

```python
def format_plan_phase_reasoning(...) -> DisplayLine:
    """Format a labeled plan-phase reasoning line (assessment vs plan strategy).

    IG-225: Uses level=2 (flat, no indent) for prominent visibility alongside step headers.
    """
    return DisplayLine(
        level=2,  # Changed from level=3
        content=f"💭 {label}: {text}",
        icon="•",
        indent=indent_for_level(2),  # Empty string (flat)
        ...
    )
```

## Implementation Details

### Changed Files

1. **`src/soothe_cli/cli/stream/formatter.py`**
   - Updated `format_plan_phase_reasoning()` docstring
   - Changed level from 3 to 2
   - Uses flat indent (empty string) instead of tree indent (2 spaces)

2. **`tests/unit/ux/cli/test_cli_stream_display_pipeline.py`**
   - Fixed `test_level3_flat_indent` → `test_level3_tree_indent` (IG-182 compliance)
   - Updated tests for IG-182 step completion behavior (tree children)
   - Fixed event type names (`step.started` → `step.started`, `reason` → `reasoned`)
   - Updated loop reason tests to expect 3 lines (judgement + assessment + plan)

3. **`tests/unit/ux/tui/test_tui_progress_indent.py`**
   - Updated to expect assessment/plan lines at level=2 (no indent)
   - Fixed test expectations for IG-225 behavior

### Behavior Change

**Before**:
```
→ 🌟 [new] List workspace files and search for README files
  • 💭 Assessment: Need to find all readme files in the project.
  • 💭 Plan: Simple counting task: explore structure, find READMEs, count them.
```

**After** (IG-225):
```
→ 🌟 [new] List workspace files and search for README files
• 💭 Assessment: Need to find all readme files in the project.
• 💭 Plan: Simple counting task: explore structure, find READMEs, count them.
```

## Design Rationale

### Why Level=2?

- **Visual Prominence**: Assessment and Plan reasoning are critical decision-making information, not subordinate details
- **Consistency**: Aligns with step headers (level=2) for better visual hierarchy
- **Flat Layout**: IG-182 established flat layout for levels 1-2, with tree indent only for level-3 children

### IG-182 Context

From IG-182, the display hierarchy is:
- Level 1: Goal headers (flat, no indent)
- Level 2: Step headers, tool calls, judgements, assessment/plan (flat, no indent) ← IG-225
- Level 3: Step results, tool results (tree children, 2-space indent with `|__` connector)
- Level 4: Error details (nested children)

## Testing

### Test Results

All tests passing:
- `tests/unit/ux/cli/test_cli_stream_display_pipeline.py`: 51 tests ✅
- `tests/unit/ux/test_pipeline_plan_reason_sections.py`: 2 tests ✅
- `tests/unit/ux/tui/test_tui_progress_indent.py`: 1 test ✅

### Key Test Cases

1. `test_loop_agent_reason_shown_at_normal`: Verifies 3-line output with flat assessment/plan
2. `test_tui_progress_preserves_hierarchy_indent`: Verifies level=2 flat indent for assessment/plan
3. `test_level3_tree_indent`: Confirms IG-182 behavior (level=3 has 2-space indent)

## Verification

Run verification script:
```bash
./scripts/verify_finally.sh
```

Expected output:
- Code formatting: ✅ Pass
- Linting: ✅ Zero errors
- Unit tests: ✅ All tests passing (900+ tests)

## References

- IG-182: Step Completion Display Hierarchy (level-3 tree children)
- RFC-0020: CLI Stream Display Pipeline Architecture
- RFC-604: AgentLoop Two-Phase Planning (assessment + plan reasoning)
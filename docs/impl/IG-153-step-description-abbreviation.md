# IG-153: CLI Output Polish - Step Abbreviation & Final Report Spacing

**Status**: ✅ Completed
**Created**: 2026-04-12
**Completed**: 2026-04-12
**Scope**: CLI/TUI Stream Display

## Problem

Three polish issues in CLI/TUI output:

### Issue 1: Long Step Descriptions
Completed step descriptions shown in full length, making output verbose:

```
● ✅ Run cloc on src/ and tests/ directories to count Soothe source and test code [1 tools] (11.4s)
```

### Issue 2: Missing Spacing Before Final Report
Final report appears immediately after goal completion with no separation:

```
● 🏆 run cloc to calculate code base (complete, 1 steps) (50.8s)
**Soothe Code Statistics (src/ + tests/)**
```

### Issue 3: TUI Renderer Crash
TUI renderer crashes when accessing `full_response` attribute that doesn't exist:

```
AttributeError: 'TuiRendererState' object has no attribute 'full_response'
```

## Solution

### 1. Abbreviate Step Descriptions
Abbreviate long step descriptions to show condensed version:

```
● ✅ Run cloc on src/ and ... test code [1 tools] (11.4s)
```

### 2. Add Newline Before Final Report
Add visual separation before final report:

```
● 🏆 run cloc to calculate code base (complete, 1 steps) (50.8s)

**Soothe Code Statistics (src/ + tests/)**
```

### 3. Fix TUI Renderer State Access
Use correct attribute path `suppression.full_response` instead of `full_response`.

## Implementation

### 1. Abbreviation Helper (formatter.py)

```python
def abbreviate_text(text: str, max_length: int = 50) -> str:
    """Abbreviate text to max_length, preserving start and end."""
    if len(text) <= max_length:
        return text

    # Find word boundary in first ~25 chars
    first_end = min(25, len(text))
    while first_end > 0 and text[first_end] != " ":
        first_end -= 1
    if first_end == 0:
        first_end = 25

    # Find word boundary in last ~10 chars
    last_start = max(len(text) - 10, 0)
    while last_start < len(text) and text[last_start] != " ":
        last_start += 1
    if last_start == len(text):
        last_start = len(text) - 10

    first_part = text[:first_end].rstrip()
    last_part = text[last_start:].lstrip()
    return f"{first_part} ... {last_part}"
```

### 2. Apply in format_step_done (formatter.py)

```python
def format_step_done(...) -> DisplayLine:
    duration_ms = int(duration_s * 1000)
    # Abbreviate description for cleaner display
    abbreviated = abbreviate_text(description, max_length=50)
    tool_info = f" [{tool_call_count} tools]" if tool_call_count > 0 else ""
    content = f"✅ {abbreviated}{tool_info}"
    ...
```

### 3. Add Newline Before Final Report (cli/renderer.py)

```python
def _write_stdout_final_report(self, text: str) -> None:
    stripped = text.strip()
    if not stripped:
        return

    # Add newline before final report if stderr was just written
    if self._state.stderr_just_written:
        sys.stdout.write("\n")
        self._state.stderr_just_written = False

    sys.stdout.write(stripped)
    ...
```

### 4. Fix TUI Renderer State (tui/renderer.py)

```python
def _write_panel_final_report(self, text: str) -> None:
    stripped = text.strip()
    if not stripped:
        return

    # Use suppression.full_response instead of full_response
    self._state.suppression.full_response.append(stripped)
    ...
```

## Files Modified

- `src/soothe/ux/cli/stream/formatter.py` - Added `abbreviate_text()` and updated `format_step_done()`
- `src/soothe/ux/cli/renderer.py` - Added newline before final report
- `src/soothe/ux/tui/renderer.py` - Fixed `full_response` attribute access
- `tests/unit/test_cli_stream_display_pipeline.py` - Added abbreviation tests

## Verification

All checks passed ✓:
- Format check: PASSED
- Linting: PASSED (zero errors)
- Unit tests: PASSED (1589 tests)

## Impact

- **Scope**: CLI/TUI display only
- **Backward compatible**: No API changes
- **User benefit**: Cleaner output, proper spacing, crash fix
- **Bug fix**: Resolves AttributeError in TUI renderer

## Notes

- Abbreviation preserves word boundaries (no mid-word cuts)
- Threshold: 50 chars total, preserves ~25 char start and ~10 char end
- Only applies to completed steps, not step headers
- TUI renderer now matches CLI renderer's state structure
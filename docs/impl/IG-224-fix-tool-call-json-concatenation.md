---
name: IG-224 Fix Tool Call Display Issues
status: completed
created: 2026-04-20
---

# IG-224: Fix Tool Call Display Issues

## Problem

Two critical issues preventing tool arguments from displaying correctly in TUI:

### Issue 1: JSON Concatenation Bug (Fixed)

Providers sending mixed dict + string chunks created invalid JSON by concatenating
complete JSON objects with partial fragments.

### Issue 2: Line Range Not Displayed (Fixed)

Arguments parsed correctly (streaming overlay showed complete dicts), but tool headers
didn't display `start_line`/`end_line` parameters, showing only `read_file(executor.py)`
instead of `read_file(executor.py:1-150)`.

### Symptoms

1. Tool cards mount with empty `()` or placeholders like `read_file(…)`
2. Arguments never parse successfully → `args_meaningful = False`
3. Card deferred indefinitely or shows incomplete information
4. Debug logs show JSON parse failures silently (no user feedback)
5. Streaming overlay contains invalid JSON that never resolves

### Example Scenario

Provider sends tool call in chunks:
1. Chunk 1: `{"id": "call-1", "name": "read_file", "args": {"file_path": "/tmp"}}` (complete dict)
2. Chunk 2: `{"id": "call-1", "args": '{"path": "'}` (partial JSON string)
3. Chunk 3: `{"id": "call-1", "args": '/README.md"}'}` (continuation)
4. Chunk 4: `{"id": "call-1", "chunk_position": "last"}` (final marker)

**Current behavior** (buggy):
```python
args_str = '{"file_path": "/tmp"}' + '{"path": "' + '/README.md"}'
         = '{"file_path": "/tmp"}{"path": "/README.md"}'
         # ✗ INVALID: two complete JSON objects concatenated
         # → json.loads() fails → args never display
```

**Expected behavior**:
```python
args_str = '{"path": "/README.md"}'  # Final value after dict replacement
         # ✓ VALID: single complete JSON object
         # → parses successfully → args display in card header
```

## Root Cause

**File**: `packages/soothe-cli/src/soothe_cli/shared/message_processing.py`
**Lines**: 49-67 in `accumulate_tool_call_chunks()`

### Bug Analysis

```python
# Line 49-61: First chunk registration
if tc_name and tc_id and tc_id not in pending_tool_calls:
    if isinstance(tc_args, str):
        args_str = tc_args  # String: partial or complete
    elif isinstance(tc_args, dict) and tc_args:  # ← BUG: only non-empty dict
        args_str = json.dumps(tc_args)  # Creates COMPLETE JSON
    else:
        args_str = ""  # Empty dict → empty string
    pending_tool_calls[tc_id] = {
        "name": tc_name,
        "args_str": args_str,  # ← May already be COMPLETE JSON
        "emitted": False,
        "is_main": is_main,
    }

# Line 62-64: Later chunk with complete dict
elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, dict) and tc_args:
    pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)  # ✓ REPLACES (safe)

# Line 65-67: Later chunk with string fragment
elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, str) and tc_args:
    pending_tool_calls[tc_id]["args_str"] += tc_args  # ← BUG: CONCATENATES!
    # If args_str was complete JSON from line 53, this creates:
    # '{"file_path": "/tmp"}{"path": "' → INVALID
```

### Logic Flow Problem

Two separate code paths that don't coordinate:
1. **Initialization path** (line 49-61): Sets `args_str` from first chunk
2. **Accumulation path** (line 65-67): Appends string fragments

No logic distinguishes between:
- Complete JSON (should be replaced, not appended)
- Partial JSON (should be appended)

### Missing State Tracking

Current implementation lacks:
- Flag marking whether `args_str` is complete vs partial
- Logic to detect when complete JSON should be cleared before appending
- Handling for provider sending dict first, then refining with strings

### Why Empty Dict Works (Partial Coverage)

Empty dict `{}` falls through to `else` → `args_str = ""`, so string accumulation starts from empty, works correctly. But **non-empty dict + strings** creates invalid JSON.

## Fix Strategy

Track whether `args_str` contains complete JSON vs partial, and handle replacements correctly.

### Approach: State Flag + Replacement Logic

Add `"is_complete_json"` flag to pending tool call state:

```python
pending_tool_calls[tc_id] = {
    "name": tc_name,
    "args_str": args_str,
    "is_complete_json": bool,  # NEW: True if args_str is complete JSON
    "emitted": False,
    "is_main": is_main,
}
```

**Logic**:
1. When dict args arrive (non-empty): mark `is_complete_json = True`
2. When string fragment arrives:
   - If `is_complete_json`: clear and restart accumulation (provider refined args)
   - Else: append fragment (normal partial accumulation)
3. When dict args arrive later (line 63): replace and mark complete

### Implementation Details

#### Branch 1: First chunk with non-empty dict (line 52-53)

```python
elif isinstance(tc_args, dict) and tc_args:
    args_str = json.dumps(tc_args)
    pending_tool_calls[tc_id] = {
        "name": tc_name,
        "args_str": args_str,
        "is_complete_json": True,  # NEW: mark as complete
        "emitted": False,
        "is_main": is_main,
    }
```

#### Branch 2: First chunk with empty dict (line 54-55)

```python
else:  # Empty dict or no args
    args_str = ""
    pending_tool_calls[tc_id] = {
        "name": tc_name,
        "args_str": args_str,
        "is_complete_json": False,  # NEW: mark as incomplete/empty
        "emitted": False,
        "is_main": is_main,
    }
```

#### Branch 3: First chunk with string (line 50-51)

```python
if isinstance(tc_args, str):
    args_str = tc_args
    pending_tool_calls[tc_id] = {
        "name": tc_name,
        "args_str": args_str,
        "is_complete_json": False,  # NEW: assume partial unless validated
        "emitted": False,
        "is_main": is_main,
    }
```

#### Branch 4: Later chunk with complete dict (line 63-64)

```python
elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, dict) and tc_args:
    pending_tool_calls[tc_id]["args_str"] = json.dumps(tc_args)
    pending_tool_calls[tc_id]["is_complete_json"] = True  # NEW: mark complete
```

#### Branch 5: Later chunk with string fragment (line 66-67) — **THE FIX**

```python
elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, str) and tc_args:
    # NEW: Check if args_str is already complete JSON
    if pending_tool_calls[tc_id].get("is_complete_json"):
        # Provider refined args: clear and restart accumulation
        pending_tool_calls[tc_id]["args_str"] = tc_args
        pending_tool_calls[tc_id]["is_complete_json"] = False
    else:
        # Normal partial accumulation
        pending_tool_calls[tc_id]["args_str"] += tc_args
```

### Edge Cases Handled

1. **Dict → String refinement**: Clears complete JSON, restarts accumulation
2. **String → Dict replacement**: Replaces partial with complete (existing line 63-64)
3. **Empty dict → String**: Starts from empty string (works already)
4. **String → String**: Normal accumulation (works already)
5. **Dict → Dict**: Replacement (existing line 63-64 works)

## Implementation Steps

### Step 1: Add state flag to pending tool calls

**File**: `packages/soothe-cli/src/soothe_cli/shared/message_processing.py`

1. Add `"is_complete_json"` field to pending tool call dict (lines 56-61)
2. Set to `True` when non-empty dict initializes (line 53)
3. Set to `False` when empty dict or string initializes (lines 51, 55)
4. Set to `True` when dict replaces later (line 64)

### Step 2: Fix string accumulation logic

**File**: `packages/soothe-cli/src/soothe_cli/shared/message_processing.py`

1. Before appending string fragment (line 67), check `"is_complete_json"` flag
2. If `True`: clear `args_str` and restart accumulation (provider refined args)
3. If `False`: append normally (partial accumulation)

### Step 3: Update tests

**File**: `packages/soothe-cli/tests/unit/ux/test_message_processing.py`

Add test case covering the bug scenario:

```python
def test_dict_then_string_replaces_not_concatenates(self) -> None:
    """Non-empty dict on first chunk + string fragments must not concatenate."""
    pending: dict[str, Any] = {}

    # Chunk 1: non-empty dict
    accumulate_tool_call_chunks(
        pending,
        [{"id": "call-1", "name": "read_file", "args": {"file_path": "/old"}}],
    )
    assert pending["call-1"]["args_str"] == '{"file_path": "/old"}'
    assert pending["call-1"]["is_complete_json"] is True

    # Chunk 2: string fragment (provider refined args)
    accumulate_tool_call_chunks(
        pending,
        [{"id": "call-1", "args": '{"path": "'}],
    )
    # Should REPLACE, not concatenate
    assert pending["call-1"]["args_str"] == '{"path": "'
    assert pending["call-1"]["is_complete_json"] is False

    # Chunk 3: more string
    accumulate_tool_call_chunks(
        pending,
        [{"id": "call-1", "args": '/new.txt"}'}],
    )
    assert pending["call-1"]["args_str"] == '{"path": "/new.txt"}'
    assert pending["call-1"]["is_complete_json"] is False

    # Verify parse succeeds
    parsed = try_parse_pending_tool_call_args(pending["call-1"])
    assert parsed == {"path": "/new.txt"}
```

### Step 4: Add comprehensive edge case tests

Test all streaming patterns:

```python
def test_all_streaming_patterns(self) -> None:
    """Verify all dict/string combinations parse correctly."""
    patterns = [
        # Pattern 1: Empty dict → strings (works already)
        [{"args": {}}, {"args": '{"x": "'}, {"args": '1"}'}],
        # Pattern 2: Non-empty dict → strings (BUG being fixed)
        [{"args": {"old": 1}}, {"args": '{"new": "'}, {"args": '2"}'}],
        # Pattern 3: String → dict replacement
        [{"args": '{"old":'}, {"args": {"new": 3}}],
        # Pattern 4: Strings only
        [{"args": '{"x":'}, {"args": '4"}'}],
        # Pattern 5: Dict → dict replacement
        [{"args": {"old": 5}}, {"args": {"new": 6}}],
    ]

    for pattern_chunks in patterns:
        pending = {}
        accumulate_tool_call_chunks(pending, pattern_chunks)
        parsed = try_parse_pending_tool_call_args(pending["tc-1"])
        assert parsed is not None, f"Pattern failed: {pattern_chunks}"
```

## Testing Strategy

### Unit Tests

1. **JSON concatenation test**: Verify dict → string replacement (not concatenation)
2. **Parse success test**: Confirm all streaming patterns yield valid JSON
3. **State flag test**: Verify `is_complete_json` transitions correctly
4. **Edge case matrix**: Test all combinations of dict/string/empty patterns

### Integration Tests

1. **TUI streaming simulation**: Verify tool cards display correct args in streaming scenarios
2. **Provider simulation**: Simulate Anthropic/OpenAI streaming patterns
3. **Overlay refresh test**: Verify `build_streaming_args_overlay()` handles cleared args_str

### Regression Tests

Run existing test suite to ensure:
- Empty dict → strings still works
- String accumulation still works
- Dict replacement still works
- All IG-214/216/219 tests still pass

## Verification

### Pre-commit Verification

```bash
./scripts/verify_finally.sh
```

Must pass:
- Code formatting check
- Linting (zero errors)
- Unit tests (900+ tests)
- Integration tests

### Manual Testing

1. Start daemon: `soothed start`
2. Run query that triggers tool calls: `soothe "read README.md"`
3. Observe TUI tool cards:
   - Tool name displayed correctly (not `tool`)
   - Arguments visible in header (not empty `()`)
   - Path abbreviation works
   - No placeholders when args available

### Debug Logging

Enable DEBUG logs to verify fix:

```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "your query"
```

Check logs for:
- `tool_stream_overlay` debug messages show valid JSON
- Parse succeeds on every chunk
- No "JSONDecodeError" in logs
- Args display correctly in card headers

### Test Coverage

Verify new tests cover:
- Non-empty dict → string refinement scenario
- `is_complete_json` flag transitions
- All streaming pattern combinations
- Parse success for all patterns

## Expected Impact

### Fixed Behaviors

1. Tool cards show correct arguments when providers send dict + strings
2. `args_str` always contains valid JSON (parseable)
3. No empty `()` when arguments actually available
4. Streaming overlay updates correctly across all chunk patterns
5. Card mounting happens as soon as args parse successfully

### No Regression

Existing behaviors remain correct:
- Empty dict → strings accumulation (already worked)
- String-only accumulation (already worked)
- Dict replacement (already worked)
- Display formatting (IG-214/216/219 fixes preserved)

### User Experience

Users will see:
- Tool arguments immediately when available
- Correct path/file names in headers
- No stale placeholders when args present
- Consistent display across all providers

## Implementation Checklist

- [ ] Add `"is_complete_json"` flag to pending tool call state
- [ ] Set flag correctly on dict initialization (True)
- [ ] Set flag correctly on empty/string initialization (False)
- [ ] Set flag correctly on dict replacement (True)
- [ ] Check flag before string accumulation
- [ ] Clear args_str and restart when flag is True
- [ ] Add test for dict → string refinement
- [ ] Add comprehensive edge case tests
- [ ] Run verification script
- [ ] Manual testing with real queries
- [ ] Check debug logs for parse success

## References

- [IG-214: Tool display name and ls/glob argument lines](./IG-214-tool-display-name-and-ls-glob-args.md)
- [IG-216: Tool card arg/output placeholders](./IG-216-tool-card-args-output-placeholders.md)
- [IG-219: Tool and task argument display in parentheses](./IG-219-tool-display-args-parentheses.md)
- [IG-213: TUI essential DEBUG logs for tool calls](./IG-213-tui-tool-call-debug-logging.md)
- [RFC-0020: CLI Stream Display Pipeline](../specs/RFC-0020-cli-stream-display-pipeline.md)

## Notes

- This fix addresses the **root cause** of argument display issues
- IG-214/216/219 fixed **symptoms** (display formatting) but not accumulation bug
- Complete JSON should never be concatenated with partial JSON
- Provider behavior varies: some send dict first, others send strings
- Fix ensures all streaming patterns work correctly
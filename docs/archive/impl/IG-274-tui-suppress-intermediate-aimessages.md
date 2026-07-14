# IG-274: Suppress Intermediate AIMessages in TUI During Multi-Step Execution

**Status**: ✅ Ready for Implementation

**Created**: 2026-04-27

**Problem**: TUI displays intermediate AIMessage text during plan-execute execution, unlike CLI which properly suppresses them.

**Goal**: Add suppression logic to TUI's background event consumer to match CLI behavior.

---

## Background

### Current Behavior

**CLI (headless)**: Uses `EventProcessor` + `CliRenderer` with `SuppressionState` (IG-143) to:
- Suppress intermediate AIMessage during multi-step plan execution
- Accumulate suppressed text for goal completion output
- Display accumulated text only when execution completes

**TUI**: Bypasses `EventProcessor`, directly displays AIMessage in `_background_daemon_event_consumer`:
```python
# packages/soothe-cli/src/soothe_cli/tui/app.py:4058-4077
if isinstance(message, (AIMessage, AIMessageChunk)):
    extracted = extract_ai_text_for_display(message)
    if extracted:
        # No suppression check - always displays
        asst = AssistantMessage(...)
        await asst.append_content(extracted)
```

### Root Cause

The TUI's `_background_daemon_event_consumer` (app.py:3982-4103) does not use `SuppressionState` to track multi-step execution state, causing all AIMessage chunks to be displayed immediately regardless of execution context.

---

## Solution Design

### Approach

Add suppression logic to TUI's background consumer, reusing the existing `SuppressionState` class from `soothe_cli.shared.suppression_state`.

### Changes Required

1. **Import SuppressionState** in TUI app background consumer
2. **Track suppression state** from progress events:
   - `soothe.cognition.agent_loop.started` (max_iterations > 1)
   - `soothe.cognition.plan.creating` (num_steps > 1)
   - `soothe.cognition.agent_loop.completed`
3. **Suppress AIMessage display** when `should_suppress_output()` returns True
4. **Accumulate suppressed text** for goal completion
5. **Display accumulated text** when suppression ends

### Implementation Pattern

Follow CLI's pattern from `CliRenderer.on_assistant_text()` (renderer.py:179-216):

```python
# Check suppression
if self._state.suppression.should_suppress_output():
    # Accumulate for goal completion output instead
    self._state.suppression.accumulate_text(text)
    return

# Emit only when suppression inactive
# ... display logic ...
```

---

## Implementation Steps

### Step 1: Add SuppressionState to Background Consumer

**File**: `packages/soothe-cli/src/soothe_cli/tui/app.py`

**Location**: `_background_daemon_event_consumer` method (around line 3982)

**Changes**:
```python
# Add import at top of method (line ~3987)
from soothe_cli.shared.suppression_state import SuppressionState

# Initialize suppression state (line ~3996, after tool_cards dict)
suppression = SuppressionState()

# Add accumulator for assistant messages by namespace (line ~3997)
suppressed_assistant_by_ns: dict[tuple[Any, ...], str] = {}
```

### Step 2: Track Suppression State from Events

**Location**: Event processing loop, after progress pipeline (around line 4091)

**Changes**:
```python
for event_payload in payloads:
    event_type = event_payload.get("type", "")

    # Track suppression state from events
    final_stdout = suppression.track_from_event(event_type, event_payload)

    # Existing pipeline processing...
    event_for_pipeline = dict(event_payload)
    event_for_pipeline["namespace"] = list(namespace)
    lines = progress_pipeline.process(event_for_pipeline)
    for line in lines:
        rendered = line.format().lstrip("\n").rstrip()
        if rendered:
            await self._mount_message(AppMessage(rendered))

    # Emit goal completion when suppression ends
    if suppression.should_emit_goal_completion(event_type, final_stdout):
        response = suppression.get_final_response(final_stdout)
        # Display accumulated response
        if response and ns_key not in assistant_cards_by_ns:
            asst = AssistantMessage(id=f"asst-goal-{uuid.uuid4().hex[:8]}")
            await self._mount_message(asst)
            await asst.append_content(response)
            await asst.stop_stream()
            assistant_cards_by_ns[ns_key] = asst
```

### Step 3: Suppress AIMessage Display

**Location**: AIMessage handling (around line 4058)

**Changes**:
```python
if isinstance(message, (AIMessage, AIMessageChunk)):
    extracted = extract_ai_text_for_display(message)
    if extracted:
        # Check suppression BEFORE displaying
        if suppression.should_suppress_output():
            # Accumulate for goal completion
            suppression.accumulate_text(extracted)
            # Track by namespace for final output
            suppressed_assistant_by_ns[ns_key] = "".join(suppression.full_response)
            continue

        # Normal display logic (only when suppression inactive)
        # Deduplicate immediate replayed AI chunks after reconnect/resubscribe.
        if last_ai_chunk_by_ns.get(ns_key) == extracted:
            if getattr(message, "chunk_position", None) == "last":
                await _flush_assistant_ns(ns_key)
            continue
        asst = assistant_cards_by_ns.get(ns_key)
        if asst is None:
            asst = AssistantMessage(id=f"asst-{uuid.uuid4().hex[:8]}")
            await self._mount_message(asst)
            assistant_cards_by_ns[ns_key] = asst
        await asst.append_content(extracted)
        last_ai_chunk_by_ns[ns_key] = extracted

    if getattr(message, "chunk_position", None) == "last":
        await _flush_assistant_ns(ns_key)
        last_ai_chunk_by_ns.pop(ns_key, None)
    continue
```

### Step 4: Reset Suppression State on Turn End

**Location**: Status handling (need to add status event handling in background consumer)

**Current Gap**: Background consumer skips status events (line 4017 checks for "messages", line 4080 checks for "updates"). Need to add status tracking.

**Add status handling** (before line 4017):
```python
# Handle status events for suppression state reset
if mode == "status":
    state = data.get("state", "")
    if state in {"idle", "stopped"}:
        suppression.reset_turn()
    continue
```

---

## Testing Strategy

### Manual Testing

1. Run TUI with multi-step plan:
   ```bash
   soothe "Create a comprehensive analysis of the repo structure"
   ```

2. Verify:
   - No intermediate AIMessage during plan execution
   - Tool calls/results still displayed
   - Final goal completion message appears after all steps complete

3. Compare with CLI behavior:
   ```bash
   soothe --headless "Create a comprehensive analysis of the repo structure"
   ```
   Should match TUI output pattern

### Edge Cases

1. **Single-step execution** (max_iterations=1): Should display AIMessage normally
2. **Plan with 1 step**: Should display AIMessage normally
3. **Multi-step plan cancellation**: Should reset suppression state
4. **Thread history loading**: Should not suppress historical messages

---

## Implementation Notes

### Key Files

- `packages/soothe-cli/src/soothe_cli/tui/app.py` - Main implementation
- `packages/soothe-cli/src/soothe_cli/shared/suppression_state.py` - Reuse existing class
- `packages/soothe-cli/src/soothe_cli/cli/renderer.py` - Reference implementation

### Reuse Existing Components

**DO NOT** reimplement suppression logic. Reuse:
- `SuppressionState` class (suppression_state.py)
- `track_from_event()` method
- `should_suppress_output()` method
- `accumulate_text()` method
- `should_emit_goal_completion()` method
- `get_final_response()` method

### Architectural Alignment

This follows IG-143's design:
- Multi-step/agentic suppression for stdout only (AIMessage)
- Tool calls/results still displayed at NORMAL+ verbosity
- Goal completion output when loop completes

---

## Verification

After implementation:
1. Run `./scripts/verify_finally.sh` - all tests must pass
2. Manual testing with multi-step queries in TUI
3. Compare TUI vs CLI behavior - should match

---

## References

- IG-143: Multi-step/agentic suppression implementation
- IG-273: Goal completion output optimization
- RFC-200: Agentic Goal Execution
- `packages/soothe-cli/src/soothe_cli/cli/renderer.py:179-216` - CLI suppression logic
- `packages/soothe-cli/src/soothe_cli/shared/suppression_state.py` - Shared state tracking
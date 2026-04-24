# IG-251: Fix TUI Streaming Message Duplicate Bug

**Status**: ✅ Completed
**Priority**: High
**Scope**: packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py

## Problem Statement

When streaming assistant messages are displayed in the TUI, duplicate text appears. The screenshot shows "The current TUI has a streaming" appearing twice.

## Root Cause Analysis

### Current Behavior

When streaming assistant text arrives as `AIMessageChunk`s:
1. Text chunks are appended to an `AssistantMessage` via `append_content()` (textual_adapter.py:1152)
2. Text accumulates in `pending_text_by_namespace[ns_key]` and in the widget's `_content`

When a final output event arrives (like `chitchat.responded` or `final_report.reported`):
3. `_extract_custom_output_text(data)` extracts the **complete** response text (line 1373)
4. Lines 1376-1383: Existing streaming message is flushed and **removed** from dict
5. Lines 1384-1388: A **NEW** `AssistantMessage` is created with the full `output_text` and mounted

### Why This Causes Duplication

The problem occurs when:
- Streaming chunks have already created a message with partial/complete text
- A final event arrives with the same text
- The code unconditionally creates a NEW message instead of reusing the existing one

This results in two messages displaying the same content.

## Solution

### Fix Strategy

When `output_text` from a final event matches (or is contained in) the already-streamed `pending_text`, we should:
1. **Reuse the existing streaming message** instead of creating a new one
2. Just finalize it (stop the stream and sync content to store)
3. Keep it in the UI (don't pop from `assistant_message_by_namespace` until after finalization)

### Implementation Changes

**File**: `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`

**Location**: Lines 1373-1395 (the `if output_text := _extract_custom_output_text(data)` block)

**Change**:
```python
if output_text := _extract_custom_output_text(data):
    pending_text = pending_text_by_namespace.get(ns_key, "")
    existing_msg = assistant_message_by_namespace.get(ns_key)
    
    # Check if output matches already-streamed text
    if pending_text and existing_msg:
        # Normalize both for comparison (strip whitespace)
        pending_normalized = pending_text.strip()
        output_normalized = output_text.strip()
        
        # Case 1: Exact match - reuse existing message
        if pending_normalized == output_normalized:
            await _flush_assistant_text_ns(
                adapter,
                pending_text,
                ns_key,
                assistant_message_by_namespace,
            )
            pending_text_by_namespace[ns_key] = ""
            # Message already finalized, no need to create new one
            if adapter._set_active_message:
                adapter._set_active_message(None)
            if adapter._set_spinner:
                await adapter._set_spinner(None)
            continue
        
        # Case 2: Output is subset of pending - also reuse
        if output_normalized in pending_normalized:
            await _flush_assistant_text_ns(
                adapter,
                pending_text,
                ns_key,
                assistant_message_by_namespace,
            )
            pending_text_by_namespace[ns_key] = ""
            if adapter._set_active_message:
                adapter._set_active_message(None)
            if adapter._set_spinner:
                await adapter._set_spinner(None)
            continue
        
        # Case 3: Output differs from pending - flush old and create new
        await _flush_assistant_text_ns(
            adapter,
            pending_text,
            ns_key,
            assistant_message_by_namespace,
        )
        pending_text_by_namespace[ns_key] = ""
        assistant_message_by_namespace.pop(ns_key, None)
    
    # Only create new message if no existing one or content differs
    if not existing_msg or output_text.strip() != pending_text.strip():
        output_widget = AssistantMessage(
            output_text, id=f"asst-{uuid.uuid4().hex[:8]}"
        )
        await adapter._mount_message(output_widget)
        await output_widget.write_initial_content()
        if adapter._sync_message_content and output_widget.id:
            adapter._sync_message_content(output_widget.id, output_text)
    
    if adapter._set_active_message:
        adapter._set_active_message(None)
    if adapter._set_spinner:
        await adapter._set_spinner(None)
    continue
```

### Edge Cases

1. **Exact match**: `pending_text == output_text` → reuse existing, skip new
2. **Subset**: `output_text in pending_text` → reuse existing, skip new  
3. **Superset**: `pending_text in output_text` → flush existing, create new
4. **Different**: Completely different text → flush existing, create new
5. **No pending**: No streaming message yet → create new message
6. **Empty output**: `output_text.strip() == ""` → skip entirely

## Testing Strategy

### Manual Testing
1. Run `soothe` with a query that triggers streaming
2. Verify text streams smoothly without duplicates
3. Check final output matches streamed content

### Automated Testing
- Add unit test for `_extract_custom_output_text` with various inputs
- Add integration test for streaming + final event scenarios
- Verify message deduplication logic

## Verification

Run verification script after fix:
```bash
./scripts/verify_finally.sh
```

## Estimated Impact

- **Scope**: Single file, ~30 lines
- **Risk**: Low (local change, preserves existing behavior for non-matching cases)
- **Benefit**: Eliminates duplicate text in TUI streaming
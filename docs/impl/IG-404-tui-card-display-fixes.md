# IG-404: TUI card display fixes — duplicate messages, orphan tool cards, task-scoped routing

## Goal

Fix three interrelated TUI display regressions introduced by the IG-402/IG-403 step+task card infrastructure:

1. **Duplicate assistant message**: Goal-completion synthesis text renders twice — once from the streaming path (`goal_completion_stream_by_namespace`) and again from the non-chunk full `AIMessage` that arrives after stream finalization.
2. **Subagent tool calls not routed to parent task card**: When the `task` tool is buffered in `_pending_main_tools` and flushed into the step card, `_tool_display_by_call_id[task_id]` is overwritten to point to the step widget instead of the `ToolCallMessage` (task card). Subsequent subagent tools resolve `parent_for_inner` to the step widget (wrong parent) or `None` (after step completion cleanup), causing them to mount as standalone cards.
3. **Orphan standalone tool cards**: Subagent tools that fail to resolve a parent task card fall through to the standalone `ToolCallMessage` mount path. These should be suppressed — only tool calls aggregated into step or task cards should be visible.

## Root Causes

### Duplicate assistant message (issue 1)

In the `phase == "goal_completion"` path:
- Streaming chunks create an `AssistantMessage` via `goal_completion_stream_by_namespace`.
- On stream finalization, `goal_completion_stream_by_namespace` is popped and the message is stored in `assistant_message_by_namespace` (line 1418).
- A subsequent non-chunk full `AIMessage` with the same `phase="goal_completion"` arrives.
- The guard at line 1459 (`if not existing_msg or output_normalized != pending_normalized`) always passes because `pending_normalized` is empty (cleared on previous flush), so a second widget is created.

**Fix**: After popping `goal_completion_stream_by_namespace`, check whether `assistant_message_by_namespace[ns_key]` already holds a finalized message with matching content. Skip creating a new widget when the non-chunk message content matches the already-rendered stream content.

### Task card routing overwrite (issue 2)

In `AGENT_LOOP_STEP_STARTED` handling (line 1986-1996), the flush of `_pending_main_tools` unconditionally sets `adapter._tool_display_by_call_id[tcid_str] = step_widget` for ALL buffered tools, including the `task` tool. This overwrites the early-mount entry that pointed to the actual `ToolCallMessage` (task card), breaking subagent namespace resolution.

**Fix**: During the pending flush, skip overwriting `_tool_display_by_call_id` for `task` tools that already have a `ToolCallMessage` card mounted (check if the existing entry is a `ToolCallMessage`).

### Orphan standalone tool cards (issue 3)

At line 1860-1875, subagent tools with no resolvable parent mount as standalone `ToolCallMessage` widgets. This produces noise when the routing fails or when tools arrive after step completion.

**Fix**: Suppress standalone card mounting for subagent (non-main) tools. Instead, log a debug message. Only main-agent tools without a step aggregator should produce standalone cards (and only as a fallback for the edge case where no step_started ever arrives).

## Implementation

### File: `textual_adapter.py`

#### Fix 1: Duplicate goal_completion suppression

In the `phase == "goal_completion"` non-streaming branch (after `stream_msg` is popped), add a content-dedup check:

```python
# After stream_msg finalization, check if existing_msg has same content
if existing_msg is not None:
    existing_content = getattr(existing_msg, '_content', '') or ''
    if existing_content.strip() and (
        output_normalized == existing_content.strip()
        or output_normalized in existing_content.strip()
        or existing_content.strip() in output_normalized
    ):
        # Duplicate of already-rendered stream — skip
        continue
```

#### Fix 2: Preserve task card in `_tool_display_by_call_id` during step flush

In the `AGENT_LOOP_STEP_STARTED` pending flush loop, guard the overwrite:

```python
for tcid_str, buf in adapter._pending_main_tools:
    step_widget.add_tool_call(tcid_str, buf["name"], buf["args"], raw_args=buf.get("raw_args", ""))
    adapter._tool_to_step[tcid_str] = step_widget
    # Preserve existing ToolCallMessage (task card) — only overwrite for non-task tools
    existing_display = adapter._tool_display_by_call_id.get(tcid_str)
    if not isinstance(existing_display, ToolCallMessage):
        adapter._tool_display_by_call_id[tcid_str] = step_widget
```

#### Fix 3: Suppress standalone subagent tool cards

In the tool routing fallback at line 1860, suppress standalone mount for subagent tools:

```python
else:
    if not is_main_agent:
        # Subagent tool with no parent — suppress standalone card
        logger.debug(
            "Subagent tool card suppressed (no parent): name=%s "
            "tool_call_id=%s namespace=%s",
            buffer_name,
            lookup_id,
            ns_key,
        )
    else:
        tool_msg = ToolCallMessage(buffer_name, parsed_args, tool_call_id=lookup_id)
        await adapter._mount_message(tool_msg)
        adapter._current_tool_messages[lookup_id] = tool_msg
        adapter._tool_display_by_call_id[lookup_id] = tool_msg
```

### File: `textual_adapter.py` — Step completion cleanup

Also fix the step completion cleanup (line 2040-2042) to NOT remove `_tool_display_by_call_id` entries that point to `ToolCallMessage` instances (task cards that should outlive the step):

```python
for k, parent in list(adapter._tool_display_by_call_id.items()):
    if parent is widget and not isinstance(parent, ToolCallMessage):
        adapter._tool_display_by_call_id.pop(k, None)
```

Wait — `parent is widget` means `parent is step_widget`. A step_widget is a `CognitionStepMessage`, never a `ToolCallMessage`. So the existing cleanup is fine; the issue is the overwrite in Fix 2 above.

## Files

- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` — all three fixes
- `docs/specs/RFC-501-display-verbosity.md` — note on suppression of orphan subagent cards
- Tests under `packages/soothe-cli/tests/unit/`

## Verification

- Run `/ explore count all readme` and verify:
  - Single `AssistantMessage` at the end (no duplicate)
  - Subagent tool calls (Glob, ShellExecute) appear as rows inside the task card, not standalone
  - No orphan standalone tool cards visible
- Run existing tests: `pytest packages/soothe-cli/tests/unit/tui/`

## Status

Implementing in this change set.

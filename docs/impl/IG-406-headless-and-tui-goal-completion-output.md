# IG-406: Headless goal output and TUI duplicate final assistant

**Status:** Done  
**Scope:** Agent loop goal completion wiring, Textual TUI dedupe of replayed `goal_completion` vs already-shown execute output.

## Problem

1. **`--no-tui` / headless** sometimes printed nothing for completed goals. The runner only emits `loop_assistant_messages_chunk` with `phase=goal_completion` when `skip_goal_completion_wire_duplicate` is false; that flag was incorrectly true for **`ledger_direct`**, so headless (which suppresses execute-phase prose) never received a final line.

2. **TUI** showed the final answer twice: once from normal execute streaming (step card and/or standalone `AssistantMessage`) and again from the runner’s **`goal_completion`** replay (same text as headless needs).

## Root causes

### Headless

- `skip_goal_completion_wire_duplicate` was set for every completion path that was not synthesis-with-stream, including **`ledger_direct`**. Headless relies on the replay chunk; skipping it removed the only visible answer.

### TUI (multiple mechanisms)

- **`execute_step`** text on `CognitionStepMessage` did not populate `assistant_message_by_namespace`, so the “existing assistant message” short-circuit did not apply; a second standalone card was mounted for `goal_completion`.
- After **`chunk_position == "last"`**, `assistant_message_by_namespace` was **popped** while the widget remained, so when `goal_completion` arrived, **`existing_msg` was absent** even though the first card was on screen.
- **`goal_completion` could arrive before `_flush_assistant_text_ns` ran**, while the same text still lived in **`pending_text_by_namespace`** (already streamed via `append_content`). Flushed-body tracking did not see it yet. **`/explore`** often flushed earlier (tools / subgraph ordering), masking the bug for that path only.

## Final solution

### Daemon / runner (headless)

- In `packages/soothe/src/soothe/core/agent_loop/orchestrator/nodes/goal_completion.py`, set  
  `skip_goal_completion_wire_duplicate = (action == SYNTHESIZE and not used_synthesis_fallback)`  
  so **`ledger_direct`** and **`SUMMARY`** still emit the wire replay; only successful streamed synthesis skips it.

### TUI (dedupe without breaking headless)

All in `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` (plus step widget prose in `widgets/messages.py`):

- Track **`_last_completed_main_step_execute_prose`** when a main-namespace step completes (`AGENT_LOOP_STEP_COMPLETED` → `CognitionStepMessage.last_completed_execute_prose`).
- Track **`_last_main_flushed_assistant_prose`** after `_flush_assistant_text_ns` for the main namespace (covers pop-after-last-chunk).
- Before mounting a non-chunk **`goal_completion`** `AssistantMessage`, skip if normalized **`goal_completion`** body matches any of:
  - last step execute prose,
  - last flushed main assistant body,
  - **in-flight `pending_text`** for that namespace (same normalization as flush).
- Normalize with **`RendererBase.repair_concatenated_output`** then **`format_explore_task_json_blob_for_display`** so direct runs and explore JSON blobs match the flush pipeline.

### Tests

- `packages/soothe/tests/unit/core/agent_loop/orchestrator/test_goal_completion_ledger.py` (skip flag expectations).
- `packages/soothe-cli/tests/unit/ux/tui/test_textual_adapter_goal_completion_dedupe.py` (matcher cases including pending buffer).

## References

- RFC-500 / RFC-614 loop-tagged assistant phases; headless policy IG-343 (`HeadlessCliRenderer`).
- Related TUI routing: IG-402 (step card), IG-404 stub (superseded narrative).

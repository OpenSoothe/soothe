# IG-455: Restore conversation history on `soothe loop continue`

## Problem

When a user runs `soothe loop continue <loop_id>` the TUI launches but no
prior conversation is rendered. The loop's persisted messages, tool calls,
and events are present on disk and in the checkpoint, but several
independent gaps in the resume path neutralize them before they reach the
screen.

## Root causes

### 1. `bind_execution_thread_for_loop` disagrees with RFC-223
RFC-223 normalizes the main StrangeLoop checkpoint thread id to the
``loop_id`` itself: ``soothe.core.loop.engine.strange_loop`` rewrites any
caller-supplied id back to ``loop_id`` before saving the checkpoint, and
the LangGraph checkpointer stores the conversation under that id. The
daemon's ``bind_execution_thread_for_loop``
(``packages/soothe-daemon/src/soothe_daemon/loop_isolation.py``) was
written for the pre-RFC-223 model where ``thread_id`` and ``loop_id`` were
distinct identifiers. It still mints a fresh UUID when
``current_thread_id`` is empty *and* treats a stored
``current_thread_id == loop_id`` as a "legacy alias" to delete and replace.
Every read RPC (``loop_state_get``, ``loop_messages``) therefore queries
a phantom thread id that holds no checkpoint, and the TUI legitimately
sees nothing on resume. The fix is to always return ``loop_id`` as the
checkpoint thread id, matching what the runtime actually persists.

### 2. Conversation rows are dropped from the activity fallback
`_history.py:_fetch_loop_activity_events` filters the conversation log to
`kind in ("event","tool_call","tool_result")` and
`_convert_event_to_message_data` has no branch for `kind == "conversation"`.
When checkpoint-based recovery cannot run (no checkpoint, no recoverable
state, etc.) the fallback path is the only thing left, but the actual
user/assistant text rows produced by `ThreadLogger.log_user_input` /
`log_assistant_response` are discarded before rendering.

### 3. `--prompt` short-circuits history loading
`_startup.py:251-257` and `_startup.py:493-494` only call
`_load_loop_history()` when `_schedule_initial_submission()` returns False.
`soothe loop continue <id> --prompt "next instruction"` therefore submits
the new prompt and never loads or renders the prior conversation, leaving
the user looking at an empty transcript that's about to grow a fresh turn.

## Fix scope

| Change | File |
|---|---|
| Return `loop_id` as the checkpoint thread id (RFC-223) and stop generating / discarding alien UUIDs | `packages/soothe-daemon/src/soothe_daemon/loop_isolation.py` |
| Include `conversation` rows in fallback fetch + add converter branch | `packages/soothe-cli/src/soothe_cli/tui/app/_history.py` |
| Always schedule `_load_loop_history()` on resume, even when a prompt is queued | `packages/soothe-cli/src/soothe_cli/tui/app/_startup.py` |

## Non-goals

- Pushing a historic event window on `loop_subscribe`. Worth a follow-up
  for fewer RPC round-trips and to close the subscribe→fetch race, but
  not required to restore correctness.
- Schema or storage changes. All persisted data is already correct; only
  the resume read path is broken.

## Tests

- `tests/unit/daemon/test_loop_isolation_resume.py` — adopt-existing-thread
  path (empty `current_thread_id`, non-empty `thread_ids`).
- `tests/unit/tui/test_history_conversation_rows.py` — converter branch +
  fallback fetch keeps `conversation` rows.
- `tests/unit/tui/test_startup_resume_history.py` — resume + prompt still
  schedules history load.

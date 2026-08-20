# IG-759 — Goal-completion card never finalizes in the TUI

## Symptom

The plan panel shows the loop finished, but the final synthesis report keeps a
blinking prefix dot and renders as raw markdown source. The card stays in
`AssistantMessage._streaming_active` state forever.

## Root cause

`AssistantMessage` renders plain text while streaming and switches to a single
themed-markdown render in `stop_stream()`. For a `phase=goal_completion` card,
`stop_stream()` is only reached through `_finalize_goal_completion_stream`, and
that had exactly two triggers — both unreliable:

1. **A `stream_terminal` frame on the messages stream.** The daemon coalescer
   only stamps one when the goal-completion buffer produced a block flush
   (`adaptive` past `adaptive_threshold_chars`) or when upstream marked
   `chunk_position="last"`. Nothing in `packages/soothe/` sets
   `chunk_position`, so a synthesis that stays under the threshold — and every
   turn in `mode: streaming` — ends with no terminal frame at all.
2. **`soothe.stream.end` with `scope="turn"`.** Dead code in the TUI:
   `_prepare_custom_chunk` classified `soothe.stream.end` at tier 99, set
   `PreparedTurnChunk.skip = True`, and `_apply_turn_chunk` returns on `skip`.
   Even unskipped it would rarely help — the daemon broadcasts it after the
   runner stream closes, while the client already ended the turn on
   `strange_loop.completed` plus a 300 ms drain window.

Secondary: `StreamDeliveryCoalescer.should_skip_tool_message_wire` drops any
empty messages-mode frame despite its name, so a content-free terminal marker
would be discarded before reaching the client; and the TUI's `if not blocks:
continue` gate discarded empty terminal frames before the goal-completion
branch could see them.

## Fix

**`soothe-daemon` (`query/stream_delivery.py`)**

- Track the last un-terminated passthrough goal-completion frame and re-stamp it
  as `chunk_position=last` / `stream_terminal=true` at final flush, so every
  synthesis terminates regardless of length or delivery mode.
- Exempt phase-tagged and stream-terminal frames from
  `should_skip_tool_message_wire`.

**`soothe-cli`**

- `runtime/turn/prepare.py`: treat `soothe.stream.end` as a control frame
  (`PRIORITY_HIGH`, never tier-filtered).
- `tui/textual_adapter.py`: let content-free goal-completion terminal frames
  past the empty-blocks gate; finalize in-flight synthesis cards on
  `strange_loop.completed`, after the turn pipeline drains, and on
  cancel/interrupt; do not mount a second report when a terminal frame arrives
  after the card was already closed.

## Verification

- `packages/soothe-daemon/tests/unit/query/test_stream_delivery.py`
  — terminal emitted below threshold and in `streaming` mode; terminal markers
  survive `skip_redundant_tool_message_wire`.
- `packages/soothe-cli/tests/unit/ux/tui/test_goal_completion_stream_terminal.py`
  — `soothe.stream.end` is not tier-filtered.

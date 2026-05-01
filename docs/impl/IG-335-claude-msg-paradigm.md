# IG-335: Claude Subagent Activity to Soothe Message Paradigm

## Status: In progress

## Problem

The Claude subagent (`packages/soothe/src/soothe/subagents/claude/`) wraps
`claude_agent_sdk.query()` which streams structured `AssistantMessage`,
`UserMessage`, `SystemMessage`, and `ResultMessage` events containing
`TextBlock`, `ToolUseBlock`, `ToolResultBlock`, and `ThinkingBlock` content.

Today the implementation only logs these and emits one terminal
`ClaudeResultEvent` plus a final `AIMessage` containing concatenated text.
CLI/TUI users see a single `Task(claude, ...) -> Completed` line with no
visibility into Claude's internal reasoning, tool calls, or tool results.

## Approach

Translate each Claude SDK message into a corresponding LangChain message
(`AIMessage` / `AIMessageChunk` / `ToolMessage`) and surface it through the
existing client-side message pipeline using a new "message relay" custom
event:

- Custom event shape: `{"type": "soothe.relay.message", "message": <wire dict>, "metadata": {...}}`
- Relay is emitted via `langgraph.config.get_stream_writer()` so the daemon
  forwards it under the Claude subgraph's namespace, which is already bound
  to `[Task(claude):<tcid>]` by `EventProcessor._maybe_bind_task_namespace`
  (IG-334).
- Both `EventProcessor` (no-tui) and `textual_adapter` (TUI) intercept relay
  events and route them as if they had arrived on `mode="messages"`,
  reusing all existing rendering, dedup, and task-scope logic.

## Mapping table

| Claude SDK | Soothe equivalent |
|---|---|
| `AssistantMessage` w/ `TextBlock` | `AIMessageChunk(id=mid, content=text)` per chunk |
| `AssistantMessage` w/ `ToolUseBlock(id, name, input)` | `AIMessage(tool_calls=[{name, args, id, type:"tool_call"}])` |
| `AssistantMessage` w/ `ThinkingBlock` | `AIMessage(content=[{type:"thinking", thinking, signature}])` |
| `UserMessage` w/ `ToolResultBlock(tool_use_id, content, is_error)` | `ToolMessage(tool_call_id, name, content, status)` |
| `UserMessage` w/ plain text | skipped (echo of prompt) |
| `SystemMessage` (init/task_progress/...) | custom `soothe.capability.claude.system.<subtype>` |
| `ResultMessage` | existing `ClaudeResultEvent` + final state-return `AIMessage` |
| `RateLimitEvent(rejected)` / `AssistantMessage(error=...)` | custom `soothe.capability.claude.error` |
| `StreamEvent` | not relayed (block-level granularity) |

## File changes

- New `packages/soothe/src/soothe/subagents/claude/message_mapping.py`:
  pure translators + `ClaudeToolCorrelator`.
- New `packages/soothe/src/soothe/subagents/claude/relay.py`:
  `relay_message(msg, *, metadata=None)` helper.
- Modify `packages/soothe/src/soothe/subagents/claude/implementation.py`:
  per-block translate-and-relay loop, plus error/system custom events.
- New `packages/soothe-cli/src/soothe_cli/shared/message_relay.py`:
  shared helper to convert a relay event to a `(message, metadata)` tuple
  consumable by both EventProcessor and textual_adapter.
- Modify `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`:
  `_handle_custom_event` short-circuits relay -> `_handle_messages`.
- Modify `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`:
  custom-mode branch routes relay -> messages-mode handling.
- Modify `packages/soothe-sdk/src/soothe_sdk/ux/classification.py`:
  `soothe.relay.message -> INTERNAL` so the envelope is invisible.

## Tests

- `packages/soothe/tests/unit/subagents/claude/test_message_mapping.py`
- `packages/soothe-cli/tests/unit/ux/test_event_processor_relay.py`
- `packages/soothe-cli/tests/unit/ux/test_verbosity_tier.py` extension

## Out of scope

- Re-enabling deprecated `soothe.capability.claude.text.running` events.
- HumanMessage rendering in subagent streams (`EventProcessor` has no path).
- Generalizing the relay helper outside `subagents/claude/`.

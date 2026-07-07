# IG-330: Daemon agentic stream — forward all AIMessage payloads

## Goal

Change agentic `stream_event` forwarding so WebSocket/TUI clients receive **every** `mode="messages"` chunk whose primary payload is an assistant **AI** message (`AIMessage` / `AIMessageChunk` and compatible wire dicts), including plain execute-phase prose, not only tool results and tool-bearing AI chunks.

## Non-goals

- Changing how the TUI deduplicates or suppresses text (client behavior).
- Forwarding `HumanMessage` / tool dict types as “AI” (explicitly excluded).

## Implementation

- `_runner_agentic.py`: add `_is_ai_messages_stream_chunk`, extend `_forward_messages_chunk_for_tool_ui`, yield `event_data` without `_sanitize_forwarded_ai_tool_chunk`.
- Remove unused strip/sanitize helpers tied to the old subgraph-only tool metadata policy.

## Verification

- `./scripts/verify_finally.sh`

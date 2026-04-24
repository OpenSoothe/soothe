# IG-200: TUI daemon WebSocket message envelope fix

## Problem

TUI showed no assistant output for `/claude` (and other subgraph turns) while the headless CLI worked.

## Root cause

`soothe_sdk.client.protocol._serialize_for_json` serializes `AIMessage` via `model_dump()`, producing a **flat** dict (`type`, `content`, …) without the `data` envelope. `langchain_core.messages.messages_from_dict` requires `{"type": "...", "data": {...}}`. `TuiDaemonSession._normalize_stream_data` called `messages_from_dict([flat_dict])`, which raised `KeyError: 'data'`, was swallowed, and the chunk stayed a **dict**. `textual_adapter._tui_effective_ai_blocks` only handles `AIMessage` instances, so it returned no blocks.

The CLI `EventProcessor` handles raw dicts in `_handle_dict_message`, so it was unaffected.

## Fix

Before `messages_from_dict`, wrap flat LangChain message dicts into the expected envelope when `data` is missing and the dict looks like a serialized `BaseMessage`.

## Verification

`./scripts/verify_finally.sh`

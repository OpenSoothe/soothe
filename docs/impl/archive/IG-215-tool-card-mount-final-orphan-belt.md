# IG-215: Tool card mount on final stream chunk, orphan name parity, id→name belt

**Status:** Completed  
**Scope:** `textual_adapter.py`, `tool_card_payload.py`, `messages.ToolCallMessage`

## Changes

1. **First mount timing**: Defer mounting a new `ToolCallMessage` until `chunk_position == "last"` when the chunk has an **explicit** non-terminal `chunk_position` (e.g. forward-compat markers). `None` keeps legacy “mount when args are ready” for streams that never mark `last`.

2. **Orphan policy**: `extract_tool_result_card_payload` infers real tool names from `functions.*` ids when `name` is empty or `tool`; orphan cards use `ToolCallMessage(..., tool_call_id=...)` and hook `tool.error` uses `orphan._tool_name`.

3. **Second belt**: `ToolCallMessage(..., tool_call_id=...)` applies `infer_tool_name_from_call_id` when the display name is missing or `tool`.

## Verification

- `./scripts/verify_finally.sh`

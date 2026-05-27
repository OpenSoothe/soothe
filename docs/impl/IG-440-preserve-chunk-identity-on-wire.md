# IG-440: Preserve AIMessageChunk identity on the wire

## Goal

Stop the daemon → client wire from collapsing `AIMessageChunk` to plain
`AIMessage`. Preserving the chunk identity is required by the TUI synthesis
streaming branch and any future streaming consumer.

## Symptom (loop c191 turn 2)

For the query "analyze soothe-cli code structure" (`action=synthesize`,
630 chunks, 11079 chars):

- Daemon emitted 630 `LoopAIMessageChunk` instances tagged with
  `phase="goal_completion"`.
- Client received 3013 messages-mode envelopes (502 text chunks) — i.e. the
  IG-439 visibility fix correctly delivered them to the TUI.
- TUI displayed **no** completion card.

Turn 1 (`action=ledger_direct`, single `LoopAIMessage`) rendered fine, which
narrowed the regression to the multi-chunk streaming case.

## Root cause

`packages/soothe-sdk/src/soothe_sdk/client/wire.py` had:

```python
_LC_MESSAGE_CLASS_TO_WIRE: dict[str, str] = {
    "AIMessage": "ai",
    "AIMessageChunk": "ai",       # ← collapsing
    "HumanMessage": "human",
    "HumanMessageChunk": "human", # ← collapsing
    ...
}
```

`prepare_stream_message_for_wire(chunk)` calls
`flatten_enveloped_message_dict(message_to_dict(chunk))`, which uses the map
above to rewrite the wire tag. For a `LoopAIMessageChunk` the resulting wire
dict is `{"type": "ai", "content": "...", "phase": "goal_completion", ...}` —
**chunk identity is lost**.

On the client, `messages_from_dict` resolves `"ai"` to plain `AIMessage`. The
TUI synthesis branch (`packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`):

```python
is_gc_chunk = isinstance(message, AIMessageChunk)   # ← False after collapse
...
is_synthesis_stream_chunk = is_gc_chunk
if is_synthesis_stream_chunk:
    # mount/append assistant card per stream chunk
    ...
```

…never fires. Instead the code falls through to the "single AIMessage with
phase=goal_completion" path which mounts a card for the first chunk and then
hits `existing_msg is not None → continue` for every subsequent chunk,
silently dropping them.

`messages_from_dict` natively accepts the long tag (verified):

```text
'AIMessageChunk'  -> AIMessageChunk
'HumanMessageChunk' -> HumanMessageChunk
'ai'              -> AIMessage
'human'           -> HumanMessage
```

so the collapse was unnecessary and actively harmful.

## Fix

Remove the chunk classes from `_LC_MESSAGE_CLASS_TO_WIRE` so they pass through
unchanged. Result:

- `AIMessageChunk` → wire `{"type": "AIMessageChunk", ...}` → restored as
  `AIMessageChunk`.
- Extra fields (`phase`, `chunk_position`, `thread_id`, `iteration`,
  `wave_id`) ride along because LangChain `BaseMessage` allows extras.

`AIMessage` (the Pydantic class name) still maps to `"ai"` — needed for the
small number of legacy serializers that emit class names instead of short
tags. This was the original intent of the map.

## Why the regression existed

`a38cefb3` (May 17 2026) introduced the canonical wire serializer and added
`AIMessageChunk`/`HumanMessageChunk` to the class-name map to satisfy a
LangChain assumption that was actually no longer true. Tests at the time
asserted "AIMessageChunk normalizes to AIMessage on the wire (intentional)" —
this IG flips that assertion.

## Files touched

- `packages/soothe-sdk/src/soothe_sdk/client/wire.py` — drop the chunk
  entries, expand the docstring.
- `packages/soothe-sdk/tests/unit/test_langchain_wire.py` — update
  `test_prepare_stream_data_for_wire_pair`; add
  `test_ai_message_chunk_roundtrip_preserves_chunk_identity` and
  `test_ai_message_chunk_roundtrip_preserves_extra_phase_field`.
- `packages/soothe-cli/tests/unit/ux/tui/test_daemon_session_normalize.py` —
  `test_envelope_wraps_flat_chunk_dict` now asserts `AIMessageChunk` (not
  `AIMessage`).
- `packages/soothe/tests/unit/core/loop/utils/test_messages.py` — new
  `TestLoopAIMessageChunkWireRoundtrip` covering the full
  `LoopAIMessageChunk → wire → restored` chain (the actual synthesis path).

## Verification

Run the focused suites then the full repo verification:

```bash
cd packages/soothe-sdk && uv run pytest tests/unit/test_langchain_wire.py -x -q
cd ../soothe-cli && uv run pytest tests/unit/ux/tui/test_daemon_session_normalize.py tests/unit/runtime/ -x -q
cd ../soothe && uv run pytest tests/unit/core/loop/utils/test_messages.py -x -q
./scripts/verify_finally.sh
```

Manual reproduction:

```python
from soothe.core.loop.utils.messages import LoopAIMessageChunk
from soothe_sdk.client.wire import (
    deserialize_langchain_message_from_wire,
    prepare_stream_message_for_wire,
)
chunk = LoopAIMessageChunk(content="x", phase="goal_completion", thread_id="t", iteration=1)
wire = prepare_stream_message_for_wire(chunk)
restored = deserialize_langchain_message_from_wire(wire)
assert type(restored).__name__ == "AIMessageChunk"
assert restored.phase == "goal_completion"
```

## Relationship to IG-439

IG-439 (mode=messages envelope visibility) unblocked delivery of synthesis
chunks from daemon to client. IG-440 unblocks rendering: even when chunks
reach the TUI, their identity must survive so the streaming branch fires.
Both are required for end-to-end synthesis display.

## Status

Completed.

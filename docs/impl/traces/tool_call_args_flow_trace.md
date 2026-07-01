# Tool Call Args Flow Trace: Backend → SDK → CLI Display

**Date**: 2026-06-16
**Purpose**: Trace how tool call arguments flow from backend execution through SDK wire protocol to CLI TUI display

---

## Flow Summary

```
Backend (soothe)
├── Middleware: tool_call_args_registry.py (captures at invocation)
├── Stream Engine: tool_call_args.py (collects + merges)
├── Executor: executor.py (backfills + unified IDs)
│
SDK (soothe-sdk)
├── Wire Protocol: wire.py (serialize for transport)
├── Message Processing: message_processing.py (accumulate + parse)
│
CLI (soothe-cli)
├── Resolution: tool_call_resolution.py (merge all sources)
├── TUI Adapter: textual_adapter.py (wire event handling)
├── Widgets: messages.py (step card tool rows)
├── Formatting: tool_display.py (activity line rendering)
```

---

## Detailed Trace

### 1. Backend: Invocation Capture

**File**: `packages/soothe/src/soothe/middleware/tool_call_args_registry.py`

**Mechanism**: Middleware captures args **before** tool execution via `record_tool_call_args_from_request()`:
```python
def record_tool_call_args_from_request(request: ToolCallRequest) -> None:
    store = _registry.get()
    if store is None:
        return
    tc = getattr(request, "tool_call", None)
    if not isinstance(tc, dict):
        return
    tid = str(tc.get("id") or "").strip()
    args = coerce_tool_call_args(tc.get("args"))
    if tid and args:
        store[tid] = dict(args)
```

**Key Points**:
- Args stored by **provider `tool_call_id`** (before unified ID rewriting)
- ContextVar-based registry per execution wave
- Critical for Kimi-style streams that emit ToolMessage without preceding AIMessage tool metadata

---

### 2. Backend: Stream Collection & Merging

**File**: `packages/soothe/src/soothe/foundation/sloop/engine/tool_call_args.py`

**Class**: `ToolCallArgsCollector` merges multiple sources:

```python
@dataclass
class ToolCallArgsCollector:
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    
    def ingest_invocation_registry(self, provider_tool_call_id: str) -> dict[str, Any]:
        args = get_recorded_tool_call_args(provider_tool_call_id)
        if args:
            _store(self.by_id, provider_tool_call_id, args)
        return args
    
    def record_ai_pair(self, before_rewrite, after_rewrite, *, step_id="", task_idx=None):
        # Records from both pre/post ID-rewrite AI messages
        _record_from_ai_message(before_rewrite, self.by_id, step_id=step_id, task_idx=task_idx)
        _record_from_ai_message(after_rewrite, self.by_id, step_id=step_id, task_idx=task_idx)
```

**Sources Merged**:
1. **Invocation registry** (middleware capture) — authoritative for Kimi-style
2. **AIMessage.tool_calls** — complete structured args
3. **AIMessage.tool_call_chunks** — incremental JSON fragments

**Wire Event Generation**:
```python
def wire_updates_from_ai_message(msg: BaseMessage) -> list[dict[str, Any]]:
    # Builds soothe.stream.tool_call.update payloads
    for tc in getattr(msg, "tool_calls", None) or []:
        tid = str(tc.get("id") or "").strip()
        args = coerce_tool_call_args(tc.get("args"))
        if args:
            out.append(tool_call_update_event(tool_call_id=tid, name=..., args=dict(args)))
```

---

### 3. Backend: Executor Backfill

**File**: `packages/soothe/src/soothe/foundation/sloop/engine/executor.py`

**Function**: `_backfill_tool_calls_args_from_chunks()` handles provider quirks:

```python
def _backfill_tool_calls_args_from_chunks(msg: BaseMessage) -> BaseMessage:
    """Fill empty tool_calls[].args from tool_call_chunks on the same message.
    
    Some providers emit terminal AIMessage with tool_calls having {} while
    accumulated chunk args are complete.
    """
    # Builds lookup: chunk_id → parsed_args, chunk_index → parsed_args
    # Then patches empty tool_calls[].args from chunk data
```

**Unified ID Generation**:
```python
def _unified_tool_call_id_for_stream(step_id, raw_tid, *, task_idx=None) -> str:
    if task_idx is None:
        return _make_step_tool_call_id(step_id, raw_tid, 0)  # {step}:s:{tool}:{n}
    return _make_task_inner_tool_call_id(step_id, task_idx, raw_tid, 0)  # {step}:t{n}:{tool}:{n}
```

---

### 4. SDK: Wire Serialization

**File**: `packages/soothe-sdk/src/soothe_sdk/client/wire.py`

**Key Function**: `_stringify_tool_call_chunk_args_in_body()` ensures LangChain compatibility:

```python
def _stringify_tool_call_chunk_args_in_body(body: dict[str, Any]) -> bool:
    """Coerce tool_call_chunks[].args dicts to JSON strings.
    
    AIMessageChunk validates chunk args as str (streaming JSON fragments).
    Executor backfill may attach complete dict kwargs; without this step
    messages_from_dict fails and TUI never merges task descriptions.
    """
    chunks = body.get("tool_call_chunks")
    for tc in chunks:
        args = block.get("args")
        if isinstance(args, dict):
            block["args"] = json.dumps(args, separators=(",", ":"))
```

**Envelope Wrapping**:
```python
def envelope_langchain_message_dict(message: dict[str, Any]) -> dict[str, Any]:
    # Wraps for messages_from_dict: {"type": "ai", "data": {...}}
```

---

### 5. SDK: Pending Args Accumulation

**File**: `packages/soothe-sdk/src/soothe_sdk/display/message_processing.py`

**Accumulation**: `accumulate_tool_call_chunks()` tracks streaming state:

```python
def accumulate_tool_call_chunks(pending_tool_calls, tool_call_chunks, *, is_main=True, last_active_id=""):
    # First chunk: register pending entry
    if tc_name and tc_id and tc_id not in pending_tool_calls:
        pending_tool_calls[tc_id] = {
            "name": tc_name,
            "args_str": tc_args,  # Partial JSON string
            "is_complete_json": False,
            "emitted": False,
            "is_main": is_main,
        }
    # Subsequent chunks: accumulate JSON fragments
    elif tc_id and tc_id in pending_tool_calls and isinstance(tc_args, str):
        pending_tool_calls[tc_id]["args_str"] += tc_args
```

**Args Extraction**: `extract_tool_args_dict()` handles multiple formats:

```python
def extract_tool_args_dict(tool_like: Any) -> dict[str, Any]:
    """Flatten args from tool_calls entry, content block, or args dict.
    
    Providers differ: args, arguments (JSON string), input (Anthropic),
    or top-level parameter keys without args envelope.
    """
    # Try: args → arguments → input → _raw/raw_args_str → flat params
```

---

### 6. CLI: Resolution & Merging

**File**: `packages/soothe-cli/src/soothe_cli/runtime/parse/tool_call_resolution.py`

**Merge Function**: `merge_tool_display_args()` combines all sources:

```python
def merge_tool_display_args(tool_call_id, *, block_args=None, streaming_overlay=None, 
                            pending_tool_calls_lc=None, message=None, tool_name=None):
    """Merge kwargs from block buffer, tool_call_chunks overlay, and pending JSON.
    
    Order (lowest → highest priority):
    1. from_block (content block args)
    2. from_streaming (overlay from chunks)
    3. from_tool_call_attr (pending buffer parsed)
    4. from_message_tool_calls (AIMessage.tool_calls)
    """
```

**Resolved Invocation**:
```python
@dataclass(frozen=True, slots=True)
class ResolvedToolInvocation:
    tool_call_id: str
    name: str
    args: dict[str, Any]  # Final merged args
```

---

### 7. CLI: Wire Event Handling

**File**: `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`

**Wire Update Processing**: `apply_tool_call_wire_update()`:

```python
async def apply_tool_call_wire_update(adapter, router, *, data, ns_key, pending_tool_calls_lc, ...):
    tcid = str(data.get("tool_call_id", "")).strip()
    name = str(data.get("name") or "").strip() or "tool"
    raw_args_field = data.get("args")
    display_args = extract_tool_args_dict(raw_args_field)
    
    # Merge with overlay/pending
    display_args = merge_tool_display_args(
        merge_id or tcid,
        block_args=display_args,
        streaming_overlay=overlay,
        pending_tool_calls_lc=pending_tool_calls_lc,
        tool_name=name,
    )
    
    # Add to step card
    if step_w.has_tool_call_row(tcid):
        step_w.update_tool_args(tcid, display_args)
    else:
        step_w.add_tool_call(tcid, name, display_args)
```

---

### 8. CLI: Step Card Tool Rows

**File**: `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`

**Add Tool Call**:
```python
def add_tool_call(self, tool_call_id, tool_name, args, *, raw_args="", parent_tool_call_id=None, is_task_row=False):
    row_args = dict(args or {})
    if raw_args:
        row_args["_raw"] = raw_args  # Store for later merge
    
    row = _StepToolRow(
        tool_call_id=tcid,
        tool_name=(tool_name or "tool").strip() or "tool",
        args=row_args,
        phase="pending",
        ...
    )
    
    self._rows.append(row)
    self._row_index[tcid] = row
    self.request_tools_display_refresh(immediate=True)
```

**Update Tool Args**:
```python
def update_tool_args(self, tool_call_id, args):
    row = self._row_index.get(str(tool_call_id))
    if row is None:
        return
    
    incoming = extract_tool_args_dict(args or {})
    merged = dict(row.args or {})
    if incoming:
        merged.update(incoming)  # Merge incoming into existing
    
    row.args = merged
    self.request_tools_display_refresh()
```

---

### 9. CLI: Activity Line Formatting

**File**: `packages/soothe-cli/src/soothe_cli/tui/tool_display.py`

**Format Command**:
```python
def format_step_tool_activity_command(tool_name: str, args: dict[str, Any]) -> str:
    """One-line invocation summary: DisplayName(arg) or DisplayName."""
    display = get_tool_display_name(canonical)
    preview = _args_preview(canonical, args or {})
    if preview:
        return f"{display}({preview})"
    return display
```

**Args Preview**:
```python
def _args_preview(tool_name: str, args: dict[str, Any]) -> str:
    """Comma-separated arg summary: primary value bare, extras as key=value."""
    clean = {k: v for k, v in args.items() if k not in _SKIP_ARG_KEYS}
    # Skip: _raw, _subgraph_tool, value
    
    # First arg value bare (no key=), remaining as key=value
    for key in _ordered_arg_keys(tool_name, clean):
        text = _format_arg_value(tool_name, key, clean[key])
        if not primary_emitted:
            segments.append(text)  # Bare
            primary_emitted = True
        else:
            segments.append(f"{key}={text}")
    
    return ", ".join(segments)
```

---

## Potential Loss Points

### 1. **Wire Transport: Dict → String Conversion**

**Location**: `wire.py:_stringify_tool_call_chunk_args_in_body()`

**Risk**: If this conversion is skipped or fails, LangChain's `messages_from_dict()` will reject dict args on chunks, causing the entire message to fail deserialization. Args would be **completely lost**.

**Verification**: Ensure `coerce_tool_call_chunk_args_for_wire()` is called on all outbound messages.

---

### 2. **Pending Buffer: Incomplete JSON**

**Location**: `message_processing.py:accumulate_tool_call_chunks()`

**Risk**: If streaming ends before JSON is complete, `try_parse_pending_tool_call_args()` returns `None`, and args stay as unparsed string in `args_str`. `richest_pending_args_for_lookup()` would return `{}`.

**Mitigation**: Backend sends complete args via `tool_call_update_event` wire messages (independent of chunk accumulation).

---

### 3. **Resolution: Missing Overlay Lookup**

**Location**: `tool_call_resolution.py:merge_tool_display_args()`

**Risk**: If `streaming_overlay` is not passed or `pending_tool_calls_lc` is empty, merge falls back to message `tool_calls` only. For providers that stream chunks without populating `tool_calls` until final message, this could miss args during intermediate chunks.

**Verification**: Ensure `build_streaming_args_overlay()` is called with correct `pending_tool_calls_lc`.

---

### 4. **Step Card: Update Without Add**

**Location**: `textual_adapter.py:apply_tool_call_wire_update()` (line 959-962)

**Risk**: If `step_w.has_tool_call_row(tcid)` is True but row was created with empty args, `update_tool_args()` merges correctly. However, if row was never added (missed earlier event), update does nothing.

**Mitigation**: Code handles this with `else: step_w.add_tool_call(tcid, name, display_args)`.

---

### 5. **Display: Skipped Keys**

**Location**: `tool_display.py:_args_preview()` (line 75)

**Risk**: Args with keys in `_SKIP_ARG_KEYS` (`_raw`, `_subgraph_tool`, `value`) are filtered out and **never shown**.

**Issue**: `_raw` is stored for incremental merge but excluded from display. If args only have `_raw` (no other keys), preview shows nothing.

**Verification**: Check if `extract_tool_args_dict()` successfully parses `_raw` into actual arg keys before display.

---

### 6. **Format: Path vs Value Confusion**

**Location**: `tool_display.py:_format_arg_value()`

**Risk**: If `get_tool_meta()` returns incorrect `path_arg_keys`, path args get abbreviated (`~/...`) while non-path args get truncated. Mislabeling could show wrong format.

---

## Recommendations

### A. Verify Wire Serialization

**Check**: Ensure all outbound messages pass through `coerce_tool_call_chunk_args_for_wire()`:
```python
# In executor stream output
msg_dict = coerce_tool_call_chunk_args_for_wire(msg_dict)
```

### B. Defensive Args Extraction

**Check**: In `update_tool_args()`, ensure `_raw` is parsed:
```python
def update_tool_args(self, tool_call_id, args):
    incoming = extract_tool_args_dict(args or {})
    # If incoming is empty but args has _raw, parse it
    if not incoming and isinstance(args.get("_raw"), str):
        incoming = extract_tool_args_dict({"_raw": args["_raw"]})
```

### C. Merge Logging

**Add**: Debug logging in `merge_tool_display_args()`:
```python
logger.debug(
    "merge_tool_display_args id=%s sources: block=%d stream=%d pending=%d msg=%d → merged=%d",
    tool_call_id,
    len(block_args or {}),
    len(stream_args or {}),
    len(pend_parsed or {}),
    len(message_args or {}),
    len(merged),
)
```

### D. Display Fallback

**Check**: In `_args_preview()`, if all keys are skipped, try parsing `_raw`:
```python
clean = {k: v for k, v in args.items() if k not in _SKIP_ARG_KEYS}
if not clean and "_raw" in args:
    parsed = extract_tool_args_dict({"_raw": args["_raw"]})
    clean = {k: v for k, v in parsed.items() if k not in _SKIP_ARG_KEYS}
```

---

## Test Scenarios

### 1. Chunk-Only Stream

**Setup**: Provider streams only `tool_call_chunks` (no `tool_calls` until final).

**Verify**: `pending_tool_calls_lc` accumulates args_str, `build_streaming_args_overlay()` parses it, display shows args before final message.

### 2. Dict Args on Chunks

**Setup**: Backend sends chunk with dict args (after backfill).

**Verify**: `wire.py` converts to JSON string, SDK accumulates correctly, CLI parses.

### 3. Kimi-Style No AIMessage

**Setup**: Stream emits ToolMessage without preceding AIMessage tool metadata.

**Verify**: Invocation registry captures args, unified ID mapping works, wire event carries args.

### 4. Subagent Task Descriptions

**Setup**: Task tool call with description arg.

**Verify**: Args merge from all sources, `task` row shows description preview, not empty.

---

## Conclusion

The flow is **well-designed** with multiple fallbacks:

1. **Invocation registry** captures at execution start
2. **Chunk accumulation** handles streaming
3. **Wire events** provide authoritative updates
4. **Multi-source merge** combines all paths
5. **Step card update** merges incrementally

**Primary risks**:
- Wire serialization skipped (dict args on chunks)
- Pending JSON incomplete (no fallback to wire event)
- `_raw` key filtered from display

**Overall**: Args are **not lost** in normal flow. Issues would arise from:
- Serialization bugs
- Missing wire event dispatch
- Display filtering of internal keys (`_raw`)

The architecture is robust with appropriate defensive checks at each stage.
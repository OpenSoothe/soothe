# Execute-Step Progress Reporting

**Status**: Draft  
**Date**: 2026-07-06  
**Kind**: Design (Platonic Coding — brainstorm handoff)  
**Related**: RFC-100 (CoreAgent runtime), RFC-201 (plan-execute loop), RFC-214 (loop message surface), RFC-227 (prior progress digest — wave-end, plan-assess only), RFC-401 (event processing), RFC-500 (CLI/TUI architecture), RFC-501 (display verbosity), RFC-607 (progressive display), IG-549 (stream heartbeat), IG-542 (execute-step ledger projection)  
**Supersedes behavior in**: silent long execute steps (TUI shows only tool rows + generic running animation until `step_completed`)

---

## 1. Problem

Execute-step CoreAgent runs can take several minutes — multi-tool research, browser automation, large code execution. During that time the TUI/WebSocket client sees:

- Tool call rows appearing incrementally (good for *what* ran, poor for *why* or overall direction)
- A generic running animation on the step card footer
- IG-549 transport heartbeats every 10s (empty keep-alive, no semantic content)

Users watching a long step have no periodic narrative summary of progress. The final `step_completed` summary arrives only when the step finishes.

**Goal**: While a single execute-step CoreAgent stream is in flight, emit an LLM-generated ~100-word progress summary every 60 seconds, per step, for TUI/WebSocket display.

### 1.1 Out of scope (explicit non-goals)

| Concern | Why excluded |
|---------|--------------|
| Plan-assess grounding | RFC-227 `PriorProgressDigest` already covers wave-end deterministic digest for planner phases |
| Autopilot `report_progress` proposals | RFC-204 — agent-initiated, queued after iteration; different lifecycle |
| Replacing `step_completed` final summary | Progress summaries are interim; final card summary unchanged |
| Wave-level merged summary across parallel steps | User chose per-step reporting (parallel steps each get their own summary) |
| Mid-stream `aget_state` as message source | Execute streams use checkpoint-free `execution_graph` (`durability="exit"`); in-memory accumulator is authoritative |

---

## 2. Constraints (from design discussion)

These are **requirements**.

1. **Consumer**: TUI and WebSocket clients only — no `LoopState`, proposal queue, or plan-assess changes.
2. **Per-step isolation**: Each parallel execute branch owns its own reporter and events (tagged with `step_id`).
3. **Interval**: Default 60 seconds between summaries; configurable; `0` disables.
4. **Length**: ~100 words per summary (prompt-enforced; config `max_words` default 100).
5. **Message source**: Snapshot the in-memory `messages` list accumulated by `Executor._stream_and_collect` — not `execution_aget_state`.
6. **Non-blocking**: Summary LLM runs in a background `asyncio` task; must not stall the CoreAgent stream.
7. **Failure isolation**: LLM errors skip the tick and retry next interval; never fail the execute step.
8. **Transport heartbeat preserved**: IG-549 10s heartbeat remains separate (connection liveness vs semantic progress).
9. **Verbosity gating**: Suppress display at `quiet` verbosity (RFC-501 alignment).

---

## 3. Design principles

### 3.1 Sidecar reporter, not graph change

Progress reporting is an **executor-side sidecar** attached to `_stream_and_collect`. No CoreAgent middleware, no LangGraph topology change, no ledger mutation.

### 3.2 Snapshot, don't poll state

The reporter reads a **copy** of the live message accumulator via a supplier callback. This matches how `_stream_and_collect` already owns the authoritative in-flight message list for token extraction and step outcomes.

### 3.3 Cheap auxiliary LLM

Summaries use the `fast` model role by default. This is observability, not reasoning — latency and cost matter.

### 3.4 One summary in flight per step

If the previous LLM call has not finished when the next interval fires, skip the tick. Avoid overlapping calls and out-of-order UI updates.

### 3.5 Idempotent display

Each progress event **replaces** the running footer text on the step card. Clients show the latest summary only (no history list in P0).

---

## 4. Architecture

### 4.1 Data flow

```
CoreAgent.execution_astream()
        │
        ▼
Executor._stream_and_collect()
        │
        ├── accumulates messages[] on each chunk
        ├── yields wire events (tools, tokens, …) immediately
        │
        └── ExecuteStepProgressReporter (background task)
                │
                every interval_s (default 60):
                ├── snapshot = copy(messages)
                ├── if empty or unchanged since last → skip
                ├── compact snapshot → bounded text (~8K chars)
                ├── LLM summarize (fast role, ~100 words)
                └── yield wire event execute_step_progress
                        │
                        ▼
                Runner._runner_strange_loop maps → StrangeLoopStepProgressEvent
                        │
                        ▼
                TUI textual_adapter → CognitionStepMessage.set_progress_summary()
```

### 4.2 Parallel execute

Each `_execute_step_collecting_events` invocation runs its own `_stream_and_collect` loop and therefore its own reporter instance. Events carry `step_id`; the TUI routes to the matching step card independently. No cross-step aggregation.

---

## 5. Components

### 5.1 `ExecuteStepProgressReporter`

**Location**: `packages/soothe/src/soothe/sloop/engine/execute_step_progress.py` (new)

**Responsibilities**:

- Start background `asyncio.Task` when `_stream_and_collect` begins (if enabled)
- Loop: `await asyncio.sleep(interval_s)` → snapshot → summarize → callback
- Cancel on stream completion, step error, or parent task cancellation
- Track `last_summary_fingerprint` (hash of compacted input) to skip redundant LLM calls when nothing changed

**Public API** (sketch):

```python
class ExecuteStepProgressReporter:
    def __init__(
        self,
        *,
        step_id: str,
        step_description: str,
        interval_s: float,
        message_supplier: Callable[[], list[BaseMessage]],
        summarize: Callable[[list[BaseMessage], str], Awaitable[str | None]],
        on_summary: Callable[[str, int, int], Awaitable[None]],  # summary, elapsed_ms, tool_count
    ) -> None: ...

    def start(self) -> None: ...
    async def stop(self) -> None: ...
```

`on_summary` is invoked by the reporter; `_stream_and_collect` implements it by yielding a `_StreamCollectChunk.wire_event(...)`.

### 5.2 Message compaction

**Location**: `execute_step_progress.py` or `foundation/sloop/utils/message_compact.py`

Convert `list[BaseMessage]` to a bounded plain-text block for the summarizer prompt:

| Message kind | Included content |
|--------------|------------------|
| `AIMessage` / `AIMessageChunk` | Text content; tool call names + arg previews (reuse `_preview_claude_tool_input` pattern) |
| `ToolMessage` | Tool name, status, truncated result (reuse `preview()` / `tool_output_max_chars` caps) |
| `HumanMessage` | **Exclude** initial execute envelope (static task brief; wastes tokens) |
| `SystemMessage` | **Exclude** |

**Input cap**: `execute_step_progress_input_max_chars` (default 8000). Truncate oldest tool results first if over cap.

### 5.3 LLM summarizer

**Location**: `execute_step_progress.py`

```python
async def summarize_execute_step_progress(
    compacted_transcript: str,
    *,
    step_description: str,
    max_words: int,
    model_router: ModelRouter,
    model_role: ModelRole = "fast",
) -> str | None:
```

**Prompt contract** (system + user):

- Audience: end user watching a long-running agent step
- Output: single paragraph, ≤ `max_words` words
- Cover: what has been accomplished so far, what is currently in progress, any blockers or errors surfaced in tool results
- Do not invent facts not present in the transcript
- Do not repeat the full task description verbatim

**Timeout**: 30s; on timeout return `None` (skip tick).

### 5.4 Wire event (internal stream)

Emitted inside `_stream_and_collect` as a custom stream chunk (same path as `step_heartbeat`):

```python
((), "custom", {
    "type": "execute_step_progress",
    "step_id": step_id,
    "summary": summary_text,
    "elapsed_ms": elapsed_ms,
    "tool_call_count": tool_call_count,
})
```

### 5.5 Catalog event

**Location**: `packages/soothe/src/soothe/events/catalog.py`

```python
class StrangeLoopStepProgressEvent(LifecycleEvent):
    """Interim execute-step progress for TUI/WebSocket (in-flight only)."""

    type: Literal["soothe.cognition.strange_loop.step.progress"] = (
        "soothe.cognition.strange_loop.step.progress"
    )
    step_id: str
    summary: str
    elapsed_ms: int
    tool_call_count: int = 0
```

**Runner mapping**: `packages/soothe/src/soothe/runner/_runner_strange_loop.py` — handle internal `execute_step_progress` alongside `step_started` / `step_completed`.

**Visibility**: Register as client-broadcast lifecycle event; `is_progress_wire_event` returns true (prefix `soothe.cognition.strange_loop`).

### 5.6 TUI display

**Location**: `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`, `cognition_step.py`

1. Handle `soothe.cognition.strange_loop.step.progress` in the stream event dispatcher.
2. Resolve step card via `StepRouter` / `_current_step_messages[step_id]`.
3. New method on `CognitionStepMessage`:

```python
def set_progress_summary(self, summary: str) -> None:
    """Update running footer with latest interim progress narrative."""
```

- Only applies while `_status == "running"`; ignored after `set_complete`.
- Replaces generic running footer text; spinner animation continues in header.
- Truncate display to ~300 chars with ellipsis if needed (full text available on expand in P1 — P0 shows truncated footer).

**Thinking row** (optional P0): set spinner `hint_extra` to first ~60 chars of summary when no tools are pending.

**Verbosity**: Skip rendering when `config.verbosity == "quiet"`.

---

## 6. Configuration

**Location**: `packages/soothe/src/soothe/config/models.py` — nested under `AgentLoopConfig` (or new `ExecuteStepProgressConfig` on `agent.loop`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `execute_step_progress_enabled` | `bool` | `true` | Master enable |
| `execute_step_progress_interval_s` | `int` | `60` | Seconds between summaries; `0` = disabled |
| `execute_step_progress_max_words` | `int` | `100` | LLM output word target |
| `execute_step_progress_model_role` | `ModelRole` | `fast` | Router role for summarizer |
| `execute_step_progress_input_max_chars` | `int` | `8000` | Compacted transcript cap |
| `execute_step_progress_llm_timeout_s` | `float` | `30.0` | Per-summary LLM timeout |

**Sync**: Update `config/config.template.yml` and `config/develop/config.yml` with matching structure.

---

## 7. Integration points

### 7.1 `_stream_and_collect` (primary hook)

At method entry (after budget/setup):

1. If disabled (`interval_s == 0` or `enabled == false`), proceed unchanged.
2. Create `ExecuteStepProgressReporter` with `message_supplier=lambda: list(messages)`.
3. `reporter.start()` before `async for chunk in stream`.
4. In `on_summary` callback: yield `_StreamCollectChunk.wire_event(...)`.
5. In `finally`: `await reporter.stop()`.

The reporter must not yield directly — it calls back into the async generator's context via an `asyncio.Queue` or similar bridge if needed to avoid re-entrancy issues. **Preferred pattern**: reporter pushes summaries to a `asyncio.Queue`; the main `async for` loop drains the queue with `asyncio.wait` / non-blocking `get_nowait` between stream chunks (same pattern as parallel live event queue).

### 7.2 First summary timing

First summary fires after the **first full interval** elapses (e.g. 60s), not immediately at step start. If the step completes before the first interval, no summary is emitted.

### 7.3 Unchanged paths

| Path | Change |
|------|--------|
| `_core_agent_astream_with_interrupt_resume` | None (heartbeat stays 10s) |
| `_append_parallel_wave_ledger` / RFC-227 | None |
| `step_completed` emission | None |
| CoreAgent graph / middleware | None |

---

## 8. Error handling

| Scenario | Behavior |
|----------|----------|
| LLM timeout / API error | Log warning at DEBUG/INFO; skip tick; retry next interval |
| Previous summary still in flight | Skip tick |
| Empty message snapshot | Skip tick |
| Snapshot identical to last successful summary | Skip tick (fingerprint match) |
| Step completes / stream cancelled | Cancel reporter task immediately |
| Reporter task raises unhandled exception | Log error; cancel reporter; **do not** fail the step stream |
| `quiet` verbosity | Event still emitted on wire (for headless/logging); TUI suppresses render |

---

## 9. Testing

| Test | Location | Asserts |
|------|----------|---------|
| Reporter start/stop/cancel | `tests/unit/core/loop/engine/test_execute_step_progress.py` | Task lifecycle, no leak after stream end |
| Interval skip when in-flight | same | Second tick skipped while LLM pending |
| Fingerprint dedup | same | No LLM call when messages unchanged |
| Message compaction bounds | same | Output ≤ `input_max_chars`; human/system excluded |
| Summarizer mock | same | Word limit passed to prompt; timeout returns None |
| Wire event shape | `test_executor_*` or dedicated | Custom chunk has `type=execute_step_progress` + `step_id` |
| Runner catalog mapping | `tests/unit/runner/` | Internal type → `StrangeLoopStepProgressEvent` |
| TUI handler | `soothe-cli/tests/unit/ux/tui/` | Event updates running step card footer; ignored after complete |
| Parallel isolation | integration or unit | Two reporters, distinct `step_id`, no cross-routing |
| Disabled config | unit | `interval_s=0` → no reporter started |

Run `./scripts/verify_finally.sh` before merge.

---

## 10. Files (expected touch list)

| File | Change |
|------|--------|
| `foundation/sloop/engine/execute_step_progress.py` | **New** — reporter, compaction, summarizer |
| `foundation/sloop/engine/executor.py` | Wire reporter into `_stream_and_collect` |
| `foundation/sloop/engine/step_wave_types.py` | Optional: progress queue item type |
| `foundation/events/catalog.py` | `StrangeLoopStepProgressEvent` |
| `foundation/events/__init__.py` | Export |
| `runner/_runner_strange_loop.py` | Map `execute_step_progress` |
| `config/models.py` | Config fields |
| `config/config.template.yml` | Mirror |
| `config/develop/config.yml` | Mirror |
| `soothe-cli/tui/textual_adapter.py` | Event handler |
| `soothe-cli/tui/widgets/messages/cognition_step.py` | `set_progress_summary()` |
| `soothe-sdk` (if wire models generated) | Optional typed event model |
| `tests/unit/...` | Coverage per §9 |

---

## 11. Future extensions (not P0)

- **P1**: Expandable progress history on step card (last N summaries)
- **P1**: Headless/JSONL renderer for progress events
- **P2**: Adaptive interval (shorter when tool error detected, longer when idle)
- **P2**: Feed condensed latest summary into thinking-row only at `minimal` verbosity

---

## 12. Open decisions (resolved in this draft)

| Question | Decision |
|----------|------------|
| Primary consumer | TUI / WebSocket |
| Parallel execute | Per-step summaries |
| Message source | `_stream_and_collect` accumulator |
| vs IG-549 heartbeat | Keep both; different purposes |
| vs RFC-227 digest | No interaction |

---

## 13. Acceptance criteria

1. A execute step running longer than `interval_s` emits at least one `soothe.cognition.strange_loop.step.progress` event with ≤100-word summary.
2. Parallel steps each emit progress tagged with their own `step_id`; TUI updates the correct card.
3. Step completion cancels further progress events for that step.
4. LLM failure during summary does not fail the step.
5. `execute_step_progress_interval_s: 0` disables the feature entirely.
6. `quiet` verbosity suppresses TUI rendering.
7. `./scripts/verify_finally.sh` passes.

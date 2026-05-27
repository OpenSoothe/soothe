# IG-441: Three-mode goal_completion delivery (batch / adaptive / streaming)

## Goal

1. Replace the "stream then go silent" behavior of `adaptive` stream delivery
   with a two-phase pipeline that keeps the user informed of progress on long
   synthesis outputs while still reducing wire frame count vs. raw passthrough.
2. Document the precise semantics of `batch` mode so the contract is clear.
3. Add an explicit `streaming` mode for raw passthrough at the LLM's native
   generation rate (no buffering, no coalescing of goal_completion frames).

## Background

`StreamDeliveryCoalescer` (`packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py`)
shapes runner stream tuples before broadcast. Two delivery modes existed:

- `batch`: buffer the whole goal_completion synthesis, emit one
  `AIMessageChunk` with `chunk_position="last"` at `agent_loop.completed`.
- `adaptive` (default): stream each chunk individually until cumulative
  emitted chars reach `adaptive_threshold_chars` (default 500), then **switch
  to pure batch** for every remaining chunk.

The SDK and CLI used to default clients to a `stream_delivery="streaming"`
request, but the daemon session manager silently coerced it to `batch` because
the `StreamDeliveryMode` literal only allowed `batch | adaptive`. IG-441 makes
`streaming` a first-class mode **and** promotes `adaptive` to the default
across the whole stack (`OutputStreamingConfig`, SDK
`bootstrap_loop_session` / `send_loop_subscribe`, CLI daemon execution,
daemon protocol router fallback, and session-manager fallback). Mode is
chosen as: explicit subscribe request → session preference → `adaptive`.

The second phase of `adaptive` was effectively the same as `batch` from that
point on — no client output until completion. For long synthesis (e.g. loop
c191 turn 2: 11079 chars / ~70 s) the user observed:

```
t=0   .. ~3s : smooth streaming of first ~500 chars
t=~3s ..70s  : silent (10.5 KB buffered in daemon)
t=70s        : one ~10.5 KB AIMessageChunk arrives at once
```

— indistinguishable from a hung agent.

## Design

### Three-mode taxonomy

| Mode | Phase tracker | Behaviour |
| --- | --- | --- |
| `batch` | always `batch` | Buffer the entire goal_completion. Single `AIMessageChunk` emitted at `agent_loop.completed` with `chunk_position="last"`. No real-time visibility. |
| `adaptive` (default) | `streaming` → `chunked_streaming` → final flush | Two-phase: per-chunk passthrough below `adaptive_threshold_chars`; block-buffered flushes after threshold (see below). Final block carries `chunk_position="last"`. |
| `streaming` | always `streaming` | Raw passthrough at the LLM's native generation rate. Every goal_completion chunk forwarded immediately, no buffering, no transition. Highest wire-frame count. |

When `file_output_threshold_chars > 0` *every* mode behaves like `batch` for
goal_completion so the file-vs-wire decision sees the complete text.

### Adaptive phase transitions

```
streaming (cumulative chars < adaptive_threshold_chars)
    ↓ (cumulative ≥ threshold)
chunked_streaming  ←─ size flush (buffer ≥ adaptive_block_chars)
                   ←─ time flush (now - last_block ≥ adaptive_block_interval_ms)
    ↓ (agent_loop.completed)
final flush (chunk_position="last" if remainder, else no trailing frame)
```

### Streaming phase (unchanged)

Each goal_completion `AIMessageChunk` is forwarded individually. `gc_streamed_chars`
counts cumulative streamed text. Once `gc_streamed_chars + buffered_chars + incoming_chars
≥ adaptive_threshold_chars`, the coalescer transitions to chunked_streaming and the
threshold-crossing chunk is the first contribution to the buffer.

### Chunked-streaming phase (new)

Incoming chunks accumulate into `_GoalCompletionBuffer`. A block flush is
triggered by either of:

| Trigger | Knob | Default |
| --- | --- | --- |
| Buffer size ≥ N chars | `adaptive_block_chars` | 500 |
| Elapsed since last block ≥ T ms | `adaptive_block_interval_ms` | 250 |

The default `adaptive_block_chars=500` aligns with `adaptive_threshold_chars`
so the first post-cutover block is roughly the same size as one streamed
chunk window, producing a smooth handover from phase 1 to phase 2.

When a flush fires, the buffer text is emitted as one `AIMessageChunk` with
`phase="goal_completion"` and `chunk_position` unset (intermediate). The
buffer is cleared but `_GoalCompletionBuffer.template_msg` / `template_meta`
remain so subsequent blocks reuse the same template.

The time-based trigger is checked at the start of every `ingest()` call
(alongside the existing `_flush_due_tool_batches` pass) so the inter-block
delay does not exceed `adaptive_block_interval_ms` whenever any chunk is
arriving.

### Final flush

At `agent_loop.completed` (or `flush()` at end of stream):

- Pure `batch` mode: emits the full buffered text with `chunk_position="last"`.
- `chunked_streaming` phase: emits any remaining buffer text with
  `chunk_position="last"`. If the previous intermediate block left the buffer
  empty, no trailing frame is emitted (the prior block already carried the
  data; only the `agent_loop.completed` custom event goes out).

### file_output interaction

`file_output_threshold_chars > 0` forces the goal_completion path into
**pure-batch buffering** regardless of mode/phase. Streaming partial blocks
would defeat the file_output decision (which needs the full text to compare
against the threshold). The buffer is examined at the final flush and either
sent to file (with a summary message) or emitted as a single
`AIMessageChunk`.

### TUI compatibility

No TUI changes required. Goal-completion chunks already mount onto a single
`AssistantMessage` card via `append_content`, with finalization on
`chunk_position="last"` (see IG-440 for the prerequisite that chunk identity
survives the wire).

## Configuration

`OutputStreamingConfig` (`packages/soothe/src/soothe/config/models.py`):

```yaml
agent:
  loop:
    output_streaming:
      mode: adaptive                    # batch | adaptive | streaming
      adaptive_threshold_chars: 500     # phase-1 → phase-2 cutover (adaptive)
      adaptive_block_chars: 500         # phase-2 block size (adaptive)
      adaptive_block_interval_ms: 250   # phase-2 max ms between blocks (adaptive)
```

Tuning guide:

- **Lower latency on long outputs (adaptive)** → reduce `adaptive_block_chars`
  (e.g. 256) and/or `adaptive_block_interval_ms` (e.g. 150).
- **Fewer wire frames on fast streams (adaptive)** → raise
  `adaptive_block_chars` (e.g. 2048).
- **Token-level fidelity** → set `mode: streaming` (pure passthrough; the
  block knobs are ignored).
- **Headless / scripted runs** → set `mode: batch` (single final frame; the
  block knobs are ignored).

## Pure `batch` mode contract

For completeness, the precise semantics of `batch` mode after IG-441:

- All goal_completion chunks accumulate into `_GoalCompletionBuffer` (no wire
  emission during synthesis).
- At `agent_loop.completed`:
  - If `file_output_threshold_chars > 0` and `len(text) ≥ threshold`:
    write the text to a file under `file_output_dir` (or
    `<workspace>/.soothe/output/`) and emit a single `AIMessageChunk` with
    a preview + file path.
  - Otherwise: emit one `AIMessageChunk` containing the full text with
    `phase="goal_completion"` and `chunk_position="last"`.
- Plain assistant text (non-goal_completion) still uses the per-namespace
  text coalescer with quiet-gap flushing (`coalesce_interval_ms`).

## Metrics

New properties on `StreamDeliveryCoalescer` for observability:

- `goal_completion_phase` — `"streaming" | "chunked_streaming" | "batch"`
- `goal_completion_block_flush_count` — number of intermediate block flushes
  this turn

## Tests

`packages/soothe-daemon/tests/unit/daemon/test_stream_delivery.py`:

- `test_adaptive_mode_switches_to_chunked_streaming_on_threshold` — replaces
  the pre-IG-441 "switches to batch" test, asserts phase transition and the
  no-duplicate guarantee.
- `test_adaptive_chunked_streaming_emits_size_based_blocks` — verifies block
  flush on `adaptive_block_chars` crossing with time-based flush disabled.
- `test_adaptive_chunked_streaming_time_based_block_flush` — verifies block
  flush on `adaptive_block_interval_ms` with size-based flush disabled,
  using a monkeypatched monotonic clock.
- `test_streaming_mode_passthrough_every_goal_completion_chunk` — verifies
  that mode `streaming` never enters the chunked-streaming phase regardless
  of threshold/block knob values.
- `test_streaming_mode_file_output_still_buffers` — guards the file_output
  override in mode `streaming`.
- `test_adaptive_chunked_streaming_with_file_output_uses_pure_batch` —
  guards the file_output incompatibility fallback for mode `adaptive`.

## Verification

```bash
cd packages/soothe-daemon && uv run pytest tests/unit/daemon/test_stream_delivery.py -v
./scripts/verify_finally.sh
```

## Relationship to recent IGs

- **IG-439** (mode=messages envelope visibility) — unblocked daemon → client
  delivery of `mode=messages` envelopes.
- **IG-440** (preserve AIMessageChunk identity on wire) — unblocked the TUI
  synthesis-stream branch by keeping the chunk class identity intact.
- **IG-441** (this) — keeps the user informed of progress for long synthesis
  outputs by replacing the "go silent after threshold" behavior with
  block-buffered streaming, adds a first-class `streaming` mode, and makes
  `adaptive` the default for every entry point (SDK, CLI, daemon).

## Status

Completed.

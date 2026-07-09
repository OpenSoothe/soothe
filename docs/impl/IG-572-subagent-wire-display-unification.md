# IG-572: Unified Subagent Wire Display Protocol

**Status**: Complete  
**RFC**: RFC-403 §8.4, RFC-619 §8, RFC-628 (SubAgent card), RFC-500 (stream forwarding)  
**Depends on**: IG-339 (curated wire), IG-513/IG-515 (SubAgent card)

## Problem

Loop `d393` showed an empty SubAgent card during `deep_research` despite the engine logging many
`soothe.subagent.deep_research.*` events. Root causes:

1. **Transport** — StrangeLoop runner `_forward_messages_chunk` dropped all `custom`-mode
   payloads except `soothe.stream.tool_call.update`; subagent wire events never reached WebSocket clients.
2. **Visibility** — `deep_research.progress` was registered at `INTERNAL`; daemon wire ceiling suppressed it even if forwarded.
3. **TUI mapping** — Only `.gather.summary` and `.step.completed` rendered as rows; `.progress`, `.crawl.summary`, and `.started` were ignored.
4. **Duplication** — Research engines, TUI row mapping, and emit paths were copy-pasted per subagent.

## Solution

### Transport (runner)

- Forward curated `soothe.subagent.*` custom stream chunks when
  `is_curated_subagent_wire_event_type` and `is_custom_stream_payload_client_visible` pass.
- Module: `packages/soothe/src/soothe/runner/_runner_strange_loop.py`

### Unified display protocol (SDK)

- **`soothe_sdk.ux.subagent_wire_display`**
  - `SubagentWireRenderKind`: `activity_note` | `activity_row` | `lifecycle_end`
  - `classify_subagent_wire_render(event_type)` — suffix-based classifier (row kinds checked before `.completed`)
  - `subagent_wire_row_params(event_type, data)` — synthetic tool-row fields for TUI/CLI
- **`soothe_sdk.ux.subagent_progress.summarize_subagent_wire_activity`** — one-line summaries for notes (includes Veritas + research signals)

### TUI routing

- **`_route_subagent_wire_event`** in `textual_adapter.py` dispatches by `SubagentWireRenderKind`:
  - `activity_row` → synthetic tool rows on SubAgent card
  - `activity_note` → `append_subagent_activity`
  - `lifecycle_end` → finalize card + sync parent task row

### Shared research emitter

- **`soothe.subagents.research_wire.ResearchWireEmitter`** — shared `.progress` / `.step.completed` for
  `deep_research` and `academic_research`.

### Emission consistency

- **`browser_use`** — emit via `soothe.utils.subagent_emit` (step_id context), not SDK-only emitter.
- **`veritas`** — wire types registered on `soothe.subagents` package import.
- **Research gather** — `gather.summary` includes `sources_touched`; each gather loop emits `step.completed` with query/hit/crawl preview and `duration_ms`.

### Legacy removed

- `make_subagent_tool_started/completed/failed` (unused catalog helpers)
- `SUBAGENT_BROWSER_USE_DISPATCHED` / `SUBAGENT_BROWSER_USE_STEP` aliases
- `DisplayPolicy.is_deep_research_event` → `is_subagent_wire_event`

## Builtin signal matrix

| Signal suffix | Render kind | Builtins using it |
|---------------|-------------|-------------------|
| `.started` | note | deep_research, academic_research, browser_use |
| `.progress` | note | deep_research, academic_research |
| `.step.completed` | row | deep_research, academic_research, browser_use |
| `.gather.summary`, `.crawl.summary` | row | deep_research, academic_research |
| `.requested`, `.answered`, `.deferred` | note | veritas |
| `.completed`, `.failed` | lifecycle | all task-delegated subagents |

Graph-native subagents (research, browser) rely on wire events for SubAgent card activity; tool-calling subgraphs may also show `{step}:t{n}:tool` rows from the `messages` stream.

## Tasks

- [x] Runner forward curated subagent custom events
- [x] Promote `.progress` tier to NORMAL (deep_research, academic_research)
- [x] SDK display classifier + row params
- [x] TUI `_route_subagent_wire_event`
- [x] `ResearchWireEmitter` + gather emission tweaks
- [x] browser_use / veritas alignment
- [x] Remove dead catalog/display helpers
- [x] Tests + `./scripts/verify_finally.sh`
- [x] RFC / IG documentation (this guide)

## Verification

```bash
./scripts/verify_finally.sh
```

Manual: run a `deep_research` task in TUI — SubAgent card should show phase notes, WebSearch/Crawl rows, and lifecycle footer while running.

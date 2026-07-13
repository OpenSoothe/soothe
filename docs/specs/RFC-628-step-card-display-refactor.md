# RFC-628: Cognition Step Card & SubAgent Card Display

**RFC**: 628
**Title**: Cognition Step Card & SubAgent Card Display
**Status**: Implemented
**Kind**: Implementation Interface Design
**Created**: 2026-06-26
**Updated**: 2026-06-26
**Authors**: Xiaming Chen
**Depends on**: RFC-500 (CLI/TUI Architecture), RFC-501 (Display Verbosity), RFC-607 (Progressive Display Refinements)
**Extends**: RFC-500 § Event Rendering (step card), RFC-501 § 7.3 (TUI step card body)
**Implemented by**: IG-512-step-card-display-refactor.md, IG-513-subagent-card.md, IG-514-execute-namespace-tool-stamping-fix.md, IG-515-step-subagent-card-footer-and-lifecycle-fixes.md
**Design draft**: `docs/archive/drafts/2026-06-26-subagent-card-flattened-display.md`

---

## Abstract

This RFC is the **canonical specification** for the Textual TUI **step card** (`CognitionStepMessage`): layout, activity tree, running status lines, tool-count semantics, refresh orchestration, and module boundaries. It consolidates and supersedes scattered step-card guidance previously referenced only via IG-402/IG-421/IG-428 in RFC-500 and RFC-501.

Implementation lives in `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step.py` (widget lifecycle) and `cognition_step_activity.py` (pure classification and rendering).

---

## Relationship to Other RFCs

| RFC | Role |
|-----|------|
| **RFC-500** | Places step cards in TUI architecture (`execute_step` → `CognitionStepMessage`, stream routing). **Normative step-card UX is defined here (RFC-628).** |
| **RFC-501** | Verbosity tiers for ActivityInfo; step cards are always visible in ConversationPanel regardless of tier. |
| **RFC-607** | Progressive display refinements post-migration; step cards follow the same cognition gutter and card-header patterns. |
| **RFC-201 / RFC-614** | Loop AI message phases (`execute_step`, tool wire updates) that feed the step card via `textual_adapter`. |

Historical implementation guides (IG-402 tool aggregation, IG-421 stats, IG-428 activity preview) remain useful for archaeology; **new work MUST follow this RFC.**

---

## Motivation

### Problems addressed (2026-06-26 refactor)

1. **Missing tool counts** — Footer showed `Running... (10s) · 1 task` without `· N tools` because stats excluded nested subgraph tools; orphan and mixed main+task branches omitted branch suffixes.
2. **Fragmented row classification** — Multiple helpers re-filtered `_rows` independently; preview and stats drifted.
3. **Fragmented refresh** — Footer and activity panel could desync across six repaint entry points.
4. **Obsolete auto-collapse** — Activity already capped at three preview lines per scope; auto-collapse hid body zones without benefit.
5. **Monolithic widget** — ~2145 lines mixed lifecycle, rendering, and policy.

### Goals (all implemented)

1. Every **Running** line (footer and each activity branch) shows `· N tools` when N > 0 for that scope.
2. Footer shows **total** tool count (main + subgraph + orphan) plus task delegation count when present.
3. **Single surface sync** — `_sync_step_card_surface()` repaints activity, footer, and timer.
4. **Extracted module** — testable pure builders in `cognition_step_activity.py`.
5. **No auto-collapse** — manual click-to-collapse only.

---

## Step Card Overview

When StrangeLoop emits `step.started` / tool wire updates for the **main** stream (and no goal-tree aggregate card is active), the TUI mounts one **step card** per plan step. Main-agent tool traffic is **not** a separate card per tool; subgraph `task` delegations appear as branches inside the same card.

### Widget zones

```
CognitionStepMessage
├── step-header          (#step-cognition-header)     step description only
├── step-subagent-notes  (#step-cognition-subagent-notes)  activity tree (RFC-628)
├── step-tools           (#step-cognition-tools)        optional full nested list
├── step-detail          (#step-cognition-detail)       execute prose / clarification / error
└── step-status          (#step-cognition-status)       footer status line
```

| Zone | Visible when | Content |
|------|--------------|---------|
| Header | Always | `● {description}` via `_assemble_card_header` |
| Activity tree | Tool rows, task delegations, or subagent notes exist | `StepActivityTree.render` |
| Tools panel | `STEP_CARD_SHOW_TOOL_ROW_DETAILS = True` | Full nested tool list (default **off**) |
| Detail | Execute streaming, clarification Q&A, or error prose | `branched_prose_body` |
| Footer | Step not bare header-only | `StepCardStatusLine` (pending / queued / running / complete) |

**Invariant:** Non-empty activity body while running ⇒ `#step-cognition-subagent-notes.display == True`.

### Manual collapse

Click the card (when collapsible content exists) toggles `-collapsed` CSS, hiding activity, detail, tools, and footer. Header stays visible. **No automatic collapse** — preview caps bound visible lines.

---

## Activity Tree

Rendered by `StepActivityTree.render` from `StepRowIndex` (see below).

### Preview cap

`STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT = 2` — latest N tool invocation lines **per scope** (task branch children, main-agent tools, orphan subgraph tools).

### Render order

1. **Task delegations** — `SubAgentName(description)` label → child tool preview lines → branch status line → per-task subagent notes
2. **Main-agent tools** — preview lines → main branch Running status when step is `running` **and task delegations exist** (main-only steps rely on footer Running to avoid duplicate lines)
3. **Orphan subgraph tools** — preview lines → orphan branch Running when step is `running` **and** (task delegations or main tools exist)
4. **Global subagent notes** — prose/metadata not tied to a task key

### Tool line format

Goal-tree gutter (`⎿`), phase icon (hollow circle / spinner / checkmark / error), `ToolName(args)`, optional phase tail (duration, failed, etc.). Formatting via `soothe_cli.tui.tool_display`.

### Branch status lines (running)

Each scope gets its own Running line with elapsed time and **scope-local** tool count:

```
⎿   ⠋ Running... (12s) · 6 tools     ← task branch (child count)
⎿ ⠋ Running... (45s) · 2 tools       ← main branch (mixed layout only)
⎿ ⠋ Running... (45s) · 4 tools       ← footer (always; main-only steps show Running here only)
```

Completed branches use Done / Failed / Skipped with the same stats suffix pattern.

---

## Stats Semantics

### `StepRowIndex` (single-pass classification)

Built by `StepRowClassifier.build(step_id, rows)` on every surface sync.

| Field | Semantics |
|-------|-----------|
| `task_delegations` | Step-level `task` rows (`{step}:s:task:…`) |
| `main_tools` | Direct main-agent tools (type `s`, not task, no parent) |
| `orphan_tools` | Subgraph tools without visible task parent |
| `children_by_task` | Map task dedupe key → child tool rows |
| `total_tool_count` | Distinct tool rows excluding task rows and task-metadata-only rows |
| `main_tool_count` | Count of `main_tools` |
| `task_delegation_count` | Count of `task_delegations` |

### Footer (running)

```
⎿ {spinner} Running... ({elapsed}) · {total} tools[, {M} tasks][ · in:… out:…][ (retry)]
```

- `{total}` = `StepRowIndex.total_tool_count` (main + subgraph + orphan)
- `{M}` = `StepRowIndex.task_delegation_count`
- Token budget and retry suffixes append after stats (unchanged)

### Footer (pending / queued)

```
⎿ ○ Pending... · {total} tools[, {M} tasks]
⎿ ○ Queued... · {total} tools[, {M} tasks]
```

### Footer (complete)

```
⎿ ✓ Completed ({duration}) · {total} tools[, {M} tasks][ · tokens]
⎿ ✗ Failed · {duration} · …
```

When `set_complete(tool_call_count=N)` and `N > index.total_tool_count`, footer may use server `N` (debug log) for parity with goal-tree counts.

---

## Tool Row Lifecycle

| Row kind | Initial phase on `add_tool_call` | Notes |
|----------|----------------------------------|-------|
| Main-agent (`{step}:s:…`) | `pending` | Hollow circle until result |
| Subgraph (`{step}:t{n}:…` or parented) | `running` | Spinner when step running |
| Task delegation (`is_task_row`) | `pending` | Branch header only |

Phase transitions on step complete via `finalize_tool_rows_on_step_end` (success marks open subgraph tools done; failure marks skipped).

---

## Surface Sync Pipeline

All state changes funnel through `_sync_step_card_surface()` in `CognitionStepMessage`:

```text
_sync_step_card_surface()
  ├─ index = StepRowClassifier.build(step_id, rows)
  ├─ activity = StepActivityTree.render(index=index, …)
  ├─ paint #step-cognition-subagent-notes
  ├─ footer = StepCardStatusLine (footer scope)
  ├─ paint #step-cognition-status
  ├─ paint detail if execute/clarification buffers changed
  ├─ optional #step-cognition-tools if STEP_CARD_SHOW_TOOL_ROW_DETAILS
  └─ maybe_start_running_timer()
```

**Call sites:** `add_tool_call`, tool phase setters, `set_running`, `on_mount`, `set_complete`, `set_interrupted`, animation tick.

**Deferred mount:** `_flush_deferred_state_on_mount()` — interrupted → complete → running → surface sync.

---

## Module Layout

| Module | Responsibility |
|--------|----------------|
| `cognition_step.py` | Widget compose/CSS/mount, public stream API, `_sync_step_card_surface`, animation, manual collapse |
| `cognition_step_activity.py` | `StepToolRow`, `StepRowIndex`, `StepRowClassifier`, `StepActivityTree`, `StepCardStatusLine`, `finalize_tool_rows_on_step_end`, `stats_title_suffix`, `branched_prose_body` |
| `preview_limits.py` | `STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT`, `STEP_CARD_SHOW_TOOL_ROW_DETAILS`, `STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD` (full-list fold only) |
| `textual_adapter.py` | Wire ingest → `add_tool_call` / `StepTaskRouter` (unchanged contract) |

**Dependency rule:** `cognition_step_activity.py` MUST NOT import Textual widgets; callers pass resolved theme colors and glyphs.

---

## Configuration

| Constant | Default | Purpose |
|----------|---------|---------|
| `STEP_CARD_SHOW_TOOL_ROW_DETAILS` | `False` | When `True`, also render full nested list in `#step-cognition-tools` |
| `STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT` | `2` | Latest tool lines per scope in activity tree |
| `STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD` | `3` | Fold threshold for optional full tool list only (not card auto-collapse) |

---

## Data Flow

```text
Daemon stream (messages + tool wire)
  └─ textual_adapter.apply_tool_call_wire_update
       └─ StepTaskRouter (namespace / task binding)
            └─ CognitionStepMessage.add_tool_call(…)
                 └─ _rows / _row_index mutate
                      └─ _sync_step_card_surface()
                           ├─ StepRowClassifier.build
                           ├─ StepActivityTree.render
                           ├─ StepCardStatusLine (footer)
                           └─ running timer
```

Execute-phase prose (`phase=execute_step`) appends to `#step-cognition-detail` via `append_execute_assistant_delta`. Goal completion remains on `AssistantMessage` (RFC-500).

---

## Testing

| Suite | Coverage |
|-------|----------|
| `test_cognition_step_activity.py` | Classifier, stats suffix, render invariants |
| `test_step_card_running_stats.py` | Footer running stats, animation, wire timing |
| `test_step_card_task_activity.py` | Task branches, preview caps, dedupe |
| `test_step_tool_stats_ingest.py` | Wire → row registration |

Run `./scripts/verify_finally.sh` before merge.

---

## Out of Scope

- Daemon stream batching or `StepTaskRouter` routing rule changes
- `CognitionGoalTreeMessage` refactor (footer fallback reconcile only)
- Removing manual click-to-collapse
- Server-owned display card ledger replay (RFC-413) — separate effort

---

## References

- RFC-500 — CLI/TUI architecture and `LoopAIMessage` routing
- RFC-501 — display verbosity (ActivityInfo vs ConversationPanel)
- RFC-607 — progressive display refinements
- IG-512 (step card) — `docs/impl/IG-512-step-card-display-refactor.md`
- IG-513 (SubAgent) — `docs/impl/IG-513-subagent-card.md`
- IG-514 (execute namespace stamping) — `docs/impl/IG-514-execute-namespace-tool-stamping-fix.md`
- IG-515 (footer & lifecycle fixes) — `docs/impl/IG-515-step-subagent-card-footer-and-lifecycle-fixes.md`
- Design draft — `docs/archive/drafts/2026-06-26-subagent-card-flattened-display.md`

---

# Part II: SubAgent Card (Flattened Display)

The following sections define the `SubAgentMessage` widget and routing model for flattened step/task display. This replaces the nested `children_by_task` model from the original implementation.

---

## SubAgent Card Overview

Each task/subagent delegation gets its own card (`SubAgentMessage`) appearing immediately after the parent step card. The step card shows a **flat list** of tool calls and task rows — no nesting.

### Motivation

The original nested model (`children_by_task`, indented tool lines) had:
1. Complex classification logic to track parent IDs and match children
2. Orphan handling for subgraph tools without visible parents
3. Visual hierarchy through indentation (hard to parse at speed)

The flattened model:
1. Step shows flat row list (tools and `Task(...)` markers as peers)
2. Each SubAgent card owns its own tool rows and status
3. Direct routing via unified ID parsing — no parent matching

### Widget zones

```
SubAgentMessage (extends CognitionStepMessage)
├── subagent-header          ◆ SubAgentName(description)
├── subagent-activity        activity tree (tool rows only)
├── subagent-detail          execute prose (optional)
└── subagent-status          footer: running → completed/failed
```

| Zone | Visible when | Content |
|------|--------------|---------|
| Header | Always | `◆ {subagent_type}({description})` via `_assemble_card_header` |
| Activity | Tool rows exist | Flat tool activity lines |
| Detail | Execute streaming prose | `branched_prose_body` |
| Footer | Not bare header | `StepCardStatusLine` (running → success/error) |

**CSS:** Inherits `CognitionStepMessage` styles — same cognition-orange border, same structure.

---

## Display Layout

```
⎿ ● Step: search and analyze
  ○ read_file(query.txt)
  ○ Task(search_web)              ← flat row, peer with tools
  ○ write_file(results.md)
  ○ Running... · 3 tools, 1 task

⎿ ◆ Task(search_web)              ← SubAgent card, after parent step
  ○ web_search("query")
  ○ read_search_results()
  ✓ Completed (1.2s) · 2 tools

⎿ ● Step: summarize findings     ← next step
  ...
```

### Multiple delegations

Sequential cards after parent step:

```
⎿ ● Step: research
  ○ Task(search_web)
  ○ Task(analyze_papers)

⎿ ◆ Task(search_web)
  ○ ...tools...

⎿ ◆ Task(analyze_papers)
  ○ ...tools...
```

---

## Routing Model

### Registry

Message list maintains `_subagent_cards_by_key: dict[str, SubAgentMessage]` where key = `{step}:t{n}`.

### Routing flow

| Unified ID pattern | Route target |
|--------------------|--------------|
| `{step}:s:task:{n}` | Create SubAgent card + add task row to step |
| `{step}:t{n}:tool_name` | Lookup SubAgent card → `add_tool_call` |
| `{step}:s:tool_name` (non-task) | Step card → `add_tool_call` |

**Creation timing:** SubAgent card created when task call streams in (`task(description, subagent_type=...)`). Card starts with `running` status immediately.

### Simplified StepRowIndex

After flattening, `StepRowIndex` removes nesting fields:

| Field | Status |
|-------|--------|
| `task_delegations` | Kept — flat marker rows on step |
| `main_tools` | Kept — main-agent tools |
| `orphan_tools` | **Removed** — no orphans |
| `children_by_task` | **Removed** — no nested children |
| `total_tool_count` | Kept — main + task markers |
| `task_delegation_count` | Kept |

---

## Status Sync

When SubAgent card completes:

1. SubAgent footer: `Completed (X.Xs) · N tools` or `Failed (X.Xs)`
2. Step's corresponding task row icon syncs: `✓ Task(...)` or `✗ Task(...)`

Implementation: SubAgent card calls `step.sync_task_row_status(task_key, success)` via message list mediation.

---

## Lifecycle

| Card | Phases |
|------|--------|
| `CognitionStepMessage` | `pending → queued → running → success/error` (unchanged) |
| `SubAgentMessage` | `running → success/error` only |

SubAgent has no pending/queued states — created when task call arrives (already active).

---

## Module Layout

| Module | Changes |
|--------|---------|
| `cognition_step.py` | Remove `children_by_task` classification, simplify activity |
| `cognition_step_activity.py` | Remove `_child_rows_for_task`, `children_by_task`, orphan logic |
| `cognition_subagent.py` | NEW — `SubAgentMessage` subclass |
| `messages/__init__.py` | Export `SubAgentMessage` |
| Message list container | Add `_subagent_cards_by_key` registry, routing logic |

---

## Removed Complexity

| Removed | Reason |
|---------|--------|
| `StepRowIndex.children_by_task` | No nested children |
| `StepRowClassifier._child_rows_for_task()` | Not needed |
| `StepRowClassifier._orphan_subgraph_tool_rows()` | No orphans |
| Nested indentation rendering | Flat display |
| Task-branch status lines in step card | SubAgent shows its own footer |
| `parent_tool_call_id` nesting tracking | Unified ID parsing sufficient |

---

## Testing

| Suite | Coverage |
|-------|----------|
| `test_subagent_message_creation.py` | Card created on task call |
| `test_subagent_tool_routing.py` | Inner tools route correctly |
| `test_subagent_status_sync.py` | Completion syncs to step row |
| `test_flat_step_activity.py` | Step shows flat rows |

Run `./scripts/verify_finally.sh` before merge.

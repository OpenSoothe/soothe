# CognitionStepMessage — Step Card Display Refactor

**Date:** 2026-06-26  
**Status:** Implemented — **canonical spec is [RFC-628](../specs/RFC-628-step-card-display-refactor.md)**  
**Scope:** TUI step card (`CognitionStepMessage`) — activity tree, status lines, stats, refresh orchestration, module extraction

---

## Problem Statement

Users expect step cards to show:

1. A capped activity tree (latest tool invocations for main-agent and subagent branches)
2. Running status lines with elapsed time **and** tool totals (e.g. `⎿ ⠋ Running... (10s) · 12 tools, 1 task`)
3. Consistent behavior for main-agent tools, task delegations, and orphan subgraph tools

**Observed (2026-06-26):**

- Activity tree renders and a `Running... (10s)` line appears
- The `· N tools` suffix is **missing** on the line the user sees
- Auto-collapse still runs even though activity is already capped at 3 preview lines
- `cognition_step.py` (~2145 lines) has fragmented classification, rendering, and refresh paths that make bugs hard to prevent

---

## Root Cause Analysis

### 1. Split stats semantics (high confidence)

| Location | Current count source | Gap |
|----------|---------------------|-----|
| Footer (`_stats_title_suffix`) | Main-agent tools + task delegation **rows** | Excludes nested subgraph tools |
| Task branch status | `child_rows` only | Missing when children unmatched but tools appear via orphan path |
| Main branch status | `main_rows` | Skipped when any task delegation row exists |
| Orphan subgraph preview | Tool lines only | No Running/status line at all |

### 2. Auto-collapse is obsolete (high confidence)

`STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT = 3` already bounds visible activity. Auto-collapse adds complexity and can hide activity/footer via `-collapsed` CSS without improving UX.

### 3. Five overlapping row classifiers (high confidence)

`_row_counts_for_step_status_line`, `_main_agent_tool_rows_for_preview`, `_orphan_subgraph_tool_rows_for_preview`, `_child_rows_for_task`, `_iter_task_delegation_rows`, and `_build_nested_row_order` each re-walk `_rows` with slightly different filters — preview vs stats drift.

### 4. Six lifecycle paint paths (medium confidence)

`pending`, `queued`, `running`, `success`, `error`, and interrupted each have separate footer/branch builders with duplicated gutter, icon, tone, and theme lookup.

### 5. Fragmented refresh orchestration (medium confidence)

Multiple repaint entry points (`add_tool_call`, `_refresh_tools_display`, `_refresh_task_activity_display`, `_sync_running_status_text`, `_ensure_running_ui`, `on_mount`) allow footer and activity panel to drift.

---

## Design Goals

1. **Every Running line includes tool counts** when N > 0 for that line's scope.
2. **Remove auto-collapse** — preview cap is sufficient; keep manual click-to-collapse only.
3. **Single refresh pipeline** — `_sync_step_card_surface()` updates all zones consistently.
4. **Total tool count on footer** — main + subgraph + orphan tools, plus task count when present.
5. **Extract testable module** — row index, activity renderer, and status line builder in `cognition_step_activity.py` before shipping.
6. **YAGNI** — polish existing behavior only; no new user-facing features.

---

## Approaches Considered

### A. Stats fix only, defer extraction

**Rejected** — fixes the symptom but leaves fragmented classifiers that will regress.

### B. Stats fix + in-file unification (index + status builder)

**Rejected** — user chose full extraction before ship.

### C. Full refactor with `cognition_step_activity.py` (chosen)

Extract row model, classification, rendering, and stats into a dedicated module; slim `CognitionStepMessage` to widget lifecycle + `_sync_step_card_surface()`.

**Pros:** Testable pure functions, enforces stats invariants in one place, sustainable maintenance.  
**Cons:** Larger single PR; requires careful import boundaries and test migration.

---

## Module Architecture

### File split

```
packages/soothe-cli/src/soothe_cli/tui/widgets/messages/
├── cognition_step.py              # Widget lifecycle, compose, mount, public API (~800 lines target)
├── cognition_step_activity.py     # Row model, index, render, stats (NEW, ~500–600 lines)
└── _helpers.py                      # Shared card header, throttling (unchanged)
```

### `cognition_step_activity.py` responsibilities

| Unit | Purpose |
|------|---------|
| `StepToolRow` | Dataclass (moved from cognition_step) |
| `StepRowIndex` | Single-pass classification of `_rows` for a step |
| `StepRowClassifier` | Builds index: task delegations, main, orphan, children_by_task, totals |
| `StepActivityTree` | Pure render: `_rows` + index + step state → `Content` for activity panel |
| `StepCardStatusLine` | Pure render: footer + branch status lines (pending/queued/running/done/failed) |
| `StepToolLine` | Shared single-row renderer for activity preview and optional full panel |
| `finalize_tool_rows_on_step_end` | Phase transition table for step completion |

### `cognition_step.py` responsibilities (retained)

| Concern | Methods |
|---------|---------|
| Widget compose / CSS / mount | `compose`, `on_mount`, `on_click` |
| Public stream API | `add_tool_call`, `set_running`, `set_complete`, tool phase setters, snapshots |
| Surface sync orchestration | `_sync_step_card_surface`, `_flush_deferred_state_on_mount` |
| Execute / clarification / error detail | `append_execute_assistant_delta`, `set_clarification_details`, `set_awaiting_clarification` |
| Animation timer | `_update_running_animation`, `_maybe_start_running_timer` |
| Manual collapse | `toggle_collapse`, `_refresh_collapse_state` |
| Optional full tool panel | `_refresh_tools_display` (thin wrapper when flag enabled) |
| Token budget / retry | `record_token_usage`, `set_retry_status` |

### Dependency direction

```
cognition_step.py  →  cognition_step_activity.py  →  tool_display, theme, soothe_sdk.ux.*
_helpers.py        →  (no dependency on activity module)
```

`CognitionStepMessage` passes `step_id`, `_rows`, `_status`, timing state, and subagent notes into pure builders; builders return `Content` without querying widgets.

---

## `StepRowIndex` — unified classification

Built once per row mutation, cached on the widget until `_rows` or row phases change.

```python
@dataclass(frozen=True)
class StepRowIndex:
    task_delegations: tuple[StepToolRow, ...]
    main_tools: tuple[StepToolRow, ...]
    orphan_tools: tuple[StepToolRow, ...]
    children_by_task: dict[str, tuple[StepToolRow, ...]]
    total_tool_count: int          # distinct ids, excl. task rows + metadata-only
    main_tool_count: int
    task_delegation_count: int
```

**Rules (unchanged semantics, centralized):**

- `main_tools`: unified type `s`, not task, belongs to step, no parent, not metadata-only
- `orphan_tools`: type `t` or parented, no visible task parent, not matched by task_idx dedupe
- `children_by_task`: keyed by `_task_delegation_dedupe_key`
- `total_tool_count`: all non-task-row, non-metadata-only rows on this step

All stats suffixes and preview caps read from the index — no duplicate filters.

---

## Stats model

**Footer** (running):

```
⎿ ⠋ Running... (10s) · {total} tools[, {M} tasks][ · in:1.2K out:345][ (2/3 attempts)]
```

- `total` from `StepRowIndex.total_tool_count`
- `M` from `StepRowIndex.task_delegation_count`
- Token budget and retry suffix unchanged

**Activity branches** — `StepCardStatusLine.build(scope=...)`:

| Scope | Row set | When |
|-------|---------|------|
| `task` | `children_by_task[key]` | Task delegation branch |
| `main` | `main_tools` | Main-agent tools (even when tasks exist) |
| `orphan` | `orphan_tools` | Orphan subgraph tools |

Each Running branch line includes `· N tools` for its scope. Completed/failed branches keep Done/Failed/Skipped words with stats suffix.

**Completion footer fallback:** When `set_complete(tool_call_count=N)` and `N > index.total_tool_count`, use `N` in footer suffix (reconcile with goal-tree server count); log at debug.

---

## `StepCardStatusLine` — unified status builder

Single builder replaces `_main_branch_status_line`, `_task_branch_status_line`, `_sync_running_status_text`, `_refresh_pending_display`, `_refresh_queued_display`, and the completion head in `_update_step_footer_status_line`.

```python
class StepCardStatusLine:
    @staticmethod
    def build(
        *,
        phase: Literal["pending", "queued", "running", "success", "error", "skipped"],
        scope: Literal["footer", "main_branch", "task_branch", "orphan_branch"],
        gutter: str,
        stats: StepRowStats,           # counts + suffix strings for scope
        elapsed_secs: int | None,
        spinner_frame: str,
        colors: ThemeColors,
        glyphs: Glyphs,
        head_override: str | None = None,  # completion head text
        token_suffix: str = "",
        retry_suffix: str = "",
    ) -> Content: ...
```

Theme/glyph lookup stays in the widget; builders receive resolved values (pure, testable).

---

## `StepActivityTree` — activity panel renderer

```python
class StepActivityTree:
    @staticmethod
    def render(
        *,
        step_id: str,
        status: str,
        index: StepRowIndex,
        rows: list[StepToolRow],
        subagent_notes: list[str],
        subagent_notes_by_task: dict[str, list[str]],
        task_activity_starts: dict[str, float],
        step_start_time: float | None,
        spinner_position: int,
        preview_limit: int = STEP_CARD_TOOL_ACTIVITY_PREVIEW_COUNT,
        colors: ThemeColors,
        glyphs: Glyphs,
    ) -> Content: ...
```

**Content rules (approved + extended):**

1. Task branches: label → child preview lines → branch status line → per-task notes
2. Main tools: preview lines → main branch status (running) even when task rows exist
3. Orphan tools: preview lines → orphan branch status (running)
4. Global subagent notes appended last
5. Latest-N preview via shared `_latest_preview_rows`

---

## Remove auto-collapse & dead code

**Delete:**

- `_maybe_auto_collapse_step_card()` and all call sites
- `_step_body_line_estimate()`
- `#step-collapse-hint` widget, `_collapse_hint_widget`, `_sync_step_footer_hint` (always hidden)
- `_rebuild_tool_stats()` (inline into surface sync)
- `_task_tool_phase_icon`, `_task_tool_status_tail` (unused)
- `_has_active_main_branch_animation` / `_has_active_task_branch_animation` (replace with index-based check in surface sync)

**Keep:**

- `toggle_collapse()` / `-collapsed` CSS for manual header click
- `_step_card_user_expanded` (cleared on `set_running`)
- `STEP_TASK_CARD_COLLAPSE_LINE_THRESHOLD` for optional full tool-list folding only

**Update `preview_limits.py` comment** — remove "auto-collapses" wording for step cards.

---

## Unified sync pipeline

```
_sync_step_card_surface()
  ├─ index = StepRowClassifier.build(step_id, rows)   # rebuild if rows/version changed
  ├─ activity = StepActivityTree.render(index=index, ...)
  ├─ _paint_activity_widget(activity)
  ├─ footer = StepCardStatusLine.build(scope=footer, ...)
  ├─ _paint_footer(footer)
  ├─ _paint_detail_if_needed()                        # execute / clarification buffers
  ├─ _refresh_tools_display_if_enabled()                # STEP_CARD_SHOW_TOOL_ROW_DETAILS
  └─ _maybe_start_running_timer()
```

**Deferred state** — replace four flags with ordered flush in `_flush_deferred_state_on_mount()`:

1. `deferred_interrupted` → `set_interrupted`
2. `deferred_complete` → `set_complete`
3. `deferred_running` → `set_running`
4. `deferred_surface_sync` → `_sync_step_card_surface`
5. Else paint pending/queued/running from current status

**Animation tick:** advance spinner → `_sync_step_card_surface()` only (no partial updates).

---

## Detail zone unification

Replace `_step_branched_execute_body`, `_step_branched_error_detail`, and clarification layout duplication with:

```python
def branched_prose_body(
    lines: list[str],
    *,
    gutter: str,
    first_line_icon: str | None,
    tone: str,
    continuation_tone: str,
) -> Content: ...
```

Used by execute streaming, completion prose, errors, and clarification Q&A.

---

## Tool phase behavior

**Keep current asymmetry** (document in module docstring):

- Main-agent rows: `pending` until result (hollow circle)
- Subgraph rows: `running` on arrival (spinner when step running)

Animation gating uses `index` + row phases instead of separate `_has_active_*` helpers.

---

## Component layout (unchanged)

```
CognitionStepMessage
├── step-header
├── step-subagent-notes   ← StepActivityTree.render
├── step-tools            ← optional; StepToolLine when flag enabled
├── step-detail           ← branched_prose_body
└── step-status           ← StepCardStatusLine footer scope
```

**Invariant:** Non-empty activity + running → `step-subagent-notes.display == True`.

---

## Data flow

```
textual_adapter.apply_tool_call_wire_update
  └─ CognitionStepMessage.add_tool_call
       └─ _rows / _row_index mutate
            └─ _sync_step_card_surface()
                 ├─ StepRowClassifier.build
                 ├─ StepActivityTree.render
                 ├─ StepCardStatusLine.build (footer)
                 └─ timer
```

---

## Testing Plan

### New unit tests (`tests/unit/ux/tui/test_cognition_step_activity.py`)

| Test | Asserts |
|------|---------|
| `test_row_index_classifies_main_task_orphan` | Mixed rows → correct index buckets |
| `test_row_index_total_tool_count_includes_subgraph` | Subgraph tools counted in total |
| `test_activity_tree_orphan_running_has_tool_count` | Orphan scope status line |
| `test_activity_tree_mixed_main_and_task_branches` | Both branch status lines with counts |
| `test_status_line_footer_running_total_tools` | Footer includes total + tasks |
| `test_status_line_pending_queued_with_stats` | Pending/queued footers include suffix |
| `test_finalize_tool_rows_success_marks_subgraph_done` | Phase table on complete |

### Updated existing tests

| Test file | Changes |
|-----------|---------|
| `test_step_card_running_stats.py` | Footer total tools; no auto-collapse |
| `test_step_card_task_activity.py` | Rename `test_status_line_still_excludes_nested_task_tools` → `test_footer_stats_include_all_step_tools` |
| `test_step_tool_stats_ingest.py` | Wire path still populates index totals |

### Integration / widget tests

| Test | Asserts |
|------|---------|
| `test_no_auto_collapse_on_many_tools` | 7 tools running → never `-collapsed` auto |
| `test_manual_collapse_still_works` | Click toggle adds `-collapsed` |
| `test_sync_surface_on_deferred_mount` | Pre-mount tools → painted on mount |
| `test_deferred_running_set_running_refreshes_task_activity_panel` | Still green via surface sync |

Run `./scripts/verify_finally.sh` before commit.

---

## Implementation Order (single PR)

All steps ship together per Option C:

1. **Scaffold** `cognition_step_activity.py` — move `StepToolRow`, add `StepRowClassifier`, `StepRowIndex` with tests
2. **Extract** `StepActivityTree.render` — migrate `_step_task_activity_content` logic + approved gap fixes
3. **Extract** `StepCardStatusLine.build` — migrate all status line builders
4. **Extract** `StepToolLine` — shared row line for activity + optional panel
5. **Extract** `finalize_tool_rows_on_step_end` from `mark_unfinished_tools_on_step_complete`
6. **Refactor** `cognition_step.py` — `_sync_step_card_surface`, deferred flush, remove dead code + auto-collapse
7. **Update** `preview_limits.py` comment; migrate/adjust existing tests
8. **Verify** `./scripts/verify_finally.sh`

---

## Out of Scope

- Changing daemon stream batching or `StepTaskRouter` routing rules
- `CognitionGoalTreeMessage` refactor (only footer fallback reconcile on complete)
- `STEP_CARD_SHOW_TOOL_ROW_DETAILS = True` full panel UX overhaul
- Removing manual click-to-collapse
- Main-agent tool phase promotion to `running` on arrival (kept as-is; revisit later)

---

## Decision Log

| Date | Decision |
|------|----------|
| 2026-06-26 | Initial draft: auto-collapse + stats fix |
| 2026-06-26 | User clarified: activity visible, `· N tools` missing; remove auto-collapse |
| 2026-06-26 | **Approved:** stats invariant + remove auto-collapse; keep manual collapse |
| 2026-06-26 | Full step card review: unify classifiers, status builders, dead code removal |
| 2026-06-26 | **Approved Option C:** full extraction to `cognition_step_activity.py` before ship |
| 2026-06-26 | **Implemented:** RFC-628 / IG-628; verify_finally.sh green |

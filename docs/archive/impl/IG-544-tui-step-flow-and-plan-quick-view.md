# IG-544: TUI Step Flow — Collapsed File Previews + Plan Quick View

**Related**: [RFC-500](../specs/RFC-500-cli-tui-architecture.md), [RFC-628](../specs/RFC-628-step-card-display-refactor.md)  
**Created**: 2026-07-03  
**Status**: In progress (Phase 2 implemented)

---

## Problem

In dependency-mode plans with many file edits, the main transcript loses step locality:

1. **`FileChangePreviewWidget` mounts full diff cards** into `#messages` — each edit can consume 8+ lines.
2. When STEP-2 starts, its step card is buried under N expanded file previews from STEP-1.
3. Users cannot see **where they are in the plan** without scrolling.

**Rejected approaches** (2026-07-03):

- **Candidate A** — `StepTurnGroup` DOM container per step.
- **Candidate B (step-card absorb)** — file rows inside `CognitionStepMessage` / split preview caps.
- **Option 2 split streams** — separate Files vs Recent tools sections in the step card.

**Accepted**: Keep **RFC-628 step cards unchanged**. Shrink **file preview widgets** to collapsed one-liners in the message stream; click to expand.

---

## Phase 1 — Collapsed file previews ✅

### Behavior

| State | Display |
|-------|---------|
| **Default (collapsed)** | One line: `Write  path/to/file  +12 −3` (or `new file`, line range) |
| **Expanded (click)** | Current full preview: header + diff / content lines |
| **Finalize** | Updates summary stats; stays collapsed unless user expanded |

### Implementation

| File | Change |
|------|--------|
| `widgets/file_change_preview.py` | `-collapsed` / `-expanded` CSS; `on_click` toggle; `ALLOW_SELECT` |
| `app/app.tcss` | Global styles retained; widget `DEFAULT_CSS` owns collapse rules |
| `tests/unit/ux/tui/test_file_change_preview.py` | Collapse toggle + finalize preserves state |

### Message flow (unchanged mount path)

```text
STEP-1  (CognitionStepMessage — unchanged, latest 3 tools)
Write   src/a.py  +5 −2          ← collapsed FileChangePreviewWidget
Edit    src/b.py  +1 −1
STEP-2  (CognitionStepMessage)
…
```

### Non-goals (Phase 1)

- No changes to `CognitionStepMessage`, `StepActivityTree`, or `sync_pending_step_cards_from_plan`.
- No absorption of file previews into step cards.

---

## Phase 2 — Plan quick view (Ctrl+t) ✅

Replace ad-hoc `RunningStepsOverlay` with a **plan aggregate** quick view.

| Piece | Role |
|-------|------|
| `CognitionGoalTreeMessage` | Live full plan (goal + all steps + phases); wired on `plan_decision` / step lifecycle |
| `PlanQuickViewOverlay` | Floating panel above chat input; **Ctrl+t** toggles; snapshots goal tree |
| Removed | `RunningStepsOverlay`, `running_overlay_content()` on step cards |

### Phase 2 polish — plan tree display ✅

| Enhancement | Behavior |
|-------------|----------|
| Step dependencies | Per-row `(→ STEP-1)` suffix from `plan_decision.dependencies` |
| Running live stats | Elapsed duration + current tool count (synced from step cards) |
| Completed dedup | Hide `Done [N tools]` summary tail when structured `· N tools` suffix is shown |
| Single-line width | Clip step description so full row fits terminal width (`PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS`) |
| Overlay chrome | Compact panel padding, tinted scrollbar, bold title + dim close/Enter hints |
| Loop id header | Abbreviated `prefix...suffix` loop id (avoids full UUID clutter) |
| Done footer duration | Total goal completion duration on the last status line (`Done · … · 2m 5s`) |
| Running status | Thinking-row style live footer while steps run: `spinner Running... (12s)` |
| Overlay-only paint | Spinner ticks update in-memory frame only; remount paths keep DOM sync no-ops |

---

## Phase 3 — Dependency step visibility (optional) — pending

Optional follow-up if collapsed previews are insufficient:

- Lazy-mount pending step cards in **dependency** mode (goal tree only at plan time).
- Auto-collapse completed step cards + scroll anchor when next step starts.

**Not started** — evaluate after Phase 1 dogfooding.

---

## Phase 1 checklist

- [x] `FileChangePreviewWidget` collapsed by default
- [x] Click toggles expand (respect text selection)
- [x] `finalize_from_record` preserves collapsed state
- [x] `GenericFilePreviewWidget` uses header line when collapsed
- [x] Unit tests for collapse toggle and finalize
- [x] `./scripts/verify_finally.sh`

---

## Phase 2 checklist (plan quick view)

- [x] Wire live `CognitionGoalTreeMessage` on `plan_decision`
- [x] Extend `_StepLineState` for `pending` / `queued` phases
- [x] Add `PlanQuickViewOverlay`; Ctrl+t binding
- [x] Remove `RunningStepsOverlay` prototype
- [x] Tests: goal tree plan population, overlay toggle
- [x] Plan tree polish: dependencies, running duration/tools, deduped summaries, line-width clip
- [x] `./scripts/verify_finally.sh`

---

## Verification

```bash
./scripts/verify_finally.sh
```

Phase 1 targeted:

```bash
uv run pytest packages/soothe-cli/tests/unit/ux/tui/test_file_change_preview.py -q
```

---

## UX acceptance (Phase 1)

1. A step that edits 10+ files adds **10 one-line rows**, not 10 multi-line diff cards.
2. Clicking a row expands diff/content; clicking again collapses.
3. Step cards and tool activity preview (latest 3) are **unchanged**.

# SubAgent Card — Flattened Step/Task Display

**Date:** 2026-06-26
**Status:** Draft — approved design for RFC-628 update and IG-629
**Scope:** TUI step card + new SubAgent card (`SubAgentMessage`) — flatten nested tool display, route inner tools to separate cards

---

## Problem Statement

Current `CognitionStepMessage` nests subagent tool calls under task delegation rows:

```
⎿ 🚀 Step: search and analyze
  ○ Task(search_web)              ← task delegation header
    ○ web_search("query")         ← nested child tool
    ○ read_results()              ← nested child tool
    ✓ Done · 2 tools              ← nested branch status
  ○ write_file(results.md)
  ○ Running... · 5 tools, 1 task
```

**Issues:**

1. **Complex classification logic** — `StepRowClassifier` must track `children_by_task`, match parent IDs, and handle orphan tools
2. **Nested rendering complexity** — indentation, child previews, branch status lines increase maintenance burden
3. **Poor visual hierarchy** — users must visually parse nested indentation to understand delegation boundaries
4. **Step card clutter** — main-agent tools and task delegations compete for space in the same activity panel

---

## Design Goals

1. **Flat step card** — step shows tools and task delegations as peers (no nesting)
2. **Dedicated SubAgent cards** — each task delegation gets its own card (mini-step) appearing immediately after the parent step
3. **Direct routing** — inner subagent tools route to SubAgent card, not to step's nested children
4. **Status sync** — step's task row mirrors SubAgent card's terminal status (✓/✗ icon)
5. **Reuse existing patterns** — SubAgent card has same layout as step card (header, activity, footer)
6. **YAGNI** — remove `children_by_task` classification, nesting logic, and orphan handling

---

## Approaches Considered

### A. Keep nesting, add collapse toggle

**Rejected** — doesn't address routing complexity; nesting still requires classification.

### B. Inline expansion (click task row → reveal card in-place)

**Rejected** — requires Textual DOM manipulation, breaks message list ordering, adds click-state tracking.

### C. Flattened display with separate SubAgent cards (chosen)

Step shows flat list; SubAgent cards appear after step in message list. Both reuse same rendering patterns.

**Pros:** Simple routing, familiar card pattern, clear visual hierarchy, removes nested classification.
**Cons:** New widget class, message list routing changes.

---

## Architecture

### Two Card Types

| Card | Header glyph | Purpose | Appears |
|------|--------------|---------|---------|
| `CognitionStepMessage` | 🚀 | Main-graph step execution | In message list per `step.started` |
| `SubAgentMessage` | 🎯 | Subagent/task delegation | Immediately after parent step card |

`SubAgentMessage` subclasses `CognitionStepMessage`:
- Inherits CSS (cognition-orange border), activity panel, status footer
- Override: header glyph (🎯), no pending/queued phases (born running)

### Display Layout (example)

```
⎿ 🚀 Step: search and analyze
  ○ read_file(query.txt)
  ○ Task(search_web)              ← flat row, peer with tools
  ○ write_file(results.md)
  ○ Running... · 3 tools, 1 task

⎿ 🎯 Task(search_web)             ← SubAgent card, immediately after
  ○ web_search("query")
  ○ read_search_results()
  ✓ Completed (1.2s) · 2 tools

⎿ 🚀 Step: summarize findings     ← next step
  ...
```

---

## Routing Model

### Routing responsibilities

The TUI adapter (`textual_adapter.py`) maintains:

```python
_subagent_cards_by_key: dict[str, SubAgentMessage] = {}
# Key format: "{step}:t{n}" (step ID + task index)
```

### Routing flow

```
Tool call wire update arrives
  ├─ Parse unified ID: "{step}:{type}:{idx}:{tool_info}"
  │
  ├─ If type == "s" and tool_info starts with "task:"
  │     └─ Create SubAgentMessage (if not exists)
  │     └─ Register in _subagent_cards_by_key["{step}:t{idx}"]
  │     └─ Insert card after parent step in message list
  │     └─ Also add task row to step card's _rows (flat marker)
  │
  ├─ If type == "t" (subgraph tool)
  │     └─ Lookup _subagent_cards_by_key["{step}:t{idx}"]
  │     └─ Route tool call to SubAgentMessage.add_tool_call()
  │
  └─ Else (main-agent tool)
      └─ Route to CognitionStepMessage.add_tool_call()
```

### Creation timing

SubAgent card created **when task call streams in** — no lazy creation, no deferred mount. Card starts with `running` status immediately.

---

## Status Sync

When SubAgent card completes:

1. SubAgent footer updates: `Completed (X.Xs) · N tools` or `Failed (X.Xs)`
2. Step's corresponding task row updates icon: `✓ Task(description)` or `✗ Task(description)`

Implementation: SubAgent card calls `step.sync_task_row_status(task_key, success)` via parent reference or message list mediation.

---

## Lifecycle

| Card | Phases |
|------|--------|
| `CognitionStepMessage` | `pending → queued → running → success/error` (unchanged) |
| `SubAgentMessage` | `running → success/error` only (no pending/queued — created active) |

SubAgent footer format matches step footer: `Completed (1.2s) · 5 tools` or `Failed (0.8s)`.

---

## Multiple Delegations

A step may have multiple task calls. SubAgent cards appear **sequentially after the parent step**:

```
⎿ 🚀 Step: research topic
  ○ Task(search_web)
  ○ Task(analyze_papers)

⎿ 🎯 Task(search_web)
  ○ ...tools...

⎿ 🎯 Task(analyze_papers)
  ○ ...tools...

⎿ 🚀 Step: write summary
  ...
```

Each SubAgent card registered independently with unique `{step}:t{n}` key.

---

## Module Layout

| Module | Changes |
|--------|---------|
| `cognition_step.py` | Remove `children_by_task` classification, remove nesting render, simplify `StepRowIndex` |
| `cognition_step_activity.py` | Remove `_child_rows_for_task`, `children_by_task` field, orphan logic; keep flat row rendering |
| `cognition_subagent.py` | NEW — `SubAgentMessage` subclass with 🎯 header glyph |
| `messages/__init__.py` | Export `SubAgentMessage` |
| `textual_adapter.py` or message list | Add `_subagent_cards_by_key` registry, routing logic, card creation/insertion |

---

## Removed Complexity

| Removed | Reason |
|---------|--------|
| `StepRowIndex.children_by_task` | No nested children; tools route to SubAgent card |
| `StepRowClassifier._child_rows_for_task()` | Not needed |
| `StepRowClassifier._orphan_subgraph_tool_rows()` | No orphans — all subgraph tools have known SubAgent card |
| Nested indentation rendering | Flat display |
| Task-branch status lines in step card | SubAgent card shows its own footer |
| `parent_tool_call_id` tracking for nesting | Not needed for routing (unified ID parsing sufficient) |

---

## Implementation Order

1. **Create `SubAgentMessage`** — subclass with 🎯 glyph, simplified lifecycle
2. **Add registry** — `_subagent_cards_by_key` in message list
3. **Update routing** — parse unified IDs, route type `t` tools to SubAgent cards
4. **Simplify `StepRowIndex`** — remove `children_by_task`, `orphan_tools`
5. **Simplify `StepActivityTree`** — flat tool/task rows only, no nesting
6. **Add status sync** — SubAgent completion → step task row icon update
7. **Update tests** — remove nesting tests, add flat/SubAgent routing tests
8. **Verify** — `./scripts/verify_finally.sh`

---

## Testing Plan

| Test | Coverage |
|------|----------|
| `test_subagent_message_creation.py` | SubAgent card created on task call |
| `test_subagent_tool_routing.py` | Inner tools route to correct SubAgent card |
| `test_subagent_status_sync.py` | Completion updates step's task row |
| `test_flat_step_activity.py` | Step shows flat tool/task rows |
| `test_multiple_delegations.py` | Sequential SubAgent cards after step |

---

## Out of Scope

- Daemon stream changes
- `CognitionGoalTreeMessage` refactor
- `STEP_CARD_SHOW_TOOL_ROW_DETAILS` full panel
- Changing unified ID format

---

## Decision Log

| Date | Decision |
|------|----------|
| 2026-06-26 | Initial brainstorming: flatten nested display |
| 2026-06-26 | Q1: SubAgent cards appear immediately after step (Option 1) |
| 2026-06-26 | Q2: Simple label row on step (Option 1) |
| 2026-06-26 | Q3: Match step card header style (Option 1) |
| 2026-06-26 | Q4: Same layout as step card (Option 4) |
| 2026-06-26 | Q5: Route tools directly to SubAgent card (Option 1) |
| 2026-06-26 | Q6: Create on first task call (Option 1) |
| 2026-06-26 | Q7: Status icon sync to step's task row (Option 1) |
| 2026-06-26 | Q8: Sequential cards after parent step (Option 1) |
| 2026-06-26 | Q9: Simplified lifecycle (running → success/error) (Option 2) |
| 2026-06-26 | Q10: Match step footer format (Option 1) |
| 2026-06-26 | Q11: SubAgentMessage subclass (Option 2) |
| 2026-06-26 | Q12: Message list observes task calls (Option 2) |
| 2026-06-26 | Q13: Registry mapping for routing (Option 2) |
| 2026-06-26 | Q14: Same CSS as step (Option 1) |
| 2026-06-26 | **Approved:** flattened design with SubAgent cards |
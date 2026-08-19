# IG-750: Context Projection Consolidation — Findings & Action Plan

**Created**: 2026-08-19
**Status**: Implemented
**Related**:
[RFC-624](../specs/RFC-624-context-engine.md) (Context Engine),
[RFC-214](../specs/RFC-214-strangeloop-loop-message-surface.md) (loop message ledger),
[IG-744](IG-744-autopilot-goal-dag-pair-projection.md) (goal-report-pair projection),
[IG-748](IG-748-cognition-intention-layout.md) (cognition/intention layout)

---

## Goal

Consolidate the Context Engine projection layer (`soothe.context.projection`) and
its consumers in `soothe.sloop.prompts` / `soothe.sloop.cognition.planner` by
acting on six re-analysis findings: four dead-field / duplicate-work findings
that waste cycles on every `context_engine.project()` call, and two O(n²)
char-budget loops that scale poorly as the ledger grows. This IG specifies the
remediation design and an ordered action plan. It does **not** introduce new
projection features — it removes waste and fixes complexity.

---

## Context projection logic map

The authoritative projection entry point is
`ContextEngine.project()` (`packages/soothe/src/soothe/context/engine.py:1228`),
which delegates to `ProjectionEngine.project()`
(`packages/soothe/src/soothe/context/projection.py:69`). The produced
`ContextBundle` flows into prompt assembly via five call sites in
`packages/soothe/src/soothe/sloop/cognition/planner.py`:

| Site | planner.py line | goal_id? | Consumer (build_plan_messages → …) |
|------|-----------------|----------|------------------------------------|
| `analyze_plan_gap` | 1188 | yes | `build_plan_messages(kind="gap")` |
| `_plan_assess` | 1102 | yes | `build_plan_messages(kind="assess")` |
| `_plan_generate` (mid-goal) | 1259 | yes | `build_plan_messages(kind="generate")` |
| `_plan_generate` (new-goal) | 1424 | no | `build_plan_messages(kind="generate")` |
| continuation assess | 1589 | no | `build_plan_messages(kind="assess")` |

`build_plan_messages` (`packages/soothe/src/soothe/sloop/prompts/graph_wrapper.py`)
threads `context_bundle` into:

- `UserMessageBuilder._append_shared_plan_sections`
  (`packages/soothe/src/soothe/sloop/prompts/user_message.py:358`) — reads
  `context_bundle.prior_goals`, `context_bundle.goal_lineage`,
  `context_bundle.step_lineage`.
- `build_system_message` (`graph_wrapper.py:316-330`) — loads memory
  instructions directly via `SemanticLoader.load_memory()` for non-`assess`/`gap`
  kinds only (option (a) implemented; see Consolidation Design).
- `build_plan_assess_message` (`graph_wrapper.py:701`) — reads
  `context_bundle.active_goal.last_assessment`.
- `project_ledger(kind="synthesis")` (`graph_wrapper.py:525`) — does NOT read
  the bundle; uses its own ledger projection.

A parallel, independent ledger-projection path exists in
`packages/soothe/src/soothe/sloop/prompts/plan_ledger_projection.py`
(`project_loop_messages_for_plan`, `_trim_total_chars_front`) and in
`packages/soothe/src/soothe/context/ledger.py`
(`LedgerManager.project_for_plan`, `LedgerManager._trim_total_chars`).
These are the char-budget loop sites (Findings 5–6).

**Fields consumed from `ContextBundle` (post-implementation):**
`active_goal`, `goal_lineage`, `step_lineage`, `prior_goals` — 4 fields.

**Fields removed** (Findings 1–3): `goal_progress`, `pending_steps`,
`completed_steps`, `failed_steps`, `ledger_summary`, `ledger_messages`,
`project_instructions`, `agent_instructions`, `memory_instructions`,
`total_tokens_used`, `goal_dag_summary`, `cross_goal_ledger` — 12 fields.

---

## The six findings

### Finding 1 — Dead ContextBundle fields: ledger duplicates and observability

**Location**: `packages/soothe/src/soothe/context/projection.py:152-166` (ledger_messages),
`projection.py:268-283` (`_render_cross_goal_ledger`), `projection.py:183-184`
(`total_tokens_used`, `goal_dag_summary`).

`ContextBundle.ledger_messages` and `ContextBundle.cross_goal_ledger` were built
on every `project()` call by iterating `ledger.entries()` twice (see Finding 4),
yet **neither field was read by any consumer**. `total_tokens_used` and
`goal_dag_summary` were likewise computed (the former sums over all goals, the
latter walks all goals) and never consumed from the bundle — the prompt layer
reads token/DAG status from `LoopState` directly (see `state/schemas.py:1242`,
`state/checkpoint.py:118`).

**Impact**: wasted work per projection; the unused fields also forced
`ledger.entries()` to be materialized twice.

**Action (done)**: Removed `ledger_messages`, `cross_goal_ledger`,
`total_tokens_used`, `goal_dag_summary` from `ContextBundle` and stopped
computing them in `ProjectionEngine.project()`. Dropped the
`_render_cross_goal_ledger` static method. Dropped `ledger_summary` as well
(no consumer found). Removed `ProjectionConfig.max_ledger_messages`.

---

### Finding 2 — Dead semantic-instruction fields on ContextBundle

**Location**: `packages/soothe/src/soothe/context/projection.py:169-180`
(`project_instructions`, `agent_instructions`, `memory_instructions`),
`packages/soothe/src/soothe/context/semantic.py` (SemanticLoader disk reads).

`project_instructions` and `agent_instructions` were loaded from disk
(`CLAUDE.md`, `AGENTS.md`) on every `project()` call and truncated, but
**never read by any consumer**. `memory_instructions` was read in exactly one
place — `graph_wrapper.py:316-320`, only for `kind not in ("assess", "gap")`.
For `assess`/`gap` (3 of 5 call sites) the disk read was pure waste.

**Impact**: three file reads + truncations per projection, two of which were
always dead, the third dead for assess/gap.

**Action (done)**: Removed `project_instructions` and `agent_instructions` from
`ContextBundle`. Chose **option (a)**: removed `memory_instructions` from
`ContextBundle` and moved the `SemanticLoader.load_memory()` call directly into
`graph_wrapper.build_system_message` (`graph_wrapper.py:316-330`), guarded by
`kind not in ("assess", "gap")`. The `SemanticLoader` is constructed lazily
from `state.workspace` at the call site, making the disk-read cost visible
where it is consumed. Removed `ProjectionConfig.max_project_instructions_chars`.

---

### Finding 3 — Dead step-list and goal-progress fields on ContextBundle

**Location**: `packages/soothe/src/soothe/context/projection.py:121-131`
(`goal_progress`, `pending_steps`, `completed_steps`, `failed_steps`).

These four fields were computed (with `sorted()` over step IDs and slicing)
on every projection but **never read by any consumer** in `sloop/prompts` or
`sloop/cognition`. The prompt layer derives step status from `LoopState`
and `DagPlanningContext`, not from the bundle.

**Impact**: per-projection sort + list construction for zero consumers.

**Action (done)**: Removed `goal_progress`, `pending_steps`, `completed_steps`,
`failed_steps` from `ContextBundle` and dropped the computation block
(`projection.py:113-131`). Dropped the `_render_goal_progress` helper method.
Kept `goal_lineage` and `step_lineage` (consumed in `user_message.py:380,399`).

---

### Finding 4 — Duplicate ledger iteration in ProjectionEngine.project()

**Location**: `packages/soothe/src/soothe/context/projection.py:155` and
`projection.py:272`.

`ledger.entries()` was materialized and iterated twice in the same
`project()` call: once to build `ledger_messages` (line 155) and once to
build `cross_goal_ledger` (line 272). Both produced near-identical dicts
(`{type, phase, content}`) truncated to 500 chars. The second pass was fully
subsumed by the first.

**Impact**: 2× ledger walk; the dicts were then discarded (Findings 1).

**Action (done)**: Moot — Finding 1 removed both fields and both iteration
sites. `ProjectionEngine.project()` no longer iterates `ledger.entries()` at
all. The `ledger` parameter is retained on the signature for API stability but
documented as unused.

---

### Finding 5 — O(n²) char-budget loop in plan_ledger_projection

**Location**:
`packages/soothe/src/soothe/sloop/prompts/plan_ledger_projection.py:185-220`
(`_trim_total_chars_front`), originally line 201:
`while out and total_len(out) > max_chars:` where `total_len` called
`sum(_message_text_len(m) for m in ms)` over the **entire remaining
list on every iteration**.

Each loop iteration popped one message from the front and recomputed the sum
over the whole shrinking list. For a ledger of N messages this was O(N²) in
message count, and each `_message_text_len` called
`extract_text_from_message_content` (string normalization) per message per
iteration.

**Impact**: quadratic cost grew with ledger size; hot path for every
plan-assess / plan-generate / continuation-assess prompt.

**Action (done)**: Replaced with a single forward pass:
1. Precompute `lengths = [_message_text_len(m) for m in messages]` once.
2. Compute `total = sum(lengths)`.
3. Walk from the front, subtracting `lengths[start]` from `total` and
   advancing `start`, until `total <= max_chars` or one message remains.
4. Slice `messages[start:]`; if the single remaining message exceeds the
   budget, hard-clip it (preserved existing logic).

This is O(N) with a single `_message_text_len` call per message. The `shrunk`
flag and hard-clip-on-single-message behavior are preserved exactly.

---

### Finding 6 — O(n²) char-budget loops in LedgerManager and graph_wrapper synthesis

**Locations**:

- `packages/soothe/src/soothe/context/ledger.py:204-220`
  (`LedgerManager._trim_total_chars`): originally line 211
  `while out and sum(_text_len(m) for m in out) > max_chars:` — same pattern
  as Finding 5, recomputed the full sum each iteration.
- `packages/soothe/src/soothe/sloop/prompts/graph_wrapper.py:530-550`
  (synthesis budget loop): originally line 524
  `total = len(system_text) + _messages_text_len(ledger_msgs) + len(human_text)`
  recomputed in full on every `while` iteration; `ledger_msgs.pop(0)` shrank
  the list but the sum walked the remainder each time.

**Impact**: two more O(N²) sites; the synthesis loop also recomputed the
constant `len(system_text) + len(human_text)` each iteration.

**Action (done)**: Applied the same single-pass fix as Finding 5:
- `LedgerManager._trim_total_chars` (`ledger.py:204-220`): precompute
  per-message lengths, maintain a running total, advance a start index.
- `graph_wrapper.py` synthesis loop (`graph_wrapper.py:530-550`): precompute
  `fixed = len(system_text) + len(human_text)` and a list of per-message
  lengths; maintain a running ledger-text sum; advance a start index rather
  than re-summing.

---

## Consolidation design

After Findings 1–3, `ContextBundle` shrank from 16 fields to 4:

```python
class ContextBundle(BaseModel):
    active_goal: GoalNode | None = None
    goal_lineage: str = ""
    step_lineage: str = ""

    # RFC-624 Phase 4: cross-goal context
    prior_goals: list[PriorGoalSummary] = Field(default_factory=list)
```

`ProjectionEngine.project()` is now a thin read of DAG state (active goal,
lineage, prior goals) — no ledger iteration, no semantic triple-load, no
token/DAG observability recompute. The observability fields belong to
`LoopState` / checkpoint, not the projection bundle.

### Removed code

| Symbol | File | Reason |
|--------|------|--------|
| `ContextBundle.ledger_messages` | projection.py | Finding 1 — no consumer |
| `ContextBundle.cross_goal_ledger` | projection.py | Finding 1 — no consumer |
| `ContextBundle.total_tokens_used` | projection.py | Finding 1 — no consumer |
| `ContextBundle.goal_dag_summary` | projection.py | Finding 1 — no consumer |
| `ContextBundle.ledger_summary` | projection.py | Finding 1 — no consumer |
| `ContextBundle.project_instructions` | projection.py | Finding 2 — no consumer |
| `ContextBundle.agent_instructions` | projection.py | Finding 2 — no consumer |
| `ContextBundle.memory_instructions` | projection.py | Finding 2 — moved to call site |
| `ContextBundle.goal_progress` | projection.py | Finding 3 — no consumer |
| `ContextBundle.pending_steps` | projection.py | Finding 3 — no consumer |
| `ContextBundle.completed_steps` | projection.py | Finding 3 — no consumer |
| `ContextBundle.failed_steps` | projection.py | Finding 3 — no consumer |
| `ProjectionEngine._render_cross_goal_ledger` | projection.py | Finding 1/4 |
| `ProjectionEngine._render_goal_progress` | projection.py | Finding 3 |
| `ProjectionEngine._render_dag_summary` | projection.py | Finding 1 |
| `ProjectionConfig.max_ledger_messages` | projection.py | Finding 1/4 |
| `ProjectionConfig.max_project_instructions_chars` | projection.py | Finding 2 |
| `graph_wrapper._messages_text_len` | graph_wrapper.py | Finding 6b — orphaned after O(N) rewrite |

### Kept / refactored code

| Symbol | File | Change |
|--------|------|--------|
| `_trim_total_chars_front` | plan_ledger_projection.py:185-220 | Finding 5 — O(N) single pass |
| `LedgerManager._trim_total_chars` | ledger.py:204-220 | Finding 6 — O(N) single pass |
| synthesis budget loop | graph_wrapper.py:530-550 | Finding 6 — O(N) single pass |
| `_render_prior_goals` | projection.py:132-160 | keep (consumed via `prior_goals`) |
| `goal_lineage` / `step_lineage` | projection.py:99-120 | keep (consumed in user_message.py) |
| `SemanticLoader.load_memory` | semantic.py:35-37 | keep (called directly by graph_wrapper) |
| `SemanticLoader.load_project_instructions` | semantic.py:27-29 | keep — still called by `prompts/project_instructions.py`, `sloop/engine/strange_loop.py`, `sloop/engine/synthesis_projection.py`, `subagents/veritas/prompts.py` |
| `SemanticLoader.load_agent_instructions` | semantic.py:31-33 | keep — still called by `sloop/engine/strange_loop.py`, `sloop/engine/synthesis_projection.py` |

### Consumer updates

- `graph_wrapper.py:316-330`: `memory_instructions` field removed from
  `ContextBundle` (option a). `build_system_message` now constructs a
  `SemanticLoader` lazily from `state.workspace` and calls
  `semantic.load_memory()` directly, guarded by `kind not in ("assess", "gap")`.
- `graph_wrapper.py:701-702`: `context_bundle.active_goal.last_assessment`
  is the only consumer of `active_goal` — `active_goal` kept on the bundle.
- `user_message.py:368-400`: unchanged — reads `prior_goals`,
  `goal_lineage`, `step_lineage`, all retained.

---

## Implementation outcomes

All six findings were implemented in step CVN-03. The changes touch six files:

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/context/projection.py` | `ContextBundle` reduced 16→4 fields; `ProjectionConfig` reduced to `max_goals` + `max_lineage_chars`; `project()` body simplified to goal/lineage/prior-goals only; 3 helper methods removed |
| `packages/soothe/src/soothe/config/models.py` | Dead `ProjectionConfig` stub fields removed |
| `packages/soothe/src/soothe/sloop/prompts/graph_wrapper.py` | `memory_instructions` loaded directly via `SemanticLoader`; synthesis budget loop rewritten O(N); dead `_messages_text_len` function orphaned |
| `packages/soothe/src/soothe/sloop/prompts/plan_ledger_projection.py` | `_trim_total_chars_front` rewritten O(N) single pass |
| `packages/soothe/src/soothe/context/ledger.py` | `LedgerManager._trim_total_chars` rewritten O(N) single pass |
| `packages/soothe/tests/unit/context/test_projection.py` | Tests updated to reflect 4-field `ContextBundle`; dead-field assertions removed |

### Remaining cleanse items

1. **`graph_wrapper._messages_text_len`** (`graph_wrapper.py:128-132`): now
   orphaned — the synthesis budget loop no longer calls it. No other caller
   exists in the repo. Should be removed during the cleanse step (AGENTS.md §6).
2. **`SemanticLoader.load_project_instructions` / `load_agent_instructions`**:
   still called by `prompts/project_instructions.py`, `sloop/engine/strange_loop.py`,
   `sloop/engine/synthesis_projection.py`, and `subagents/veritas/prompts.py`.
   These are **not** orphaned — keep them.
3. **`ProjectionEngine.project()` `ledger` / `semantic` parameters**: now unused
   but retained for API stability. Documented as unused in docstrings. If a
   future breaking-change window opens, consider removing them.

---

## Action plan (ordered)

1. ✅ **Verify dead fields** (safety check). Repo-wide grep confirmed no
   external/test consumer for any removed field across `packages/`, `tests/`,
   and `docs/`.

2. ✅ **Remove dead ContextBundle fields + computation** (Findings 1–3).
   `projection.py` edited: field declarations, computation blocks, and
   `_render_cross_goal_ledger` / `_render_goal_progress` / `_render_dag_summary`
   methods removed. `ProjectionConfig` dropped `max_ledger_messages` and
   `max_project_instructions_chars`. `config/models.py` stub updated.

3. ✅ **Resolve memory_instructions** (Finding 2). Chose option (a): removed
   the field, updated `graph_wrapper.py:316-330` to call
   `SemanticLoader.load_memory()` directly.

4. ✅ **Fix O(n²) in `_trim_total_chars_front`** (Finding 5). Rewritten as
   single forward pass with precomputed per-message lengths and a running
   total. Output contract preserved.

5. ✅ **Fix O(n²) in `LedgerManager._trim_total_chars`** (Finding 6a).
   Rewritten with the same single-pass pattern.

6. ✅ **Fix O(n²) in synthesis budget loop** (Finding 6b). Rewritten to
   precompute `fixed` and per-message lengths, then find the cut index in one
   pass.

7. ⏳ **Cleanse** (per AGENTS.md §6). Remove orphaned
   `graph_wrapper._messages_text_len`. `SemanticLoader` methods are NOT
   orphaned — keep. Awaiting user confirmation per AGENTS.md §6 step 1.

8. ⏳ **Verify**. Run `./scripts/verify_finally.sh`. Fix all lint/format/test/
   vulture errors. Re-cleanse if fixes leave new dead code, then re-verify
   until green.

---

## Non-goals

- No new projection features (goal-report-pair projection is IG-744).
- No change to `LoopState` token/DAG observability (it stays authoritative).
- No split of `planner.py` or `projection.py` into multiple modules.
- No change to the RFC-214 ledger SoT contract; the O(N) fixes preserve the
  exact trimmed output.
- No change to `SemanticLoader` file resolution order.

---

## Verification

`./scripts/verify_finally.sh` — zero lint errors, all tests pass, no vulture
dead-code hits for removed symbols. *(Pending — step 8.)*

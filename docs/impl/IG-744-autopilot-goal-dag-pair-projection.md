# IG-744: Autopilot goal-DAG pair projection

**Created**: 2026-08-16  
**Status**: Draft  
**Related**: [RFC-222 §Goal-Report-Pair Projection](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-214](../specs/RFC-214-strangeloop-loop-message-surface.md) (loop message ledger),
[RFC-204 §1.3](../specs/RFC-204-autopilot-mode.md) (report commit),
[IG-726](IG-726-autopilot-report-commit-judgment.md) (report-commit judgment),
[IG-712](IG-712-domain-independent-goal-effects.md) (goal effects),
design draft [2026-08-16-autopilot-goal-dag-pair-projection-design.md](../drafts/2026-08-16-autopilot-goal-dag-pair-projection-design.md)

---

## Goal

Replace the worker's flat `_goal_text_with_bundle` prose-flattening (which
appends `## Prior effects` / `## Operator guidance` markdown to the goal
string) with a **goal-report-pair projection**: each transitive ancestor goal
becomes a `(user, ai)` message pair seeded into the StrangeLoop CE ledger as a
real multi-turn transcript before the current goal's user turn.

The executing LLM begins with a genuine conversation leading up to the
current ask, instead of a flattened prose blob that loses turn structure and
provenance.

---

## Background

`ContextProjector.project()` (`dispatch/projector.py`) reads each parent's
stored `GoalDispatchContextContribution`, merges + dedups into one
`GoalDispatchContextBundle`, ordered by recency. The worker's
`_goal_text_with_bundle` (`runner.py:470`) then flattens `prior_effects` and
`operator_guidance` into markdown sections appended to the goal description — a
single string passed as `goal=` to `run_with_progress`.

Three problems:

1. **Lost turn structure** — the model sees "a pile of prior effects," not
   "ancestor₁ asked X → reported Y; ancestor₂ asked Z → reported W."
2. **No provenance** — `prior_effects` are deduped by `ref`, dropping the
   parent→effect mapping.
3. **Flat compression** — `findings`/`prior_plan_steps` merged and top-K'd
   across all parents into bullets; poor transcript for the executing LLM.

RFC-222 §Goal-Report-Pair Projection formalizes the fix; this IG specifies the
implementation.

---

## Design rules (MUST)

1. **Additive.** `preamble_messages` is a new field on
   `GoalDispatchContextBundle`; the flat `prior_effects` /
   `prior_plan_steps` / `findings` fields stay. Structured consumers
   (verifier reasoner, consensus, worker effect checks) are unchanged.
2. **Pair shape.** One `(GoalReportUserTurn, GoalReportAITurn)` pair per
   ancestor. User half = `GoalNode.description`; AI half = the ancestor's
   committed goal report via the existing `build_goal_report` (outcome +
   summary + top findings + top effects).
3. **Full transitive walk.** BFS/DFS over `depends_on` ∪ `informs`,
   recursively, from the dispatched goal. A `visited: set[str]` guard prevents
   re-visiting on `informs` cycles.
4. **Topological order, goal last.** Ancestors sorted roots-first (a node
   never precedes its own `depends_on` parents); ties by `created_at` asc.
   The current goal directive is the final user message.
5. **Seed the CE ledger, not the goal string.** Pairs are committed to the
   CE ledger (phase `"preamble"`) after `state.bind_ce` and before
   `pump_graph`, so they surface through `loop_messages` (RFC-214 ledger SoT)
   automatically. `loop_messages` is rebuilt from the ledger on every access;
   a cache stuffed at dispatch time would be overwritten.
6. **`run_with_progress` gains a `preamble` param.** The CE ledger is created
   *inside* `run_with_progress` (`strange_loop.py:757`); the worker cannot
   pre-seed. It extracts pairs from the bundle and passes them via the new
   param; StrangeLoop commits them after `bind_ce`.
7. **No empty AI turns.** Skip an ancestor with no stored contribution (e.g.
   crashed before emitting one). `build_goal_report` guarantees a minimal
   `outcome + summary` on thin/crash terminals, so every projected AI turn is
   non-empty by construction.
8. **Cap is non-silent.** Stop at `len(preamble_messages) >= MAX_PREAMBLE_TURNS`
   (the fixed constant `12` in `goal_contracts.py`); log the drop count when
   the cap bites mid-subgraph; keep the most-recent ancestors by `updated_at`.
9. **Phase exclusion.** The `"preamble"` phase is added to the planning-phases
   exclusion set in `last_ledger_ai_content` (`sloop/utils/messages.py:107`)
   so preamble AI turns are not surfaced as final user-facing output in
   `ledger_direct` completion mode.

---

## Target flow

```text
ContextProjector.project(goal, all_goals)
  │ walk ancestors (transitive, topo sort, visited-guard)
  │ for each ancestor: build_goal_report(contribution) + node.description
  │ → preamble_messages = [user₀, ai₀, user₁, ai₁, …]
  ▼
GoalDispatchEnvelope.merged_context.preamble_messages
  │
  ▼ worker: _extract_preamble_pairs → LoopHumanMessage / LoopAIMessage (phase "preamble")
  │         _goal_directive_text → current goal directive (+ operator guidance)
  ▼
strange_loop.run_with_progress(goal=directive, preamble=pairs)
  │ … CE created (line 757) … state.bind_ce (line 974) …
  │ seed preamble pairs into CE ledger (phase "preamble")
  │ then record current goal directive as final user message (phase "intake")
  ▼
LLM sees a real multi-turn transcript
```

---

## Package / file changes

| Package | File | Change |
|---|---|---|
| `soothe` | `goal_contracts.py` | Add `GoalReportUserTurn`, `GoalReportAITurn`, `MAX_PREAMBLE_TURNS`; add `preamble_messages` field + `_enforce_bounds` cap on `GoalDispatchContextBundle` |
| `soothe-autopilot` | `dispatch/projector.py` | Add ancestor walk + topo sort + pair builder; populate `preamble_messages`; cap at `MAX_PREAMBLE_TURNS` |
| `soothe-autopilot` | `runner.py` | Split `_goal_text_with_bundle` → `_extract_preamble_pairs` + `_goal_directive_text`; pass `preamble=` to `run_with_progress` |
| `soothe` | `sloop/engine/strange_loop.py` | Add `preamble` param to `run_with_progress`; seed ledger after `bind_ce`, before `pump_graph` |
| `soothe` | `sloop/utils/messages.py` | Add `"preamble"` to planning-phases exclusion set in `last_ledger_ai_content` |

---

## Core types

### `goal_contracts.py`

```python
class GoalReportUserTurn(BaseModel):
    """The 'user' half of a projected ancestor pair — the ancestor's directive."""
    goal_id_origin: str
    content: str = Field(max_length=2000)


class GoalReportAITurn(BaseModel):
    """The 'ai' half of a projected ancestor pair — the ancestor's goal report."""
    goal_id_origin: str
    outcome: str            # completed / failed / needs_replan
    summary: str = Field(max_length=2000)
    findings: list[str] = Field(default_factory=list, max_length=8)
    effects: list[GoalEffect] = Field(default_factory=list, max_length=8)
```

On `GoalDispatchContextBundle`:

```python
preamble_messages: list[GoalReportUserTurn | GoalReportAITurn] = Field(
    default_factory=list,
    description=(
        "Projected ancestor (user, ai) pairs in topological order. "
        "Flattened: [user₀, ai₀, user₁, ai₁, …]. Seeded into the StrangeLoop "
        "CE ledger as a preamble transcript before the current goal turn."
    ),
)
```

`_enforce_bounds` gains:
```python
if len(self.preamble_messages) > MAX_PREAMBLE_TURNS:
    raise ValueError(...)
```
`MAX_PREAMBLE_TURNS` (default `12` = 6 pairs) is a public constant in
`goal_contracts.py`, shared with the projector so both agree on the bound.
It is not a config knob — the projection is always on when ancestors exist.

---

## Projector — `dispatch/projector.py`

`ContextProjector.project()` gains a branch that builds `preamble_messages`
alongside the existing merged fields (which remain unchanged). New private
helpers:

- `_collect_ancestors(goal, all_goals) -> list[GoalNode]` — recursive walk over
  `depends_on` ∪ `informs` with a `visited` set; returns ancestors in
  topological order (roots first), ties by `created_at` asc.
- `_build_preamble_pairs(ancestors, contributions) -> list[GoalReportUserTurn | GoalReportAITurn]`
  — for each ancestor with a stored contribution, emit a
  `GoalReportUserTurn(content=node.description)` +
  `GoalReportAITurn(...)` built via `build_goal_report(outcome=…, summary=…,
  findings=…, effects=…)` from `report_projection.py` (reuse). Skip ancestors
  with no contribution. Cap at `MAX_PREAMBLE_TURNS`; log drops.

The walk needs each ancestor's `GoalNode.description` (already on the node,
not projected today) plus its stored `GoalDispatchContextContribution`
(existing `_store.get_many`). Both are read-only on the projector.

### Topological sort (v1)

A node must never precede its own `depends_on` parents. A simple Kahn-style
sort over the ancestor subset, with `created_at` as the stable tiebreaker,
suffices for v1. The scheduler already guarantees acyclic `depends_on`; the
`visited` guard handles `informs` cycles defensively.

---

## Worker — `runner.py`

### Split `_goal_text_with_bundle` (line 470)

- **`_extract_preamble_pairs(job) -> list[BaseMessage]`** (new): reads
  `job.merged_context.preamble_messages`, returns a flattened
  `list[BaseMessage]` in pair order `[H₀, A₀, H₁, A₁, …]`. Each
  `GoalReportUserTurn` → `LoopHumanMessage(phase="preamble")`; each
  `GoalReportAITurn` → `LoopAIMessage(phase="preamble")`. Flattened (not
  tuple-list) because `run_with_progress` consumes a flat message stream.
- **`_goal_directive_text(job) -> str`** (new, replaces the
  prior-effects/guidance flattening): returns the goal description with
  operator guidance appended as a short structured block on the *current*
  goal turn (not on ancestor turns). Prior-effects flattening is removed from
  this path — the pairs carry that context now.

### `_run_autopilot_job` call site

```python
goal_text = _goal_directive_text(job)
preamble = _extract_preamble_pairs(job)
async for event_type, event_data in strange_loop.run_with_progress(
    goal=goal_text,
    preamble=preamble,           # new
    thread_id=tid,
    workspace=workspace,
    max_iterations=max_iterations,
    loop_id=tid,
    intent=preclassified_intent,
    routing_classification=routing_classification,
    shared_pool=shared_pool,
    clarification_policy=clarification_policy,
):
    …
```

When `preamble` is empty (no ancestors with a stored contribution),
behavior is identical to today.

---

## `run_with_progress` seam — `sloop/engine/strange_loop.py`

New optional parameter:

```python
async def run_with_progress(
    self,
    goal: str,
    thread_id: str,
    workspace: str | None = None,
    max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS,
    loop_id: str | None = None,
    intent: Any | None = None,
    routing_classification: Any | None = None,
    intent_classifier: Any | None = None,
    preferred_subagent: str | None = None,
    shared_pool: Any | None = None,
    clarification_policy: Any | None = None,
    clarification_answer: bool = False,
    clarification_answers: list[str] | None = None,
    resume_interrupted: bool = False,
    goal_trace: Any | None = None,
    preamble: list[BaseMessage] | None = None,   # NEW
) -> AsyncGenerator[tuple[str, Any], None]:
```

Seeding happens **after** `state.bind_ce(ce_instance, ce_goal.id)` (line 974)
and **before** `pump_graph` (line 1021):

```python
if preamble:
    for msg in preamble:
        await ce_instance.record_message(msg, phase="preamble")
    # record the current goal directive as the final user message
    await ce_instance.record_message(
        LoopHumanMessage(
            content=execution_goal,
            phase="intake",
            thread_id=main_thread_id,
            goal_summary=execution_goal[:200],
        ),
        "intake",
    )
else:
    # existing path: goal recorded as first user message by the graph
    …
```

The preamble messages join the same CE ledger that `loop_messages` is rebuilt
from (`_build_loop_messages_from_ce_sync`, `schemas.py:1408`), so the existing
ledger→LoopState reflection picks them up with no extra wiring.

---

## Phase exclusion — `sloop/utils/messages.py`

`last_ledger_ai_content` (line 90) maintains a planning-phases exclusion set
(line 107). Add `"preamble"` so preamble AI turns are not surfaced as final
user-facing output in `ledger_direct` completion mode:

```python
planning_phases = {
    "evaluate",
    "assess",
    "plan_assess",
    "generate_plan",
    "plan_generate",
    "analyze_gaps",
    "plan_gap_analysis",
    "intake",
    "intent_classify",
    "continuation",
    "preamble",   # NEW — ancestor goal-report pairs are context, not output
}
```

---

## Error handling / fallback

| Case | Handling |
|---|---|
| Empty ancestor set / no contributions | `preamble_messages = []`; worker seeds nothing; behavior == today |
| Projector failure | Empty bundle (existing fallback in `_build_merged_context`, `service.py:1490`) |
| Ancestor with no stored contribution | Skip its pair; transcript omits it cleanly (no empty AI turns) |
| `build_goal_report` on thin/crash terminal | Minimal `outcome + summary` by construction; AI turn non-empty |
| Cap bites mid-subgraph | Log drop count; keep most-recent ancestors by `updated_at` |
| `preamble` param `None`/empty | `run_with_progress` takes the existing first-user-message path (no ancestors to project) |

---

## Testing

### Projector unit tests (`tests/unit/core/autopilot/`)
- Topological ordering: a 3-deep chain projects as root→child→grandchild pairs.
- Transitive vs direct: a goal with a grandparent asserts the grandparent pair
  is present (not just direct parents).
- `visited` cycle guard: an `informs` cycle does not loop infinitely.
- Cap enforcement: patch `MAX_PREAMBLE_TURNS` down to 4 with 5 ancestors →
  exactly 4 messages (2 pairs), oldest dropped.
- Missing-contribution skip: an ancestor with no stored contribution is
  omitted; its descendants' pairs still appear.
- Recency tie-break within a topological level: equal-rank ancestors ordered
  by `updated_at` desc.

### Contract tests (`tests/unit/.../goal_contracts_test.py`)
- `preamble_messages` bounds: over-cap raises `ValueError` in `_enforce_bounds`.
- Serialization round-trip: `model_dump(mode="json")` → reconstruct preserves
  pair order and types.

### Worker integration test (`tests/integration/autopilot/`)
- Preamble pairs land in the CE ledger (phase `"preamble"`) **before** the
  goal's `phase="intake"` user message, in order.
- `state.loop_messages` (via `get_loop_messages()`) returns the preamble
  pairs followed by the goal turn.
- `last_ledger_ai_content` does **not** surface a preamble AI turn as the
  final response in `ledger_direct` mode.

### `run_with_progress` seam test
- `preamble=None` → identical to today (no extra messages in ledger).
- `preamble=[H, A]` → ledger has `[H(preamble), A(preamble), goal(intake)]`
  before the graph runs.

---

## Migration / compatibility

### Breaking changes

None. `preamble_messages` defaults to `[]`; `run_with_progress(preamble=None)`
is the existing path. All existing callers (solo mode, clarification resume)
pass no `preamble` and behave identically.

### Rollback

Revert the commits. There is no runtime toggle — the projection is always on
when ancestors exist, capped by `MAX_PREAMBLE_TURNS`.

---

## Implementation order

1. Contract types + `MAX_PREAMBLE_TURNS` + bundle field (with `_enforce_bounds`).
2. Projector ancestor walk + pair builder (reuse `build_goal_report`).
3. `run_with_progress` `preamble` param + ledger seeding.
4. Worker `_extract_preamble_pairs` / `_goal_directive_text` split.
5. Phase exclusion in `last_ledger_ai_content`.
6. Tests (unit → contract → integration).

---

## Appendix A: RFC requirement mapping

| RFC-222 requirement | IG section |
|---|---|
| `preamble_messages` field on bundle, additive | Core types; Design rule 1 |
| `GoalReportUserTurn` / `GoalReportAITurn` types | Core types |
| Full transitive ancestor walk + `visited` guard | Projector; Design rules 3, 6 |
| Topological order, current goal last | Projector; Design rule 4 |
| Reuse `build_goal_report` for AI half | Projector; Design rule 2 |
| Worker seeds CE ledger via `run_with_progress(preamble=)` | Worker; `run_with_progress` seam; Design rules 5, 6 |
| `"preamble"` phase excluded from `last_ledger_ai_content` | Phase exclusion; Design rule 9 |
| `MAX_PREAMBLE_TURNS` constant, default 12 (not a config knob) | Core types; Design rule 8 |

---

## Appendix B: Open questions (pre-implementation)

1. **Operator guidance placement.** Placed on the current (final) goal turn,
   not ancestor turns. Confirm before implementation.
2. **Cap default.** `12` (6 pairs) is a guess; flagged for review after first
   eval run.

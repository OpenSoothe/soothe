# Design Draft: Autopilot Goal-DAG Pair Projection for StrangeLoop Preamble

**Status**: Formalized → [RFC-222 §Goal-Report-Pair Projection](../specs/RFC-222-autopilot-goal-engine-architecture.md)
(revision 2026-08-16). Implementation:
[IG-744](../impl/IG-744-autopilot-goal-dag-pair-projection.md) (Draft).  
**Date**: 2026-08-16  

> **Deviation from this draft (implemented 2026-08-16):** The
> `max_preamble_turns` config knob and its `0` opt-out / rollback path were
> **dropped** during implementation. The projection is always on when
> ancestors exist, bounded by a fixed public constant `MAX_PREAMBLE_TURNS`
> (= 12 = 6 pairs) in `goal_contracts.py`, enforced by both the projector
> and `GoalDispatchContextBundle._enforce_bounds`. The RFC and IG are
> authoritative; references to `max_preamble_turns` / opt-out below are
> historical.

**Scope**: Optimize the goal-DAG → StrangeLoop context projection. Today the
daemon's `ContextProjector` merges parents' `GoalDispatchContextContribution`
entries into one flat `GoalDispatchContextBundle`, and the worker flattens
`prior_effects` / `operator_guidance` into markdown sections appended to the
goal string. Replace that flattening with a **goal-report-pair projection**:
each transitive ancestor goal becomes a `(user, ai)` message pair — the user
half is the ancestor's directive, the AI half is its committed goal report —
seeded into the StrangeLoop CE ledger as a real multi-turn transcript before
the current goal's user turn.  
**Related**: [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)
(goal dispatch contract, `ContextProjector`),
[RFC-214](../specs/RFC-214-strangeloop-loop-message-surface.md) (loop message
ledger), [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-228](../specs/RFC-228-autopilot-job-ipc.md) (operator guidance),
[IG-726](../impl/IG-726-goal-report-projection.md) /
[IG-712](../impl/IG-712-goal-effects.md) (goal report + effects SoT).

---

## Problem

When Autopilot dispatches a goal that depends on prior goals, the worker's
`_goal_text_with_bundle` (`runner.py:470`) builds the StrangeLoop input as a
**single string**:

```
<goal_description>

## Operator guidance
- <guidance line 1>
- <guidance line 2>

## Prior effects
- [decide] <ref>: <statement>
- [create] <ref>: <statement>
```

The LLM therefore sees ancestor context as **prose bullets bolted onto one user
message**. Three consequences:

1. **Lost turn structure.** The model cannot tell which ancestor was *asked*
   what, versus which *reported* what. Every dependency reads as an undifferentiated
   effect list, so the model reasons about "a pile of prior effects" rather than
   "a sequence of completed sub-goals, each with its own directive and report."
2. **No provenance framing.** `prior_effects` are deduped by `ref` and ordered
   by parent recency, dropping the parent→effect mapping that would let the
   model attribute claims to the goal that produced them.
3. **Flat compression.** `findings` and `prior_plan_steps` are merged and
   top-K'd across all parents into bullet lists — useful for verifiers, but a
   poor transcript for the executing LLM, which benefits from "ancestor₁ asked
   X → ancestor₁ reported Y; ancestor₂ asked Z → ancestor₂ reported W; now
   execute the current goal."

The DAG is the natural unit of decomposition, but the projection erases it.

---

## Goal

Project each dependent (ancestor) goal as a real `(user → ai)` turn in the
StrangeLoop CE ledger, so the executing LLM begins with a genuine multi-turn
transcript leading up to the current goal directive. Concretely:

1. **Pair shape**: one `(user, ai)` pair per ancestor goal. The user half is the
   ancestor's directive (its `GoalNode.description`); the AI half is its committed
   goal report (outcome + summary + top findings + top effects), built by the
   existing `build_goal_report` path. *(Confirmed: goal-report pair, not step-level.)*
2. **Ordering**: pairs in **topological order** (oldest roots first, newest parent
   last), with the current goal directive as the **final user message**. The
   transcript reads like a real conversation leading up to the current ask.
   *(Confirmed: topo order, goal last.)*
3. **Ancestor scope**: walk the **full transitive** subgraph
   (`depends_on` hard + `informs` soft, recursively), not just direct parents.
   Bounded by a new `max_preamble_turns` cap. *(Confirmed: full transitive chain.)*
4. **Contract home**: a new `preamble_messages` field on
   `GoalDispatchContextBundle` carries the projected pairs. The flat fields
   (`prior_effects`, `prior_plan_steps`, `findings`) stay — additive, not
   replacement. *(Confirmed: bundle field, additive.)*

---

## Non-goals (YAGNI)

- **No per-step expansion.** A goal-report pair is one turn per dependency;
  we do not explode each ancestor into per-plan-step pairs. Step-level fidelity
  is bounded by the existing step caps and is not needed for the LLM transcript.
- **No replacement of flat bundle fields.** Verifiers (`verifier_reasoner`,
  `consensus`) and the worker's structured-effect checks keep reading
  `prior_effects` / `findings` as today. The new field is an *additional*
  projection for the LLM transcript path only.
- **No DAG or scheduler changes.** The projector reads the DAG; it does not
  mutate it. The scheduler's acyclicity guarantee on `depends_on` is reused
  unchanged.
- **No per-goal report persistence changes.** `build_goal_report`
  (`report_projection.py`) and the CE `commit_goal_report` path are reused as-is;
  the AI half of each pair is the same report that already gets committed.

---

## Architecture

### Current projection path

```
Daemon (DAG owner)                              Worker (StrangeLoop)
─────────────────────                          ────────────────────
GoalNode {depends_on, informs}
  │
  ▼  ContextProjector.project()
  │  reads parents' stored
  │  GoalDispatchContextContribution
  │  → merges + dedups → ONE                  ──►  GoalDispatchEnvelope.merged_context
  │  GoalDispatchContextBundle                       (GoalDispatchContextBundle:
  │  (bounded, ordered by recency)                    prior_plan_steps, prior_effects,
  │                                                   findings, operator_guidance, …)
  │                                                            │
  │                                                            ▼  _goal_text_with_bundle(job)
  │                                                     goal_description + "\n\n## Prior effects\n…"
  │                                                     + "\n\n## Operator guidance\n…"
  │                                                            │  (a SINGLE STRING)
  │                                                            ▼
  │                                                     strange_loop.run_with_progress(goal=goal_text)
  │                                                            │
  │                                                            ▼  state.goal → first user msg
```

### Optimized projection path

```
ContextProjector.project(goal, all_goals)
  │  walk ancestors (transitive, topo sort, visited-guard)
  │  for each ancestor: build_goal_report(contribution) + node.description
  │  → preamble_messages = [user₀, ai₀, user₁, ai₁, …]
  ▼
GoalDispatchEnvelope.merged_context.preamble_messages
  │
  ▼  worker: extract pairs → LoopHumanMessage / LoopAIMessage
  │  pass as preamble=… to run_with_progress
  ▼
strange_loop.run_with_progress(goal=directive_text, preamble=pairs)
  │  … CE created, state.bind_ce() at line 974 …
  │  seed preamble pairs into CE ledger (phase="preamble")
  │  then record the current goal directive as the final user message
  ▼
LLM sees a real multi-turn transcript, not a flattened blob
```

### Critical correction vs. the initial sketch

The initial sketch assumed the worker could pre-seed the CE ledger before
calling `run_with_progress`, so no signature change would be needed. **That is
wrong.** The loop-scoped `ContextEngine` is created *inside*
`run_with_progress` (`strange_loop.py:757`), and `state.bind_ce(ce_instance,
ce_goal.id)` happens at `strange_loop.py:974` — both after the worker hands off.
The worker has no CE handle at dispatch time.

Consequence: the preamble pairs still live on the bundle (the SoT for
hydration), but the worker must **extract** them and pass them into
`run_with_progress` as a new `preamble` parameter. StrangeLoop seeds the ledger
**after** `bind_ce` and **before** `pump_graph`. This is a small, additive
signature change — flagged explicitly so it is not a surprise during
implementation.

---

## Components

### 1. New contract types — `goal_contracts.py` (additive, bounded)

```python
class GoalReportUserTurn(BaseModel):
    """The 'user' half of a projected ancestor pair — the ancestor's directive."""

    goal_id_origin: str
    content: str = Field(max_length=2000, description="Ancestor goal description/directive")


class GoalReportAITurn(BaseModel):
    """The 'ai' half of a projected ancestor pair — the ancestor's goal report."""

    goal_id_origin: str
    outcome: str  # completed / failed / needs_replan
    summary: str = Field(max_length=2000)
    findings: list[str] = Field(default_factory=list, max_length=8)
    effects: list[GoalEffect] = Field(default_factory=list, max_length=8)
```

Both are deliberately small and serializable (they cross the IPC boundary on the
bundle). `max_length=8` on findings/effects mirrors the per-pair cap; the
overall turn count is bounded separately (below).

### 2. Bundle field — `GoalDispatchContextBundle`

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

Hard cap enforced in `_enforce_bounds`:
`len(preamble_messages) <= max_preamble_turns` (the cap counts individual
messages, so 6 pairs = 12). Coexists with `prior_effects` /
`prior_plan_steps` / `findings`; those stay for structured consumers.

### 3. Config — `ContextProjectionConfig` (`config/models.py`)

```python
max_preamble_turns: int = Field(
    default=12, ge=0, le=60,
    description=(
        "Max messages (user+ai) projected into preamble_messages. "
        "0 disables pair projection (falls back to today's flat goal text). "
        "Default 12 = 6 ancestor pairs."
    ),
)
```

`0` is a clean opt-out: the projector emits `preamble_messages=[]` and the
worker falls back to the existing `_goal_text_with_bundle` path unchanged. This
is the safety valve for rollback.

### 4. Projector extension — `dispatch/projector.py`

`ContextProjector.project()` gains a new branch that builds
`preamble_messages` alongside the existing merged fields:

- **Ancestor walk**: BFS/DFS over `depends_on` (hard) + `informs` (soft),
  recursively, from the dispatched goal. A `visited: set[str]` guard prevents
  re-visiting even if `informs` soft-links form a cycle (the scheduler
  guarantees acyclic `depends_on`, but `informs` is not policed — the guard is
  cheap insurance).
- **Topological sort**: ancestors ordered roots-first. The walk collects all
  ancestors, then sorts so that a node never appears before its own
  `depends_on` parents. Ties broken by `created_at` (older first).
- **Per-ancestor pair**: fetch the ancestor's stored
  `GoalDispatchContextContribution` (existing `_store.get_many`) AND read its
  `GoalNode.description` (needed for the user half — already on the node, not
  projected today).
  - **Skip ancestors with no stored contribution** (e.g. crashed before
    emitting one) rather than emit an empty AI turn — the transcript omits
    that ancestor cleanly.
  - Build the AI half via `build_goal_report(outcome=…, summary=…,
    findings=…, effects=…)` from `report_projection.py` — reuse, not new code.
    `build_goal_report` already guarantees a minimal `outcome + summary` on
    thin/crash terminals, so every projected AI turn is non-empty.
- **Cap**: stop once `len(preamble_messages) >= max_preamble_turns`. When the
  cap bites mid-subgraph, log it (no silent truncation) and prefer the
  most-recently-completed ancestors by `updated_at` (drop the oldest pairs).
- `project()` returns the bundle with both `preamble_messages` and the
  existing merged fields populated.

### 5. Worker extraction — `runner.py`

`_goal_text_with_bundle` is split:

- **`_extract_preamble_pairs(job)`** (new): reads
  `job.merged_context.preamble_messages`, returns a flattened
  `list[BaseMessage]` in pair order `[H₀, A₀, H₁, A₁, …]`. Each
  `GoalReportUserTurn` → `LoopHumanMessage(phase="preamble")`; each
  `GoalReportAITurn` → `LoopAIMessage(phase="preamble")`. Flattened (not
  tuple-list) because `run_with_progress` consumes a flat message stream.
- **`_goal_directive_text(job)`** (new, replaces the prior-effects/guidance
  flattening): returns just the goal description, with operator guidance
  appended as a short structured block on the *current* goal turn (not on
  ancestor turns). Prior-effects flattening is removed from this path — the
  pairs carry that context now.

The `_run_autopilot_job` call site becomes:

```python
goal_text = _goal_directive_text(job)
preamble = _extract_preamble_pairs(job)
async for event_type, event_data in strange_loop.run_with_progress(
    goal=goal_text,
    preamble=preamble,           # new
    thread_id=tid,
    …
):
```

When `preamble` is empty, behavior is identical to today.

### 6. `run_with_progress` seam — `strange_loop.py`

New optional parameter:

```python
async def run_with_progress(
    self,
    goal: str,
    thread_id: str,
    …,
    preamble: list[BaseMessage] | None = None,  # NEW
) -> AsyncGenerator[tuple[str, Any], None]:
```

Seeding happens **after** `state.bind_ce(ce_instance, ce_goal.id)` (line 974) and
**before** `pump_graph` (line 1021):

```python
if preamble:
    for msg in preamble:
        await ce_instance.record_message(msg, phase="preamble")
    # record the current goal directive as the final user message
    await ce_instance.record_message(
        LoopHumanMessage(content=execution_goal, phase="intake",
                         thread_id=main_thread_id, goal_summary=…),
        "intake",
    )
else:
    # existing path: goal recorded as first user message by the graph
    …
```

The preamble messages join the same CE ledger that `loop_messages` is rebuilt
from (`_build_loop_messages_from_ce_sync`, `schemas.py:1408`), so the existing
ledger→LoopState reflection picks them up with no extra wiring. The new
`"preamble"` phase is added to the planning-phases exclusion set in
`last_ledger_ai_content` (`messages.py:107`) so preamble AI turns are not
surfaced as final user-facing output in `ledger_direct` completion mode.

### 7. `ContextProjectionConfig` plumbing

`ContextProjectionConfig.max_preamble_turns` is read by the projector (same
config object already passed to `ContextProjector.__init__`). No new injection
points; the projector already has `self._config`.

---

## Error handling / fallback

- **Empty ancestor set or no contributions** → `preamble_messages = []`; worker
  seeds nothing; behavior == today.
- **Projector failure** → empty bundle (existing fallback in
  `_build_merged_context`, `service.py:1490`).
- **Ancestor with no stored contribution** (crashed before emitting one) →
  skip its pair; the transcript omits that ancestor. No empty AI turns.
- **`build_goal_report` on a thin/crash terminal** → still produces minimal
  `outcome + summary`, so every projected AI turn is non-empty by construction.
- **Cap bites mid-subgraph** → log the drop count, keep most-recent pairs.
  No silent truncation.
- **`preamble` param `None` or empty** → `run_with_progress` takes the existing
  first-user-message path unchanged. This is also the rollback / opt-out path
  when `max_preamble_turns == 0`.

---

## Testing

### Projector unit tests (`tests/unit/core/autopilot/`)
- Topological ordering: a 3-deep chain projects as root→child→grandchild pairs,
  in that order.
- Transitive vs direct: a goal with a grandparent asserts the grandparent pair
  is present (not just direct parents).
- `visited` cycle guard: an `informs` cycle does not loop infinitely.
- Cap enforcement: with `max_preamble_turns=4` and 5 ancestors, exactly 4
  messages (2 pairs) survive, oldest dropped.
- Missing-contribution skip: an ancestor with no stored contribution is
  omitted; its descendants' pairs still appear.
- Recency tie-break within a topological level: equal-rank ancestors ordered
  by `updated_at` desc.

### Contract tests (`tests/unit/.../goal_contracts_test.py`)
- `preamble_messages` bounds: over-cap raises `ValueError` in `_enforce_bounds`.
- Serialization round-trip: `model_dump(mode="json")` → reconstruct preserves
  pair order and types.

### Worker integration test (`tests/integration/autopilot/`)
- Assert preamble pairs land in the CE ledger (phase `"preamble"`) **before**
  the goal's `phase="intake"` user message, in order.
- Assert `state.loop_messages` (via `get_loop_messages()`) returns the
  preamble pairs followed by the goal turn.
- Assert `last_ledger_ai_content` does **not** surface a preamble AI turn as
  the final response in `ledger_direct` mode.

### `run_with_progress` seam test
- `preamble=None` → identical to today (no extra messages in ledger).
- `preamble=[H, A]` → ledger has `[H(preamble), A(preamble), goal(intake)]`
  before the graph runs.

---

## Open questions (to resolve before RFC formalization)

1. **Operator guidance on the current goal turn.** The draft places operator
   guidance as a structured block on the *current* (final) user message, not
   on ancestor turns. Confirm this is preferred over a separate system-ish
   message. *(Initial assumption: current-goal turn.)*
2. **Phase name.** `"preamble"` is the working phase tag. Is there a canonical
   phase-name convention to follow (the ledger already uses `intake`,
   `execute_step`, `goal_completion`, etc.)? A distinct phase is needed so
   `last_ledger_ai_content` and other phase filters can exclude preamble.
3. **Cap default.** `max_preamble_turns=12` (6 pairs) is a guess. Should it
   scale with `max_findings`/`max_effects`, or stay independent? Independent is
   simpler; flagged for review.

---

## Implementation order (for the downstream IG)

1. Contract types + bundle field + config field (with `_enforce_bounds`).
2. Projector ancestor walk + pair builder (reuse `build_goal_report`).
3. `run_with_progress` `preamble` param + ledger seeding.
4. Worker `_extract_preamble_pairs` / `_goal_directive_text` split.
5. Phase exclusion in `last_ledger_ai_content`.
6. Tests (unit → contract → integration).
7. Opt-out validation: `max_preamble_turns=0` recovers today's behavior exactly.

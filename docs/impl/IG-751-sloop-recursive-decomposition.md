# IG-751: Sloop Recursive Step Decomposition

> Implementation guide for [RFC-904](../specs/RFC-904-sloop-recursive-decomposition.md).
> Status: **In progress** (P0–P3 done; P4 B-lazy + LLM reconcile next).
> Design draft (archived): `docs/archive/drafts/2026-08-19-sloop-recursive-decomposition-design.md`
>
> **Revision (2026-08-22):** The forced `DECOMPOSE_FIRST_HINT` directive has been
> removed. Steps classified `complex` no longer get a "decompose before working"
> instruction — they default to finishing in-thread, splitting only with concrete
> evidence. Over-cap proposals are now rejected (not silently truncated) per
> RFC-904 §Branch caps. Budgets tightened: `max_depth` 5→3, `max_steps` 50→30,
> `max_branch_root` code default 10→5.

---

## 1. Executive Summary

Replace StrangeLoop’s plan/eval/execute station spine with recursive
do-or-decompose driven by CE StepDAG ownership:

1. Keep intake **pass1** (chitchat vs task); remove **pass2** scope routing.
2. Goal = root `StepNode`; threads complete or call executor-bound
   `decompose_task`.
3. CE reconciles proposals; completions land immediately.
4. B-lazy failure via `replacement_of` nodes; coverage Eval is [RFC-905](../specs/RFC-905-sloop-eval-thread.md) (not GapResult new-root).

Decomposition is **always on** for StrangeLoop step THREADS. Budgets:
`agent.loop.decompose.*` (no `enabled` gate).

**Package:** `soothe` (context, sloop, config). Autopilot goal DAG unchanged.

---

## 2. Coding Plan (phases)

| Phase | Scope | Exit criteria |
|-------|--------|---------------|
| **P0** | Schema + types + config + tree_green helpers + unit tests | Flag off; no behavior change |
| **P1** | Executor-bound `decompose_task`; THREAD envelope + `write_todos` override; proposal queue | Tool enqueues proposal; no CE commit from tool |
| **P2** | Deterministic RECONCILE behind flag | Proposals → children claimable |
| **P3** | Graph cutover (DISPATCH/RECONCILE/ROOT_EVAL); pass2 bypass | Flag on path works for one-shot + simple decompose |
| **P4** | Conflict LLM reconcile; B-lazy. ROOT_EVAL GapResult **withdrawn** (RFC-905 Eval thread is a follow-on IG) | Failure paths green; Eval not in this IG |
| **P5** | Delete pass2 + dead plan-generate; docs sync | Verify green; flag default still off or on per release decision |

---

## 3. P0 — Schema & Config (this slice)

### 3.1 `soothe.context.models`

- Extend `StepStatus`: add `decomposed`, `superseded`.
- Extend `StepNode`:
  - `parent_step_id: str | None`
  - `secondary_parent_step_ids: list[str]`
  - `replacement_of: str | None`
  - `full_description: str | None`
  - `expected_output: str | None`
  - `execution_hint: Literal["tool","subagent","remote","auto"] | None`
  - `recompose_count: int = 0`
  - `kind: str | None` (optional; preserve ask_user)
- `StepDAG` helpers:
  - `mark_decomposed(step_id)`
  - `mark_superseded(step_id)`
  - `tree_green() -> bool` (RFC-904 predicate)
  - `lineage_depth(step_id) -> int`
- `ready_steps()` remains pending-only (no change needed for new statuses).

### 3.2 Proposal types

New module `soothe.context.decomposition` (or `soothe.sloop.decompose.types`):

```python
class ProposedSubtask(BaseModel): ...
class DecompositionProposal(BaseModel):
    parent_step_id: str
    subtasks: list[ProposedSubtask]
    wave_seq: int = 0
```

### 3.3 Config

Under `StrangeLoopConfig`:

```yaml
agent.loop.decompose:
  enabled: false
  max_depth: 5
  max_steps: 50
  max_recompose: 2
  max_waves: 10
  max_branch_root: 5
  max_branch_inner: 3
  reconcile_model_role: fast  # verifier-tier lean
```

Sync: `config/templates/soothe.yml`, `config/develop/soothe.yml`.

### 3.4 Tests

`packages/soothe/tests/unit/context/test_step_dag.py` (+ new
`test_decomposition_types.py`): statuses, tree_green, lineage fields,
proposal validation.

---

## 4. P1 — Tool & prompts (done)

- Bind `decompose_task` in executor on every step THREAD.
- Proposal sink on `LoopRuntimeContext` / `executor.decompose_proposals`.
- THREAD system: `THREAD_POLICY_SYSTEM_ADDENDUM` (finish vs split + write_todos);
  user envelope instance-only; override TodoListMiddleware copy.
- Do **not** implement nano middleware for decompose.

## 4b. P2 — Deterministic reconcile (done)

Module: `soothe.sloop.decompose.reconcile`

- `plan_commit_from_proposals` — exact description dedup, branch/depth/step
  budgets, composite IDs (`PLAN-01`…), in-batch `depends_on_local`, cycle edge drop.
- `reconcile_proposals_deterministic` — `ce.add_steps` + `mark_decomposed` on parents.
- `drain_executor_proposals` — clear executor queue for the future RECONCILE node.
- LLM conflict reconcile remains **P4**.

Tests: `packages/soothe/tests/unit/core/loop/decompose/test_reconcile.py`.

## 4c. P3 — Graph cutover (done)

- Live graph: `INTAKE → ENTER_LOOP → DISPATCH ⇄ EXECUTE → RECORD_PROGRESS →
  RECONCILE → ROOT_EVAL → FINALIZE` (+ `AWAIT_USER` / `DELEGATE`).
- Pass 2 classifier removed; Pass 1 tasks map to compatibility `complex`.
- Decomposition always on (no `enabled` flag); budgets under `agent.loop.decompose.*`.
- Legacy plan stations remain as importable modules for isolated unit tests;
  they are not on the compiled graph.

## 4d. P4 outline (next)

- Conflict LLM reconcile; B-lazy. ROOT_EVAL GapResult re-dispatch is **withdrawn**
  ([RFC-905](../specs/RFC-905-sloop-eval-thread.md)); do not implement GapResult
  new-root in this IG.

---

## 5. Non-Goals (this IG)

- Goal-directive CE `"decompose"`
- Merging autopilot `apply_llm_subgoals`
- Full topology cutover before P0–P2 solid

---

## 6. Verification

After each phase: `./scripts/verify_finally.sh`. Fix until green.
Ask user before cleansing related legacy after substantial slices.

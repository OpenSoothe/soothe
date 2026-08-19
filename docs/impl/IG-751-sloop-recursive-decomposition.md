# IG-751: Sloop Recursive Step Decomposition

> Implementation guide for [RFC-904](../specs/RFC-904-sloop-recursive-decomposition.md).
> Status: **In progress** (P0 started).
> Design draft (archived): `docs/archive/drafts/2026-08-19-sloop-recursive-decomposition-design.md`

---

## 1. Executive Summary

Replace StrangeLoop’s plan/eval/execute station spine with recursive
do-or-decompose driven by CE StepDAG ownership:

1. Keep intake **pass1** (chitchat vs task); remove **pass2** scope routing.
2. Goal = root `StepNode`; threads complete or call executor-bound
   `decompose_task`.
3. CE reconciles proposals; completions land immediately.
4. B-lazy failure via `replacement_of` nodes; ROOT_EVAL at tree-green.

Feature flag: `agent.loop.decompose.enabled` (default `false` until P3 green).

**Package:** `soothe` (context, sloop, config). Autopilot goal DAG unchanged.

---

## 2. Coding Plan (phases)

| Phase | Scope | Exit criteria |
|-------|--------|---------------|
| **P0** | Schema + types + config + tree_green helpers + unit tests | Flag off; no behavior change |
| **P1** | Executor-bound `decompose_task`; THREAD envelope + `write_todos` override; proposal queue | Tool enqueues proposal; no CE commit from tool |
| **P2** | Deterministic RECONCILE behind flag | Proposals → children claimable |
| **P3** | Graph cutover (DISPATCH/RECONCILE/ROOT_EVAL); pass2 bypass | Flag on path works for one-shot + simple decompose |
| **P4** | Conflict LLM reconcile; B-lazy; ROOT_EVAL gaps | Failure + gap paths green |
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

Sync: `config/soothe.template.yml`, `config/develop/soothe.yml`, packaged
daemon templates if present.

### 3.4 Tests

`packages/soothe/tests/unit/context/test_step_dag.py` (+ new
`test_decomposition_types.py`): statuses, tree_green, lineage fields,
proposal validation.

---

## 4. P1+ outline (next)

- Bind `decompose_task` in executor when `decompose.enabled` and step THREAD.
- Proposal sink on `LoopRuntimeContext`.
- THREAD prompt: DECOMPOSITION vs TODOS; override TodoListMiddleware copy.
- Do **not** implement nano middleware for decompose.

---

## 5. Non-Goals (this IG)

- Goal-directive CE `"decompose"`
- Merging autopilot `apply_llm_subgoals`
- Full topology cutover before P0–P2 solid

---

## 6. Verification

After each phase: `./scripts/verify_finally.sh`. Fix until green.
Ask user before cleansing related legacy after substantial slices.

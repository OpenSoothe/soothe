# RFC-904: Sloop Recursive Step Decomposition

**RFC**: 904
**Title**: Sloop Recursive Step Decomposition
**Status**: Proposed
**Kind**: Architecture Design
**Created**: 2026-08-19
**Dependencies**: RFC-220, RFC-624, RFC-630, RFC-903, RFC-622, RFC-219, RFC-803
**Revises**: RFC-220 §Loop Graph Topology (plan/eval/execute stations); RFC-201 §Plan-Execute structure (upfront plan waves); RFC-213 (per-iteration assess+generate pair); RFC-624 §StepDAG / Step Anchor Registry; RFC-630 §Pass 2 scope classification and complexity-tiered planning routes
**Related**: RFC-207, RFC-214, RFC-625 (goal-level decompose remains separate), RFC-206
**Design draft**: `docs/archive/drafts/2026-08-19-sloop-recursive-decomposition-design.md`

---

## Abstract

StrangeLoop single-goal execution **must** replace the rigid
plan/exec/eval station spine with **recursive, LLM-driven step decomposition**
where the Context Engine (CE) is the active source of truth for a goal's
`StepDAG`.

After intake **pass1** (chitchat vs task), a task becomes the **root step** of
its StepDAG. Each step thread either **completes** or calls executor-bound
**`decompose_task`**, which emits a `DecompositionProposal`. CE **reconciles**
proposals (deterministic by default; LLM only on conflict) and commits
children. Completions/failures land immediately; only proposals wait on the
reconcile barrier. Interior failure uses **B-lazy** replacement nodes.
Coverage is assessed only at **tree-green** via **ROOT_EVAL** (assess-only);
recoverable gaps re-dispatch a new root with `GapResult` in projection.

**Pass2** (trivial/simple/complex) is **removed**. **Pass1** is **retained**.
CoreAgent **`write_todos`** remains intra-step UX and **must not** create
StepDAG nodes. Autopilot goal-level decomposition (`apply_llm_subgoals`) is
unchanged and unmerged.

---

## Motivation

1. **Rigid topology** — Adding phases requires `builder.py` / `routing.py` /
   `stations.py` changes; the loop cannot adapt structure at runtime.
2. **Upfront planning** — Full plan waves commit before evidence; correction
   waits for iteration boundaries.
3. **Disconnected decomposition** — Autopilot goal trees and sloop step
   plans do not recurse into each other; step recursion was never wired.
4. **Pass2 pre-classifies scope** — Complexity is guessed before execution;
   pass1 chitchat gating remains valuable and is kept.
5. **Stub confusion** — CE `apply_directives("decompose")` is goal-level and
   stubbed; it is not the step tool this RFC defines.

---

## Non-Goals

1. Merging goal-level and step-level decomposition (RFC-625 stays separate).
2. Replacing CoreAgent.
3. Wholesale Wire/TUI event schema rewrites (additive events only).
4. Implementing goal-directive `"decompose"` as step children.
5. Removing clarification, checkpoint, or durability (RFC-622 / RFC-803).
6. Removing intake pass1.
7. Fully incremental CE reconcile in v1.

---

## Guiding Principles

1. **CE owns the StepDAG** — Threads propose; CE reconciles and commits.
2. **Do-or-decompose** — Scope is discovered in execution, not by pass2.
3. **B-lazy interior, root-verify** — Happy-path interior nodes are not
   re-invoked; coverage eval runs only when the tree is green.
4. **Proposal barrier, completion immediacy** — Completions unblock
   dependents ASAP; proposals never race mid-reconcile.
5. **Tool authority split** — `decompose_task` ≠ `write_todos`.
6. **LoopNode contract** — New stations are RFC-903 `LoopNode` subclasses.
7. **No keyword heuristics** on user text (RFC-630 / RFC-630 discipline).

---

## Supersedes and Obsolete Surface

When RFC-904 is **Accepted** / feature flag cut over:

| Artifact | Effect |
|---------|--------|
| RFC-220 topology | Plan/eval/evidence/record/check_limits stations **obsolete** as distinct nodes; replaced by DISPATCH / THREAD / RECONCILE / ROOT_EVAL work-queue |
| RFC-201 upfront plan waves | Partially superseded — goal-as-root + recursive decompose replaces planner-emitted full waves |
| RFC-213 | Per-iteration assess+generate pair obsolete; assess survives as ROOT_EVAL; generate folds into `decompose_task` |
| RFC-624 StepDAG | Extended statuses/fields; Step Anchor Registry retired in favor of Step Context Registry; CE gains reconcile |
| RFC-630 | **Pass2** and complexity-tiered plan routes obsolete; **pass1** retained as sole intake classifier for chitchat vs task |
| RFC-903 | Remains; topology shrinks further on the same `LoopNode` / `RouteDecision` contract |
| CE `apply_directives("decompose")` | Remains out of scope (goal DAG); must not be implemented as this RFC's step tool |

Feature flag: `agent.loop.decompose.enabled` (default off until cutover green).

---

## Architecture Overview

```text
INTAKE (pass1)
  ├─ chitchat → social_response → END
  └─ task → ENTER_LOOP → DISPATCH ⇄ THREAD* → RECONCILE → …
                                  │              ├─ ready? → DISPATCH
                                  │              └─ tree_green → ROOT_EVAL → FINALIZE
                                  │                     └─ gap → new root → DISPATCH
                                  └─ ask_user → AWAIT_USER → resume THREAD
```

Settled decisions:

| Fork | Decision |
|------|----------|
| Intent | Keep pass1; delete pass2 |
| Eval | B-lazy interior + root-verify |
| DAG | Real DAG + lineage metadata; scheduler uses `dependencies` only |
| Finalization | CE reconciles proposals; completions write-through |
| Barrier | Proposal barrier; completions immediate |
| Gaps | Eval-assesses / root-decomposes |
| B-lazy identity | New `StepNode` + `replacement_of` (not same-id reset) |
| Merged failure | Primary-only recompose |
| Reconcile LLM | Conflict-triggered; degraded → deterministic |
| `decompose_task` home | Executor-bound tool in `soothe` (not nano middleware) |

---

## Intake (Pass1 Only)

**MUST** retain `IntakePass1Classifier` / pass1 coordinator path:

- `is_task=False` → `social_response`; **MUST NOT** create root StepNode.
- `is_task=True` → ENTER_LOOP; no scope label required.

**MUST** remove pass2 classifier and trivial/simple/complex routing into
plan/skip stations (migration may delete modules after cutover).

---

## Topology

### Deleted stations

As distinct graph nodes: `GATHER_EVIDENCE`, per-iteration `EVALUATE`,
`GENERATE_PLAN`, `COMMIT_PLAN`, `RECORD_PROGRESS`, `CHECK_LIMITS`.

### New / surviving stations

| Station | Role |
|---------|------|
| INTAKE | Pass1 only |
| ENTER_LOOP | Create root `StepNode`; project predecessor ledger |
| DISPATCH | Claim `pending` steps; spawn threads |
| THREAD | CoreAgent do-or-decompose (executor-bound `decompose_task`) |
| RECONCILE | Proposal barrier → CE commit |
| ROOT_EVAL | Tree-green coverage assess → GapResult |
| FINALIZE | Goal completion synthesis (RFC-219) |
| AWAIT_USER | Clarification sidecar (RFC-622) |

DELEGATE remains a THREAD execution mode, not a plan-time station.

New stations **MUST** be `LoopNode` subclasses (RFC-903).

### Wave / barrier

| Event | DAG visibility | Claimable |
|-------|---------------|-----------|
| complete / fail | Immediate | Dependents may ready on next DISPATCH |
| `DecompositionProposal` | After RECONCILE commit | Children only post-commit |

RECONCILE **MUST** run when the proposal barrier clears (claim-set finished
with proposals, or early when no in-flight proposers remain with a non-empty
queue). Zero proposals → no-op. v1 **MUST NOT** reconcile while sibling
proposers in the same claim-set still run.

`plan_iteration` increments **only** on root gap re-dispatch.

---

## Goal = Root Step

ENTER_LOOP **MUST** create a root `StepNode`:

| Field | Value |
|-------|--------|
| `description` / `full_description` | Task query |
| `dependencies` | `[]` |
| `parent_step_id` | `None` (wave 0); prior root on gap re-dispatch |
| `plan_iteration` | 0, then N+1 on gap waves |

Goal-level `depends_on` remains autopilot-owned.

### Step status extensions

`StepStatus` **MUST** add:

- `decomposed` — proposal committed; children own work; does not block tree-green
- `superseded` — replaced (B-lazy / planner replace); not claimable

Only `pending` is claimable.

### StepNode schema additions

| Field | Purpose |
|-------|---------|
| `parent_step_id` | Primary lineage |
| `secondary_parent_step_ids` | Merge accounting |
| `replacement_of` | Prior node this replaces |
| `full_description`, `expected_output`, `execution_hint` | THREAD prompting / routing |
| `recompose_count` | B-lazy budget accounting |

---

## `decompose_task` Tool

### Binding (normative)

`decompose_task` **MUST** be bound by the StrangeLoop **step executor** when a
step THREAD starts (loop-scoped). It **MUST NOT** be implemented as CoreAgent
/ nano middleware analogous to `TodoListMiddleware`.

Tool body **MUST** enqueue a `DecompositionProposal` on a host proposal sink
and return a terminal result. Executor **MUST** map that to
`step_outcome=decompose` and end the thread. The tool **MUST NOT** commit the
StepDAG directly.

Optional thin **sloop** turn-guard (at-most-one decompose; reject same-turn
conflicts) **MAY** ship later; P1 **SHOULD** rely on envelope + tool
description first.

### `step_outcome`

| Value | Meaning |
|-------|---------|
| `complete` | CE `complete_step` |
| `decompose` | `decompose_task` called |
| `blocked` | Clarification / hard block |

### Branch caps (defaults)

| Level | Max children | Config |
|-------|--------------|--------|
| Root | 5 | `agent.loop.decompose.max_branch_root` |
| Inner | 3 | `agent.loop.decompose.max_branch_inner` |

Over-cap → reject proposal; structured `branch_cap_exceeded` (no silent truncate).

### Tool args

```text
decompose_task(
  task: str,
  subtasks: list[{
    description, full_description, expected_output,
    execution_hint,  # tool | subagent | remote | auto
    depends_on_local: list[int] | None
  }]
)
```

`depends_on_local` is in-proposal only. Cross-subtree edges are reconciler-only.

### vs goal-directive decompose

| Surface | Level | This RFC |
|---------|-------|----------|
| `decompose_task` | Step StepDAG | **In scope** |
| `GoalDirective(action="decompose")` | Goal DAG | **Out of scope** |

---

## `decompose_task` vs `write_todos`

| | `decompose_task` | `write_todos` |
|--|------------------|---------------|
| Owner | StrangeLoop + CE | CoreAgent middleware |
| Mutates | StepDAG after reconcile | Thread-local todos |
| Terminal | Yes | No |
| Creates StepNodes | Yes (post-commit) | Never |

When `agent.loop.decompose.enabled`, THREAD **MUST** override
`TodoListMiddleware` prompts so `write_todos` is **intra-step only**. Stock
LangChain “break down objectives into steps” wording **MUST NOT** remain on
StrangeLoop step threads (collides with `decompose_task`).

Non-StrangeLoop CoreAgent sessions **MAY** keep stock `write_todos` prompts.

THREAD envelopes **MUST** include a `DECOMPOSITION vs TODOS` block (Step
Context Registry). Normative prompt copy lives in the design draft §5.1 and
**SHOULD** be mirrored in implementation templates.

---

## CE Reconciliation

CE **MUST**:

1. Exact-dedup proposals (always).
2. Semantic dedup / cross-subtree deps via LLM **only on conflict** (overlap,
   cross-refs, or forced debug flag).
3. Assign lineage (primary + secondaries; primary = earliest proposer).
4. Normalize deps (`plan_dag_normalizer`).
5. Enforce depth / total-step / branch budgets.
6. Commit atomically; proposers → `decomposed`.

On LLM failure: deterministic commit + `loop.reconcile_degraded`. Prefer
duplicate work over silent wrong merges.

---

## ROOT_EVAL and Gaps

### Tree-green

```text
tree_green iff
  no pending/active steps
  AND no unresolved failed leaves
  AND every non-superseded leaf is completed
  AND decomposed/superseded parents do not block
```

Unresolved failure after recompose budget → **FAIL** before ROOT_EVAL.

### ROOT_EVAL

**MUST** assess only (reuse `PlanGapAnalysis` + `StatusAssessment` → GapResult).
**MUST NOT** call `decompose_task` or invent children.

| Outcome | Action |
|---------|--------|
| ready / at_goal | FINALIZE |
| recoverable gaps | New root + GapResult projection → DISPATCH |
| unrecoverable / identical gap fingerprint / max-waves | FAIL |

Oscillation: accumulating gap context (soft); identical gap fingerprint (hard);
max-waves (hard).

---

## B-lazy Failure

Happy path: decompose once → `decomposed` → no re-invoke.

On child failure:

1. Mark child `failed`; supersede exclusive descendants.
2. Primary owner only (secondaries: projection note only).
3. If budget remains: create **new** parent `StepNode` with `replacement_of`,
   incremented `recompose_count`, failure projected.
4. Old parent → `superseded` when replacement proposal commits (preferred).
5. Rewire dependents onto replacements.
6. Budget exhausted → propagate or FAIL at root.

---

## Budgets

| Budget | Default | Config |
|--------|---------|--------|
| Max lineage depth | 5 | `agent.loop.decompose.max_depth` |
| Max steps / goal | 50 | `agent.loop.decompose.max_steps` |
| Max recompose | 2 | `agent.loop.decompose.max_recompose` |
| Max gap waves | 10 | `agent.loop.decompose.max_waves` |
| Branch root/inner | 5 / 3 | `max_branch_root` / `max_branch_inner` |
| Reconcile model | verifier tier | `reconcile_model_role` |

Depth = longest `parent_step_id` chain. Exhaustion → FAIL up to autopilot/parent.

---

## Clarification, Checkpoint, FINALIZE

- Clarification: RFC-622 / AWAIT_USER unchanged; resume same step.
- Checkpoint: prefer post-RECONCILE or clarification park; resume DISPATCH from
  ready `pending`. Map retired resume origins via `clarification.origins`.
- FINALIZE: RFC-219; ledger-direct vs synthesize keys off tree shape, not
  “single plan wave”.

---

## Observability

Additive events (catalog at impl): `step.decompose_proposed`,
`step.decompose_committed`, `step.superseded`, `step.replaced`,
`loop.reconcile`, `loop.reconcile_degraded`, `loop.root_eval`,
`loop.wave_boundary`. Retain existing step lifecycle events. Pass1 events
unchanged.

---

## Migration

| Phase | Deliverable |
|-------|-------------|
| P0 | Schema: statuses, lineage, `replacement_of`, proposal types |
| P1 | Executor-bound `decompose_task` + THREAD prompts / `write_todos` override |
| P2 | Deterministic RECONCILE behind flag (prefer skip long dual-write) |
| P3 | Graph cutover; pass1 kept; pass2 bypassed |
| P4 | Conflict LLM reconcile; B-lazy; ROOT_EVAL gaps |
| P5 | Delete pass2 + dead plan-generate; docs sync |

---

## Testing Requirements

- Pass1 chitchat bypasses ENTER_LOOP; task enters root.
- THREAD prompt authority split; `write_todos` creates no StepNodes.
- Completion readiness before sibling proposal commit.
- B-lazy `replacement_of`; primary-only recompose.
- Reconcile LLM skipped when disjoint.
- Identical gap fingerprint → FAIL.
- Clarification park/resume; checkpoint after reconcile.
- Autopilot `apply_llm_subgoals` unaffected.

Do not weaken tests to match a broken `tree_green`.

---

## Deprecation and Future Archival (RFC-900)

RFC-904 **partially supersedes** sections of several active RFCs. Those RFCs
**MUST remain** in `docs/specs/` until their *entire* normative surface is
obsolete. Do **not** archive them solely because this RFC exists.

| RFC | Obsolete surface (after cutover) | Remains normative | Archive eligibility |
|------|-----------------------------------|-------------------|---------------------|
| RFC-220 | Plan/eval/evidence/record/check_limits spine | Two-graphs-two-keys, CoreAgent isolation, checkpoint identity | After cutover Implemented: mark obsolete sections Deprecated in-header; whole-RFC archive **only** if a follow-on RFC absorbs remaining norms |
| RFC-201 | Upfront plan-wave Plan→Execute model | CoreAgent delegation concepts (until absorbed) | Same — partial only |
| RFC-213 | Per-iteration assess+generate pair | Gap schemas reused by ROOT_EVAL | Prefer keep; or Deprecated after schemas relocated to RFC-904/624 |
| RFC-624 | Step Anchor Registry; pre-reconcile StepDAG-only growth | Goal+Step DAG, projection, persistence, goal APIs | Never archive for RFC-904 alone — CE remains SoT |
| RFC-630 | Pass 2 + complexity-tiered plan routes | Pass 1 chitchat vs task | After cutover: revise body or split; archive only if replaced by a pass1-only RFC |
| RFC-903 | None (further shrink only) | `LoopNode`, `RouteDecision` | Not deprecated |

**Design draft:** Archived at
`docs/archive/drafts/2026-08-19-sloop-recursive-decomposition-design.md` after
formalization (historical reference; RFC-904 is normative).

**Process when cutover is Implemented:**

1. Add/confirm supersession notices on each row above (already started).
2. Optionally set status `Deprecated` on a RFC **only** if no active norms remain.
3. After ≥90 days Deprecated → move to `docs/archive/specs/` per RFC-900.
4. Update `rfc-index.md` and referencing docs/IGs.

---

## Open Items (impl-time)

1. GapResult type vs alias over existing schemas.
2. `proposing` as CE status vs ExecutionState scratch.
3. Exact Step Context Registry layout beyond the DECOMPOSITION vs TODOS block.
4. Supersede old parent at replacement claim vs commit (lean: on commit).
5. Optional sloop turn-guard timing (lean: after observed violations).

---

## Change History

| Date | Change |
|------|---------|
| 2026-08-19 | Proposed from approved design draft; draft archived under `docs/archive/drafts/` |
| 2026-08-19 | Documented deprecation/archive eligibility for related RFCs (partial supersession; no premature archive) |

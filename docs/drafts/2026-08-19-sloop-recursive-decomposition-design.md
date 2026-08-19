# Sloop Recursive Step Decomposition — Design Draft

**Date:** 2026-08-19
**Status:** Draft (pending review)
**Topic:** Replacing the rigid plan/exec/eval loop with recursive, LLM-driven task decomposition, with the Context Engine as the active source of truth for goal decomposition.

---

## 1. Motivation

The current Strange Loop is a statically-compiled LangGraph with 12 fixed nodes
(`INTAKE → ENTER_LOOP → GATHER_EVIDENCE → EVALUATE → GENERATE_PLAN → COMMIT_PLAN →
EXECUTE → RECORD_PROGRESS → CHECK_LIMITS → FINALIZE`, plus `AWAIT_USER` and
`DELEGATE` sidecars). Two-pass intent classification (`pass1` social/task +
`pass2` scope trivial/simple/complex) routes into it. The planner emits a full
plan wave up front each iteration; the loop iterates through the same fixed
stations until max-iterations or goal completion.

**Problems:**

- **Rigid topology.** Adding or removing phases requires code changes to
  `builder.py`, `routing.py`, and `stations.py`. The loop structure cannot be
  reconfigured at runtime.
- **Upfront planning.** The full plan for a wave is generated before any of it
  executes. Bad plans run to the iteration boundary before course-correction.
- **Disconnected decomposition.** Goal-level decomposition (autopilot rails,
  `apply_llm_subgoals`, verifier suggestions) and step-level decomposition
  (sloop planner) are separate systems that do not recurse into each other.
- **Two-pass intent is a pre-classifier.** Scope is guessed before execution
  rather than discovered. Trivial goals pay the full pipeline; complex goals
  are committed to a wave before evidence exists.
- **Stubbed recursive hook.** `ContextEngine.apply_directives("decompose")`
  logs `"Directive 'decompose' not implemented"` — the recursive
  decomposition hook exists but is not wired.

**Goal:** Replace the rigid loop with a flexible, recursive, LLM-driven
decomposition where the Context Engine is the active source of truth for a
goal's decomposition tree. Intent pass1/pass2 are removed — scope is discovered
through execution, not pre-classified.

---

## 2. Design Overview

The goal becomes the **root step** of its own step DAG. The goal is dispatched
into a thread as a single step bundled with projected ledger messages. In the
thread, the step either:

- **completes** (records its result, thread ends), or
- calls **`decompose_task`**, which emits a local `DecompositionProposal` and
  ends the thread.

Proposals do not mutate the shared DAG directly. A **CE reconciliation pass**
evaluates the union of a wave's proposals and finalizes a globally consistent
StepDAG (dedup, cross-subtree dependency synthesis, lineage assignment). Only
after commit are new children claimable.

Recursion is **step-level within one goal's DAG**, goal-as-root. The outer loop
shrinks to a work queue: `while ready_steps(dag): dispatch(next)`. The outer
loop never re-enters per-iteration plan/eval/generate stations; those collapse
into the recursive do-or-decompose choice and a single tree-green boundary
eval.

### Architecture decisions (settled during brainstorm)

| Fork | Decision | Rationale |
|------|----------|-----------|
| Eval model | **B-lazy interior + A root-verify** | Interior nodes forward-only on success (decompose once, thread ends); re-dispatched only on child failure to re-decompose that subtree. At tree-green, a halt-the-world root eval assesses against the goal. Adaptivity where it matters (mid-tree failure, root-level coverage) without paying full recursion's happy-path tax. |
| Step DAG structure | **Real DAG + `parent_step_id` lineage metadata** | Scheduler uses `dependencies` only (unchanged). `parent_step_id` is pure metadata enabling O(1) subtree ownership lookup for B-lazy re-decomposition and cross-subtree dependency reasoning. Cross-subtree and convergence edges permitted. |
| DAG finalization | **CE as active reconciler (propose → reconcile → commit)** | Threads emit proposals; CE evaluates the union per wave and finalizes a globally consistent DAG (dedup, cross-deps, lineage). Parallel threads stay lock-free; cross-subtree-rewrite hazard has a single home. |
| Gap handling | **Eval-assesses / root-decomposes** | ROOT_EVAL emits a structured GapResult (reuses `PlanGapAnalysis`/`StatusAssessment` shapes), does not decompose. Recoverable gap → re-dispatch root with GapResult in projection; root decomposes to fill it. Unrecoverable or max-waves → FAIL/escalate. |

---

## 3. New Loop Topology

### Deleted stations

`INTAKE`, `GATHER_EVIDENCE`, `EVALUATE` (per-iteration), `GENERATE_PLAN`,
`COMMIT_PLAN`, `RECORD_PROGRESS`, `CHECK_LIMITS` — as distinct nodes. The
two-pass intent coordinator (`intention/pass1`, `intention/pass2`) is removed
entirely.

### Surviving / new structure

```
ENTER_LOOP → DISPATCH → [THREAD] → RECONCILE → ROOT_EVAL → FINALIZE
                 ↑                      │            │
                 └──────────────────────┘            │
                 (next wave: root re-dispatch)       │
                 └───────────────────────────────────┘
                 (FAIL → escalate to autopilot/parent)
```

- **ENTER_LOOP.** Create the goal's root `StepNode` (status `pending`,
  `plan_iteration=0`), bundle projected ledger messages (reuses
  `predecessor_branch_context` projection). The root step's `full_description`
  is the goal query.
- **DISPATCH.** `while ready_steps(dag): claim → spawn thread`. Each ready step
  gets an isolated thread (`{main_thread_id}__step_{step.id}`, reusing
  `thread_selection`).
- **THREAD.** CoreAgent executes the step. Either completes (record result via
  CE `complete_step`/`fail_step`, thread ends) or calls `decompose_task` (emit
  `DecompositionProposal`, thread ends). Threads never mutate the shared DAG
  beyond recording their own result.
- **RECONCILE.** Per wave: collect the wave's proposals + completed results;
  CE evaluates the union and finalizes a globally consistent StepDAG (see §6);
  commit atomically; new children become claimable.
- **ROOT_EVAL.** Fires when the resolved tree is all green (no steps
  pending/active, none failed — B-lazy handles failures before this boundary).
  Halt-the-world assessment against the root goal + aggregated step results.
  Emits a `GapResult` (see §7).
- **FINALIZE.** Goal completion synthesis (reuses existing `FINALIZE` role).

The per-iteration `EVALUATE`/`GATHER_EVIDENCE`/`GENERATE_PLAN` trio collapses.
The one eval that survives fires at **wave boundaries** (tree-green), keeping
the current eval role (status assessment + gap analysis) with full result
visibility rather than per-iteration partial visibility.

---

## 4. Goal = Root Step

A goal is dispatched as a single root `StepNode` into the goal's `StepDAG`. The
root step:

- `id`: composite per existing `plan_id` mechanics (e.g., `AAA-01`).
- `description` / `full_description`: the goal query.
- `dependencies`: `[]` (the root has no step-level dependencies; goal-level
  `depends_on` is handled by the autopilot scheduler, out of scope).
- `parent_step_id`: `None` (it is the root).
- `plan_iteration`: 0, incremented on each root re-dispatch (wave).

The root step is bundled with projected ledger messages — predecessor context
for cross-goal hydration. This reuses the existing
`predecessor_branch_context` projection path; no new context mechanism is
needed for the root's initial dispatch.

On a root re-dispatch (next wave, after a gap), the root step is re-entered
with the prior wave's `GapResult` seeded into its ledger projection (see §7).
This is analogous to today's wave mechanics — `plan_id` increments, composite
step IDs, and cross-wave dependency resolution
(`expand_dependency_satisfaction_ids`) carry over unchanged.

---

## 5. The `decompose_task` Tool

Bound to the CoreAgent inside a step's thread. The thread's only mutation of
shared state is recording its own execution result; decomposition is emitted as
a proposal, not a direct DAG write.

### Input

```
decompose_task(
    task: str,                    # the current step's task, for context
    subtasks: list[{
        description: str,         # brief summary (<20 words)
        full_description: str,    # detailed prompt (50-150 words)
        expected_output: str,
        execution_hint: str,       # "tool" | "subagent" | "remote" | "auto"
    }]
)
```

### Behavior

1. Construct a `DecompositionProposal` containing the caller's `step_id`
   (proposing parent), the proposed subtasks, and any dependency hints the
   caller expressed *within* its proposal (local view only).
2. Return a terminal signal so the thread ends. The proposal is queued for the
   next RECONCILE pass.
3. The proposal is **local and parent-relative**: "from where I sit, I believe
   these subtasks are needed." It may express intended dependencies among its
   own subtasks, but cross-subtree dependencies are the reconciler's job, not
   the thread's.

### Lineage

Committed children inherit the current `plan_iteration` (wave). IDs are
composite per existing `plan_id` mechanics. The reconciler sets
`parent_step_id` on committed children (see §6). No `parent_step_id` is set
inside the proposal — that's a reconciler decision.

This is essentially promoting the stubbed
`ContextEngine.apply_directives("decompose")` (`"not implemented"`) to a
first-class bound tool, with the CE as active arbiter rather than passive
store.

---

## 6. CE Reconciliation (Per Wave)

### Objective

Evaluate the union of a wave's `DecompositionProposal`s and finalize a globally
consistent StepDAG. The CE is the active source of truth for goal decomposition;
threads are pure proposers.

### Responsibilities

1. **Dedup.**
   - *Exact*: two proposals with identical/normalized descriptions → merge to
     one node. Deterministic, cheap.
   - *Semantic*: two differently-worded proposals that mean the same task →
     merge. LLM-assisted.
2. **Cross-subtree dependency synthesis.** Parent A's child `a₂` and parent B's
   child `b₁` — infer `b₁ depends on a₂` when B's proposal references output
   that A's subtree produces. LLM-assisted, uses `parent_step_id` lineage to
     reason about subtree ownership.
3. **Lineage assignment.** Set `parent_step_id` on each committed child
   (pointing to the proposing parent). For merged children (dedup of proposals
   from two parents), record both parents (list-valued or primary+secondary —
   see §10 Open Questions).
4. **Dependency normalization.** Resolve in-plan dependency references against
   existing and new IDs; reuse `plan_dag_normalizer` (cycle drop, linear-dep
   inference, dependency-mode forcing).
5. **Commit.** Write the reconciled children atomically: `dependencies`
   (including new cross-subtree edges) and `parent_step_id` land together. Only
   after commit are the new children claimable by DISPATCH.

### Hybrid: deterministic + LLM-assisted

- **Deterministic pre-pass** (every wave): exact-duplicate detection, ID/dep
  normalization, cycle handling. Cheap. When proposals are disjoint (no
  semantic overlap, no cross-subtree refs), this pass is sufficient and the
  LLM call is skipped.
- **LLM-assisted pass** (when needed): semantic dedup, cross-subtree
  dependency inference. Template: the existing `DagVerificationReasoner`
  pattern in the autopilot.

### Cadence

One reconcile pass per dispatch wave: batch-collect the wave's proposals,
reconcile once. Simpler than incremental reconciliation, and matches the wave
boundary where results already land.

### B-lazy interaction

A failing child re-dispatches its owning parent (via `parent_step_id` reverse
lookup). The parent emits a *fresh proposal*. That proposal enters the next
reconciliation batch. The reconciler can rewire cross-subtree dependents that
pointed at the failed child (now superseded) onto the replacement — the
cross-subtree-rewrite hazard handled in one place rather than scattered across
the graph.

---

## 7. ROOT_EVAL and Gap Handling

### When ROOT_EVAL fires

When the resolved tree is **all green** — no steps pending/active, none failed.
B-lazy resolves failures mid-tree before this boundary. A persistent failure
that exhausts the per-node re-decompose budget propagates upward; if it
reaches the root without resolution, the goal **fails before reaching
ROOT_EVAL** (escalates to autopilot/parent). ROOT_EVAL only runs when the tree
is fully green and the question is coverage, not part-failure.

### ROOT_EVAL's job: assess, not plan

ROOT_EVAL assesses the root goal against aggregated step results (ledger
projection of all `execute_step` messages). It reuses the existing eval schemas
almost verbatim:

- `PlanGapAnalysis`: `components` (each `satisfied`/`partial`/`blocked` with
  evidence/gap), `remaining_gaps`, `distance_from_goal:
  far|moderate|near|at_goal`, `gap_reasoning`.
- `StatusAssessment`: `terminal_readiness: not_ready|ready_with_gaps|ready`.

ROOT_EVAL produces a **GapResult** (structured). It does **not** decompose.

### GapResult routing

- **`at_goal` / `ready`** → `FINALIZE`. No gap, done.
- **`ready_with_gaps` / `near`/`moderate`/`far` with recoverable gaps** →
  **re-dispatch the root step**, with the GapResult seeded into its ledger
  projection. The root, on this next turn, sees "these specific components are
  still unsatisfied, here's the evidence so far" and does what a root does:
  either completes directly if the gap is answerable from existing results, or
  calls `decompose_task` to spawn children targeting the missing components.
  Children can depend on already-completed steps, reusing their outputs.
- **unrecoverable** (gap can't be closed with available tools/info, or the gap
  is identical to last wave's — the root already tried and failed to close it)
  → `FAIL`, which bubbles to the autopilot/parent-goal level (goal retry,
  send-back, or parent re-decomposition).

### Why eval-assesses / root-decomposes (not targeted replan from eval)

The gap path does not need a new planner phase because eval's output *is* the
plan input. ROOT_EVAL says "here's the gap"; the root's next decompose turn,
informed by that gap, *is* the plan. Eval→plan collapses into "root gets
another turn with eval feedback as the brief" — the same phase-collapse the
whole design does, applied to the gap case.

The alternative — ROOT_EVAL directly emitting fill-children scoped to the
identified gaps — would save one root invocation per gap wave but duplicates
decomposition intelligence into the eval phase and muddies the "eval never
plans" contract. Held as a v2 optimization, not the v1 design.

### Oscillation guards

1. **Accumulating gap context.** The GapResult from wave N is in the root's
   projection at wave N+1, so the root sees "you claimed done last wave; these
   gaps persisted." That pushes it to decompose rather than re-claim done. Soft
   guard.
2. **Max-waves budget** (hard guard, replaces today's max-iterations). When
   waves exhausted with a persistent gap → `FAIL` → escalate. A goal that can't
   be closed in N waves fails up, same as today's max-iteration exhaustion.

### Call-count honesty

Today: per-iteration `EVALUATE` + `GENERATE_PLAN` = two LLM calls per iteration.
New design: ROOT_EVAL + root-re-dispatch-that-decomposes = two calls per
**wave boundary**, gone entirely *within* a wave. The call count drops from
per-iteration to per-wave, not to zero.

---

## 8. B-lazy Failure Path (Interior)

### Happy path

Interior nodes are forward-only on success: a node decomposes once (emits
proposal, thread ends) or completes. When its children complete green, the node
stays completed. No re-invocation on the happy path. Cost ≈ today's wave loop.

### Failure path

When a step's thread completes with failure/anomaly:

1. **Reverse-lookup the owning parent** via `parent_step_id` (O(1) with
   lineage metadata; O(nodes) scan without it — the reason we added the
   field).
2. **Re-dispatch the parent's thread** with the child's failure
   ledger-projected in. The parent sees "your child X failed with this error"
   and can re-decompose: emit a fresh proposal creating replacement children.
3. **Next reconcile batch** commits the replacement; the reconciler rewires
   cross-subtree dependents that pointed at the failed child (now superseded)
   onto the replacement. The successful sibling stays green and untouched.
4. **Per-node re-decompose budget** (e.g., 2) guards against a chronically
   failing branch re-decomposing forever. When exhausted, the failure
   propagates upward (the parent's parent gets re-dispatched) or, at the root,
   triggers ROOT_EVAL/FAIL.

This is the intelligence the rigid loop cannot do today: mid-tree failure
recovery localized to the failing subtree, with the root unaware on the happy
path.

---

## 9. Budgets and Termination

| Budget | Purpose | Analog |
|--------|---------|--------|
| Max decomposition depth (step-level) | Cap recursion depth of step decomposition | `MAX_GOAL_DEPTH=5` (goal-level) |
| Max total steps per goal | Cap DAG size | `MAX_STEP_RESULTS_PER_GOAL=50` |
| Per-node re-decompose attempts (B-lazy) | Stop a chronically failing branch from oscillating | (new) |
| Max waves | Cap root re-dispatches (gap cycles); replaces max-iterations | `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS` |

Termination is guaranteed by: finite depth × finite branching × finite
re-decompose attempts × finite waves. A goal that cannot close within these
budgets fails up to the autopilot/parent level.

---

## 10. Trade-offs and Consequences

- **No social fast-path.** Dropping pass1 means chitchat ("hello") becomes a
  goal whose root step completes in one shot (the LLM just responds and the
  step records success). Cost: a goal + thread spawn per chitchat vs. today's
  near-free classification. Accepted — both intent passes are removed by design.
- **Scope is sloop-worker-internal.** The `StrangeLoop`/`ContextEngine` step
  DAG is the source of truth for *a goal's* decomposition. Autopilot
  goal-level dispatch (parent goal → child goals across workers) is out of
  scope and coexists. The two levels do not merge.
- **Reconciler LLM call per wave.** The reconciler introduces one LLM call per
  wave on the happy path (semantic dedup / cross-dep inference). Mitigated by
  the deterministic pre-pass that may make the LLM call unnecessary when
  proposals are disjoint.
- **`parent_step_id` is additive.** Adding the field does not reintroduce
  nesting (no sub-DAGs), does not change the scheduler (`ready_steps()` uses
  `dependencies` only), and is the one field that makes the difference between
  "real DAG that stays manageable" and "real DAG where B-lazy can't find its
  own subtree."

---

## 11. Open Questions (to resolve before/after draft review)

1. **Merged-child lineage.** When the reconciler dedups proposals from two
   different parents into one child, `parent_step_id` is no longer unique.
   Options: list-valued `parent_step_ids`; primary parent + secondary list;
   or forbid the merge and keep the children separate (duplicates work). Lean:
   primary + secondary, since forbidding merge loses the dedup benefit.
2. **Reconciler LLM model tier.** Which model for semantic dedup / cross-dep
   inference? Lean: the same tier the `DagVerificationReasoner` uses, tunable.
3. **Budget defaults.** Concretize max decomposition depth, max total steps,
   per-node re-decompose attempts, max waves. Lean: mirror existing
   `MAX_GOAL_DEPTH=5` for depth; existing `MAX_STEP_RESULTS_PER_GOAL=50` for
   total steps; 2 for re-decompose; today's
   `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS` for max waves.
4. **Proposal dependency hints.** Should the proposal format allow the thread
   to express intended in-subtree dependencies, or should *all* dependency
   inference be the reconciler's job? Lean: allow in-subtree hints (local
   view), cross-subtree is reconciler-only.
5. **Re-dispatch identity.** On root re-dispatch (gap path), is the root step
   re-entered as the same `StepNode` (status reset to `pending`) or a new
   `StepNode` with `parent_step_id` pointing to the prior root? Lean: new node
   with lineage, so the prior wave's root stays in the DAG for result
   reference and cross-wave dependency resolution.

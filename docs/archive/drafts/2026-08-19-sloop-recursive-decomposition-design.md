# Sloop Recursive Step Decomposition — Design Draft

**Date:** 2026-08-19
**Status:** Formalized as [RFC-904](../../specs/RFC-904-sloop-recursive-decomposition.md) (Proposed); draft archived
**Topic:** Replacing the rigid plan/exec/eval loop with recursive, LLM-driven task decomposition, with the Context Engine as the active source of truth for goal decomposition.
**Related RFCs (to revise / supersede, not rewrite):** RFC-201, RFC-220, RFC-207, RFC-213, RFC-214, RFC-219, RFC-624 §StepDAG / Step Anchor Registry, RFC-903 (topology shrink further). Autopilot goal DAG (RFC-625 / `apply_llm_subgoals`) stays a separate level. Intention: keep pass1 (chitchat vs task); remove pass2 scope pre-classification.

---

## 0. Non-Goals

Explicitly out of scope for this design:

1. **Merging goal-level and step-level decomposition.** Autopilot still owns parent→child `GoalNode` trees (`create_subgoals` / `apply_llm_subgoals`). This design only recurses **inside one goal's StepDAG**.
2. **Replacing CoreAgent.** Threads still execute via CoreAgent tools/subagents/skills.
3. **Reworking Wire/TUI event schemas wholesale.** Existing step lifecycle events stay; new events are additive (see §14).
4. **Implementing CE goal-directive `"decompose"` as goal-spawning.** That stub remains goal-level and is **not** this tool. This design introduces step-scoped `decompose_task`; goal-directive decompose may later forward to autopilot or stay stubbed.
5. **Removing clarification / checkpoint / durability.** AWAIT_USER and checkpoint resume survive; they are re-homed, not deleted.
6. **Removing intake pass1.** Chitchat vs task classification stays. Only **pass2** (trivial/simple/complex scope) is removed.
7. **Fully incremental CE reconcile.** v1 keeps batched proposal reconcile; completions may land immediately (see §3).

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
- **Pass2 scope pre-classification.** Task *complexity* is guessed before
  execution. Trivial tasks still pay plan/eval stations; complex goals are
  committed to a wave before evidence exists. (Pass1 chitchat vs task remains
  valuable and is kept.)
- **Stubbed recursive hook.** `ContextEngine.apply_directives("decompose")`
  logs `"Directive 'decompose' not implemented"` — a recursive hook exists at
  the **goal** directive surface but is not the step-level mechanism this
  design needs (and must not be conflated with it).

**Goal:** Replace the rigid plan/exec/eval loop with recursive, LLM-driven
decomposition where the Context Engine is the active source of truth for a
goal's StepDAG. **Pass2 is removed** — task scope is discovered through
do-or-decompose. **Pass1 is retained** — chitchat exits before ENTER_LOOP.

**Success criteria (design-level):**

1. Chitchat (`pass1.is_task=False`) returns `social_response` without entering
   the decompose/dispatch loop.
2. A one-shot answerable **task** completes via a single root thread (no
   GENERATE_PLAN / COMMIT_PLAN stations).
3. A multi-step goal grows a StepDAG only as threads call `decompose_task`;
   children become claimable only after CE reconcile commit.
4. Mid-tree child failure replaces the owning parent via a **new** StepNode
   (B-lazy), not the whole goal plan.
5. Tree-green ROOT_EVAL can reopen the root with a GapResult; max-waves still
   terminates.
6. Clarification, checkpoint resume, and FINALIZE synthesis still work.
7. Autopilot goal DAG behavior is unchanged.

---

## 2. Design Overview

The goal becomes the **root step** of its own step DAG. After pass1 admits a
task, the goal is dispatched into a thread as a single step bundled with
projected ledger messages. In the thread, the step either:

- **completes** (records its result via CE `complete_step`, thread ends), or
- calls **`decompose_task`**, which emits a local `DecompositionProposal` and
  ends the thread (parent becomes `decomposed` after commit — see §4.1).

Proposals do not mutate the shared DAG directly. A **CE reconciliation pass**
evaluates the union of a wave's proposals and finalizes a globally consistent
StepDAG (dedup, cross-subtree dependency synthesis, lineage assignment). Only
after commit are new children claimable. **Completions and failures may land
immediately**; only proposals wait for reconcile (§3).

Recursion is **step-level within one goal's DAG**, goal-as-root. The outer loop
shrinks to a work-queue driver:

```text
INTAKE (pass1 only)
  is_task=False → social_response → END
  is_task=True  → ENTER_LOOP → …
while not terminal:
    if failed_unresolved: escalate / FAIL
    elif tree_green: ROOT_EVAL → FINALIZE | re-dispatch root | FAIL
    else: DISPATCH ready → (completions land ASAP) → RECONCILE proposals → loop
```

### Architecture decisions (settled)

| Fork | Decision | Rationale |
|------|----------|-----------|
| Intent | **Keep pass1; delete pass2** | Chitchat fast-path stays cheap. Scope (trivial/simple/complex) is discovered by do-or-decompose, not pre-classified. |
| Eval model | **B-lazy interior + A root-verify** | Interior forward-only on success; re-dispatch only on child failure. Tree-green ROOT_EVAL for coverage. |
| Step DAG structure | **Real DAG + lineage metadata** | Scheduler uses `dependencies` only. `parent_step_id` + `secondary_parent_step_ids` for ownership / merge accounting. |
| DAG finalization | **CE reconciler for proposals** | Completions/failures write through immediately; proposals batch-reconcile then commit. |
| Wave barrier | **Proposal barrier, not full join tax** | Exec-only waves reconcile as no-op (or skip). Early reconcile when no in-flight proposers remain. |
| Gap handling | **Eval-assesses / root-decomposes** | ROOT_EVAL → GapResult; recoverable → new root + projection. |
| Parent after decompose | **Status `decomposed`** | Not a leaf; children own further work; does not block tree-green. |
| B-lazy identity | **New replacement StepNode** | Never `decomposed→pending` on same id. Old parent stays `decomposed` or marked `superseded` as planner; `replacement_of` links. |
| Merged-child failure | **Primary-only recompose** | Secondaries get projection note only — no dual fan-out. |
| Decompose bounds | **Structured outcome + branching caps** | `step_outcome` + max children per decompose level (config). |
| Reconcile LLM | **Only on conflict** | Default deterministic; LLM if overlap / cross-refs / multi-proposal conflict signals. Degraded = deterministic commit + event. |
| Root re-dispatch | **New root StepNode per gap wave** | Prior root retained for reference. |
| Clarification / DELEGATE | **Retained** | AWAIT_USER sidecar; DELEGATE as THREAD execution mode. |
| `decompose_task` vs `write_todos` | **Split authority** | `decompose_task` = durable StepDAG (terminal). `write_todos` = intra-step checklist only; override TodoListMiddleware prompts so they no longer say “break down objectives into steps.” |
| `decompose_task` binding | **StrangeLoop-bound tool, not CoreAgent middleware** | Bound by the step executor on THREAD start; closes over proposal sink. Optional thin sloop turn-guard only. Not a `TodoListMiddleware` twin in nano. |

---

## 3. New Loop Topology

### Deleted stations / modules

As distinct graph stations: `GATHER_EVIDENCE`, `EVALUATE` (per-iteration),
`GENERATE_PLAN`, `COMMIT_PLAN`, `RECORD_PROGRESS`, `CHECK_LIMITS`.

Removed: **intention pass2** (scope classifier) and the plan-generate /
plan-assess station pair as separate LLM phases.

### Retained intake

**INTAKE / pass1** stays as the chitchat vs task gate (existing
`IntakePass1Classifier` / coordinator pass1 path):

- `is_task=False` → return `social_response` (existing fast-path); do **not**
  create a root StepNode / enter DISPATCH.
- `is_task=True` → ENTER_LOOP with the task as root step. No scope label is
  required; do-or-decompose discovers depth.

Pass2 modules (`pass2_classifier`, scope→intake_label trivial/simple/complex
routing into plan/skip paths) are deleted or reduced to dead code removal in
migration P5.

### Surviving / new structure

```text
INTAKE (pass1)
  ├─ chitchat → social_response → END
  └─ task → ENTER_LOOP → DISPATCH ⇄ THREAD* → RECONCILE → …
                                  │              │
                                  │              ├─ ready? → DISPATCH
                                  │              └─ tree_green → ROOT_EVAL → FINALIZE
                                  │                     └─ gap → new root → DISPATCH
                                  └─ ask_user → AWAIT_USER → resume THREAD
```

- **ENTER_LOOP.** Create root `StepNode` (`pending`, `plan_iteration=0`);
  project predecessor ledger. Root `full_description` = goal/task query.
- **DISPATCH.** Claim ready **executable** steps (`pending`); spawn threads
  (`{main_thread_id}__step_{step.id}`).
- **THREAD.** Do-or-decompose (§5). Outcomes: complete, fail, propose,
  clarification. **Completions/failures:** CE `complete_step` / `fail_step`
  immediately (dependents may become ready next DISPATCH even before
  reconcile). **Proposals:** queued only; parent stays `active`/`proposing`
  until reconcile commit.
- **RECONCILE.** Runs when the proposal barrier clears (§3.1). Commits
  children; marks proposers `decomposed`; applies B-lazy replacements.
- **ROOT_EVAL / FINALIZE / AWAIT_USER / DELEGATE.** As previously specified.

### 3.1 Wave / barrier (precise)

| Event | When visible on DAG | Claimable effect |
|-------|---------------------|------------------|
| Step completed / failed | Immediately | Dependents may become ready on next DISPATCH |
| DecompositionProposal | After RECONCILE commit | Children claimable only post-commit |

**Proposal barrier:** RECONCILE fires when either:

1. All claimed threads in the current dispatch set have finished **and** at
   least one proposal is queued, or
2. **Early:** no in-flight thread still may propose (all remaining are
   known complete/fail paths, or the claim-set had zero proposers) and a
   proposal queue is non-empty from earlier finishes, or
3. Claim-set finished with **zero** proposals → reconcile is a no-op
   (skip LLM; optional bookkeeping only).

v1 does **not** reconcile a proposal while sibling proposers in the same
claim-set are still running (avoids cross-subtree races). Completions do not
wait on those proposers.

Clarification mid-wave still parks the goal (existing policy).

`plan_iteration` increments only on **root gap re-dispatch**, not every
interior reconcile.

### Relationship to RFC-903

`LoopNode` + `RouteDecision` remain the node contract. New stations
(`DISPATCH`, `RECONCILE`, `ROOT_EVAL`) are `LoopNode` subclasses. INTAKE
remains; its post-route drops pass2 branches.

---

## 4. Goal = Root Step

| Field | Root value |
|-------|------------|
| `id` | Composite per existing `plan_id` mechanics (e.g. `AAA-01`) |
| `description` / `full_description` | Task query (post-pass1) |
| `dependencies` | `[]` |
| `parent_step_id` | `None` for wave-0 root; prior root id on gap re-dispatch |
| `plan_iteration` | 0, then N+1 on each root re-dispatch |
| `replacement_of` | `None` for normal roots; set for B-lazy replacement nodes |

Goal-level `depends_on` remains autopilot-owned.

On root re-dispatch (gap): **new** root StepNode, GapResult in projection,
prior root retained.

### 4.1 Step status model (extended)

Current: `pending | active | completed | failed | skipped`.

Add:

| Status | Meaning |
|--------|---------|
| `decomposed` | Proposal committed; children own work. Resolves for tree-green. |
| `superseded` | Replaced by B-lazy (failed child, or replaced planner node). Not claimable; does not block tree-green. |

**Invariant:** Only `pending` is claimable. Happy-path `decomposed` parents are
never re-entered. B-lazy creates a **new** parent StepNode (`replacement_of`
→ old parent id); old parent is left `decomposed` or flipped to `superseded`
once the replacement's proposal commits (impl choice: prefer `superseded` so
lineage scans skip it).

### 4.2 StepNode schema additions

| Field | Type | Purpose |
|-------|------|---------|
| `parent_step_id` | `str \| None` | Primary lineage parent |
| `secondary_parent_step_ids` | `list[str]` | Merge accounting |
| `replacement_of` | `str \| None` | Prior node this replaces (B-lazy / gap) |
| `full_description` | `str \| None` | Detailed prompt |
| `expected_output` | `str \| None` | Success criteria |
| `execution_hint` | `Literal["tool","subagent","remote","auto"] \| None` | THREAD hint |
| `recompose_count` | `int` | Count inherited/incremented on replacement |
| `kind` | optional | Preserve `ask_user` etc. |

---

## 5. The `decompose_task` Tool

### Do-or-decompose contract

Thread end must resolve a structured **`step_outcome`**:

| Value | Meaning |
|-------|---------|
| `complete` | Step done; CE `complete_step` |
| `decompose` | `decompose_task` was called (terminal tool) |
| `blocked` | Clarification / hard block (existing ask_user path) |

Prompt rules:

1. Prefer **complete** when answerable with tools + context.
2. Call **`decompose_task`** only when the work must split into smaller units
   that should become **separate schedulable StepDAG nodes** (parallelism,
   distinct deps, or independent failure domains).
3. `decompose` and `complete` are mutually exclusive for one turn.
4. On re-dispatch (gap or B-lazy), treat projected brief as authoritative;
   prefer targeted children over cloning the prior proposal.
5. Do **not** use `decompose_task` as a personal checklist — that is
   `write_todos` (§5.1).

No keyword heuristics on user text (RFC-630). Pass1 already separated
chitchat; within a task, outcome is structured tool/field choice.

### Branching caps (over-decompose guard)

| Level | Max children per proposal (default) | Config |
|-------|--------------------------------------|--------|
| Root (`parent_step_id is None` or gap root) | 5 | `agent.loop.decompose.max_branch_root` |
| Deeper | 3 | `agent.loop.decompose.max_branch_inner` |

Over-cap → reconciler **rejects** proposal; proposing step → `failed` with
structured reason `branch_cap_exceeded` (may B-lazy once, or surface
ask_user — prefer fail→B-lazy/root path, not silent truncate).

### Input

```text
decompose_task(
    task: str,
    subtasks: list[{
        description: str,
        full_description: str,
        expected_output: str,
        execution_hint: str,              # tool | subagent | remote | auto
        depends_on_local: list[int] | None,
    }]
)
```

`depends_on_local` = in-proposal hints only. Cross-subtree edges = reconciler
only.

### Behavior

1. Build `DecompositionProposal` (caller `step_id`, subtasks, local deps).
2. Terminal tool result; queue for RECONCILE; **this thread ends**.
3. Reconciler owns IDs, lineage, cross-subtree edges, branch-cap checks.
4. Calling `decompose_task` does **not** complete the goal — it only proposes
   children. Parent becomes `decomposed` after commit; leaves complete later.

### vs CE `apply_directives("decompose")`

| Surface | Level | This design |
|---------|-------|-------------|
| `decompose_task` | Step StepDAG | **Implement** |
| `GoalDirective(action="decompose")` | Goal DAG | Out of scope |

---

## 5.1 `decompose_task` vs CoreAgent `write_todos` (normative)

CoreAgent already binds LangChain/deepagents **`write_todos`**
(`TodoListMiddleware`) for in-thread progress UX (TUI Todo section). That
tool must **not** be confused with StrangeLoop/CE decomposition.

### Authority split

| | `decompose_task` | `write_todos` |
|--|------------------|---------------|
| **Owner** | StrangeLoop + Context Engine | CoreAgent thread (middleware state) |
| **Mutates** | Goal `StepDAG` (after RECONCILE) | Ephemeral thread-local todo list |
| **Scheduler** | Yes — children become claimable steps | No — never creates StepNodes |
| **Parallelism** | Yes — siblings can DISPATCH in parallel | No — same thread executes serially |
| **Failure domain** | Child fail → B-lazy recompose | Todo item status only; step still fails/succeeds as one unit |
| **Thread lifetime** | **Terminal** for this turn | Non-terminal; continue tools / answer |
| **Durability** | Durable in CE DAG / checkpoints | Session/thread UX; not the plan SoT |
| **When to use** | Work needs **other steps** (deps, parallel, separate ownership) | Track micro-steps **inside** the current step |

### Decision rule (for the model)

```text
Need multiple schedulable units (parallel, deps, or independent retry)?
  → decompose_task  (ends this thread)

Need a checklist while YOU finish THIS step alone?
  → write_todos     (then keep working; mark items done; final answer in-thread)

Can finish in a few tool calls without either?
  → do the work; complete the step  (neither tool)
```

**Forbidden patterns:**

1. Call `write_todos` with items that are really separate StepDAG children
   (those belong in `decompose_task`).
2. Call `decompose_task` for sequential micro-steps you will execute yourself
   in this same thread (use `write_todos` or just execute).
3. Call both in the same turn intending `write_todos` items to become
   children — `write_todos` never feeds RECONCILE.
4. Treat `write_todos` completion as step/goal completion — step completes only
   via CE `complete_step` / normal thread success; goal via ROOT_EVAL/FINALIZE.

### Customizing TodoListMiddleware prompts

Default LangChain `WRITE_TODOS_*` prompts say “break down larger objectives
into smaller steps,” which **collides** with `decompose_task`. At THREAD
bind time, override `TodoListMiddleware(system_prompt=..., tool_description=...)`
so `write_todos` is scoped to **intra-step** tracking only. Normative copy:

**`write_todos` system addendum (THREAD):**

```text
## write_todos (intra-step only)

`write_todos` tracks progress **inside the current execution step**.
It does NOT create StrangeLoop steps and does NOT change the goal StepDAG.

Use write_todos when:
- This step needs 3+ tool actions you will run yourself in this thread
- You want a live checklist for the TUI / your own focus
- You may revise the list as you discover work mid-step

Do NOT use write_todos when:
- Work should become separate schedulable steps → call decompose_task instead
- The step is trivial (a few tool calls) → just execute and finish
- You are about to end the thread by decomposing — skip todos; decompose

write_todos is never terminal. After updating todos, continue working.
Mark items completed as you finish them. Deliver the step result as normal
assistant content / tool outcomes; marking todos done is not step completion.
```

**`write_todos` tool description (THREAD):**

```text
Create or replace the todo list for THIS step's in-thread work only.
Args: todos: [{content, status}] with status pending|in_progress|completed.
Does not spawn StepDAG children. For cross-step decomposition use decompose_task.
```

**`decompose_task` tool description (THREAD):**

```text
Propose child steps for the Context Engine StepDAG when this step cannot
(or should not) be finished in this thread alone.

Use when subtasks need their own threads, dependencies, parallelism, or
independent failure/retry. This call is TERMINAL for this thread: after
reconcile, children are dispatched separately.

Do NOT use for a personal checklist of work you will still do here —
use write_todos for that.

Args: task, subtasks[{description, full_description, expected_output,
execution_hint, depends_on_local}]. Cross-step deps outside this proposal
are inferred by reconcile; only express in-subtree depends_on_local.
```

### THREAD envelope section (Step Context Registry)

Add an explicit block to the execute-step user message (alongside
`EXECUTION TASK:`), e.g.:

```text
DECOMPOSITION vs TODOS:
- decompose_task: durable StepDAG children; ends this thread; CE reconciles.
- write_todos: ephemeral checklist inside this step; keep working after.
- Prefer complete if you can finish now. Prefer decompose_task only for
  schedulable split. Prefer write_todos only for in-thread tracking.
```

On gap / B-lazy re-dispatch, append the GapResult or child-failure brief in
the same envelope; still enforce the same tool split.

### Binding: not CoreAgent middleware

`write_todos` correctly lives in CoreAgent middleware (`TodoListMiddleware`):
agent-local state, always-on UX, non-terminal, nano/deepagents-owned.

`decompose_task` does **not**. It is a **StrangeLoop / CE concern**:

| Concern | Where it lives |
|---------|----------------|
| Tool registration | Bound by the **step executor** when a StrangeLoop THREAD starts (loop-scoped), not on every CoreAgent session |
| Tool body | Closure over `LoopRuntimeContext` / proposal sink → enqueue `DecompositionProposal`, return terminal result |
| Step outcome | Executor/driver: if tool name is `decompose_task` → `step_outcome=decompose`, end thread (same class of handling as `ask_user` yields) |
| Prompt | THREAD envelope `DECOMPOSITION vs TODOS` + tool description (§5.1); enough for the authority split |
| Optional guard | Thin **sloop** turn-guard (host wrapper / LoopNode-adjacent), **only if** needed for: at-most-one `decompose_task` per turn; reject same-turn `decompose_task` + `write_todos`/`complete` conflict; re-inject §5.1 system addendum every model call |
| Must not | Live as nano middleware that knows CE StepDAG / reconcile; must not be a `TodoListMiddleware` clone |

**Package boundary:** `soothe` (executor + proposal types) owns the tool. `soothe-nano` keeps `write_todos` middleware and accepts prompt overrides from the host. Reconcile stays in CE / sloop — never inside CoreAgent middleware.

### Impl note

- Bind `decompose_task` only on StrangeLoop step threads (not arbitrary
  subagents unless explicitly designed).
- Keep `write_todos` on CoreAgent as today for TUI; override prompts when
  `agent.loop.decompose.enabled`.
- Prefer envelope + tool description first; add the thin sloop turn-guard
  only if models violate the split in practice.
- Tests: prompt contract unit tests that the override text includes the
  authority split; integration that `write_todos` does not create StepNodes;
  unit that the bound tool enqueues a proposal and does not call CE commit
  directly.

---

## 6. CE Reconciliation (Per Wave)

### Objective

Finalize the union of queued `DecompositionProposal`s into a consistent
StepDAG. Completions already applied; reconcile is proposal-centric.

### Responsibilities

1. **Exact dedup** (always).
2. **Semantic dedup / cross-subtree deps** (LLM only when triggered — §6.1).
3. **Lineage** — `parent_step_id` + `secondary_parent_step_ids`; primary =
   earliest proposer `(wave_seq, step_id)`.
4. **Normalize deps** — reuse `plan_dag_normalizer`.
5. **Branch / depth / total-step budgets** — reject over-budget proposals.
6. **Commit** — children + deps + lineage; proposers → `decomposed`; B-lazy
   supersede + rewire.

### 6.1 When to call reconcile LLM

Invoke LLM **only if** any of:

- more than one proposal in the queue, **and** normalized titles overlap or
  descriptions share explicit cross-refs, or
- a single proposal's text references step ids / outputs outside its local
  `depends_on_local`, or
- config forces `reconcile.always_llm` (debug).

Otherwise: deterministic-only commit.

**On LLM failure / invalid structure:** deterministic commit +
`loop.reconcile_degraded` event. Prefer duplicate work over silent wrong
merge; ROOT_EVAL/gap cleans coverage.

Pattern/tier: `DagVerificationReasoner` role, tunable.

### B-lazy interaction (see §8)

Primary owner only gets a replacement node; secondaries receive projection
note `"shared child X failed; primary P repairing"`.

---

## 7. ROOT_EVAL and Gap Handling

### Tree-green predicate

```text
tree_green iff
  no step in {pending, active}
  AND no unresolved failed leaf (failed that is not superseded and has no
      committed replacement repairing it)
  AND every non-superseded leaf is completed
  AND decomposed / superseded parents do not block
```

Unresolved failure after recompose budget → FAIL before ROOT_EVAL.

### ROOT_EVAL

Assess only (reuse `PlanGapAnalysis` + `StatusAssessment` → GapResult).
Does not decompose.

| Outcome | Action |
|---------|--------|
| `at_goal` / `ready` | FINALIZE |
| Recoverable gaps | New root + GapResult → DISPATCH |
| Unrecoverable / identical gap fingerprint / max-waves | FAIL |

### Oscillation guards

1. Accumulating GapResult in projection (soft).
2. Identical remaining_gaps fingerprint across consecutive waves (hard).
3. Max-waves (hard).

### Call-count honesty

- Pass1: one cheap call (existing) for every intake.
- No pass2.
- No per-iteration EVALUATE+GENERATE_PLAN.
- Gap waves: ROOT_EVAL + root thread; reconcile LLM only on conflict.

---

## 8. B-lazy Failure Path (Interior)

### Happy path

Decompose once → commit → `decomposed` → children run → parent stays
`decomposed`.

### Failure path (replacement node, not status reset)

1. Mark failed child `failed`.
2. Supersede **exclusive** descendants of that child (not shared via other
   live parents).
3. Resolve **primary** owner via `parent_step_id`. Ignore secondaries for
   recompose dispatch (projection note only).
4. If `recompose_count < budget`: create **new** StepNode:
   - `replacement_of` = old parent id
   - same logical `parent_step_id` (grandparent lineage)
   - `recompose_count = old.recompose_count + 1`
   - `pending`, with child failure + prior proposal summary projected
5. Old parent → `superseded` when replacement proposal commits (or
   immediately when replacement is claimed — prefer on commit).
6. Next reconcile commits new children; rewire dependents that pointed at
   superseded ids onto replacements.
7. Budget exhausted → propagate to grandparent (new replacement there) or
   FAIL at root.

Wave-0 root that failed a direct `complete` attempt: one structured retry via
new root (gap-like) or FAIL per config; no ROOT_EVAL until tree-green.

---

## 9. Budgets and Termination

| Budget | Default | Config key | Analog |
|--------|---------|------------|--------|
| Max lineage depth | 5 | `agent.loop.decompose.max_depth` | `MAX_GOAL_DEPTH` |
| Max total steps / goal | 50 | `agent.loop.decompose.max_steps` | `MAX_STEP_RESULTS_PER_GOAL` |
| Per-lineage recompose | 2 | `agent.loop.decompose.max_recompose` | (new) |
| Max gap waves | 10 | `agent.loop.decompose.max_waves` | `DEFAULT_STRANGE_LOOP_MAX_ITERATIONS` |
| Max branch (root) | 5 | `agent.loop.decompose.max_branch_root` | (new) |
| Max branch (inner) | 3 | `agent.loop.decompose.max_branch_inner` | (new) |
| Reconcile model | verifier tier | `agent.loop.decompose.reconcile_model_role` | DagVerificationReasoner |

Depth = longest `parent_step_id` chain (lineage). Exhaustion → FAIL up.

---

## 10. Clarification, Checkpoint, Sidecars

### Clarification

Unchanged AWAIT_USER / RFC-622 park-resume. Resume re-enters the **same**
step thread (complete or decompose next).

### Checkpoint / resume

Prefer boundaries after proposal-RECONCILE commit or clarification park.
Resume: restore CE StepDAG + ledger; DISPATCH ready `pending`. No
GENERATE_PLAN replay. Map retired station resume origins → `DISPATCH` /
`ROOT_EVAL` / `FINALIZE` / `INTAKE` as appropriate.

### FINALIZE

Ledger-direct vs synthesize (RFC-219) keys off tree shape (single completed
root vs multi-step DAG), not “single plan wave”.

### INTAKE pass1

Keep current pass1 node/classifier behavior and confidence fail-safe. Only
remove pass2 invocation and scope-based routing into plan stations.

---

## 11. Data Flow

### Chitchat

```text
User → INTAKE pass1 → is_task=False → social_response → END
```

### Task happy path

```text
User → INTAKE pass1 → is_task=True → ENTER_LOOP (root pending)
  → DISPATCH root → THREAD
  → decompose_task → proposal queued (completions of peers would land ASAP)
  → RECONCILE commit → root=decomposed
  → DISPATCH children → … → tree_green → ROOT_EVAL → FINALIZE
```

### B-lazy

```text
child fail (immediate) → supersede exclusive subtree
  → new parent StepNode (replacement_of=old) pending
  → DISPATCH → fresh proposal → RECONCILE …
```

---

## 12. Migration and Phasing

| Phase | Deliverable |
|-------|-------------|
| P0 | Schema: statuses, lineage fields, `replacement_of`, proposal types |
| P1 | Executor-bound `decompose_task` tool + `step_outcome` + THREAD prompt (§5.1); TodoListMiddleware prompt override; no nano middleware for decompose; no topology cutover |
| P2 | RECONCILE deterministic-only behind flag; dual-write optional/short |
| P3 | Graph cutover: DISPATCH work-queue; remove plan/eval stations; **pass1 kept, pass2 bypassed** |
| P4 | Conflict-triggered LLM reconcile; B-lazy replacement nodes; ROOT_EVAL gaps |
| P5 | Delete pass2 modules + dead plan-generate path; RFC/docs revise |

Flag: `agent.loop.decompose.enabled` (default off until P3 green).

Prefer **short** dual-write in P2 or skip dual-write and shadow-test offline —
dual-write with old planner is a footgun if left on.

---

## 13. Observability

| Event | When |
|-------|------|
| `step.decompose_proposed` | Proposal queued |
| `step.decompose_committed` | Children committed |
| `step.superseded` | B-lazy / replace |
| `step.replaced` | New node created with `replacement_of` |
| `loop.reconcile` | Summary (dedup, `llm_used`) |
| `loop.reconcile_degraded` | LLM failed; deterministic commit |
| `loop.root_eval` | GapResult summary |
| `loop.wave_boundary` | Claim set + outcomes |

Retain existing step queued/started/completed/failed. Pass1 intake events
unchanged.

---

## 14. Trade-offs and Consequences

- **Pass1 kept, pass2 gone.** Chitchat stays cheap; task scope is discovered.
- **Proposal barrier, completion immediacy.** Parallel exec unblocks without
  waiting on proposers; cross-proposal races still serialized.
- **B-lazy via new nodes.** Clearer DAG history; more nodes per failure
  (bounded by recompose budget).
- **Primary-only recompose.** Avoids secondary fan-out; shared-child repair
  is slightly asymmetric.
- **Branch caps.** May reject valid wide plans — tune via config; prefer
  reject over silent truncate.
- **Reconcile degraded mode.** Possible duplicate steps; gap wave is backstop.
- **RFC-903 stays.** Further topology shrink on `LoopNode`.
- **Step Context Registry** replaces Step Anchor Registry in THREAD envelopes.
- **Todo prompt override required.** Stock `write_todos` copy collides with
  `decompose_task`; THREAD must re-scope it to intra-step only (§5.1).

---

## 15. Testing Strategy (design)

| Layer | What |
|-------|------|
| Unit | pass1 chitchat bypasses ENTER_LOOP; task enters root |
| Unit | THREAD prompt/tool text: decompose vs write_todos authority split |
| Unit | `write_todos` does not create StepNodes; `decompose_task` queues proposal |
| Unit | Status / tree_green / ready_steps; branch-cap reject |
| Unit | Completion lands before sibling proposal commits; dependent readiness |
| Unit | B-lazy creates `replacement_of` node; primary-only; secondaries not requeued |
| Unit | Reconcile LLM skipped when disjoint single proposal |
| Unit | Identical gap fingerprint → FAIL |
| Integration | One-shot task root complete |
| Integration | Two-level decompose + parallel children |
| Integration | Child fail → replacement parent → success |
| Integration | Clarification park/resume |
| Integration | Checkpoint after reconcile |
| Contract | Autopilot `apply_llm_subgoals` unaffected; pass1 social_response unchanged |

---

## 16. Spec / Doc Impact (when formalized)

| Artifact | Action |
|---------|--------|
| RFC-220 | Revise topology; INTAKE pass1-only route |
| RFC-201 | Partially supersede upfront plan-execute |
| RFC-213 | Assess retained at ROOT_EVAL; generate → decompose |
| RFC-624 | StepDAG fields/statuses; reconcile |
| RFC-903 | Further shrink; keep LoopNode |
| RFC-625 | Goal vs step decompose boundary |
| Intention docs / pass2 | Deprecate pass2 only |
| IG (new) | P0–P5 cutover |

Prefer updating RFC-220 / RFC-624 over a competing parallel loop RFC.

---

## 17. Settled Decisions Log

| # | Question | Decision |
|---|----------|----------|
| 1 | Merged-child lineage | Primary + `secondary_parent_step_ids` |
| 2 | Reconcile model tier | DagVerificationReasoner role; tunable |
| 3 | Budgets | depth 5, steps 50, recompose 2, waves 10, branch 5/3 |
| 4 | Proposal deps | In-subtree `depends_on_local` only |
| 5 | Root gap identity | New StepNode + lineage |
| 6 | Parent after decompose | `decomposed` |
| 7 | Interior B-lazy identity | **New** StepNode + `replacement_of` (not same-id reset) |
| 8 | Goal-directive decompose | Out of scope |
| 9 | Intent | **Pass1 keep; pass2 remove** |
| 10 | Wave barrier | Completions immediate; proposals barrier-reconcile |
| 11 | Reconcile LLM | Conflict-triggered; degraded → deterministic |
| 12 | Secondary on failure | Projection note only; primary recomposes |
| 13 | `write_todos` vs `decompose_task` | Split (§5.1); override TodoListMiddleware prompts under decompose flag |
| 14 | `decompose_task` implementation home | **Executor-bound tool** in `soothe` (not CoreAgent/nano middleware); optional thin sloop turn-guard later |

### Remaining (impl-time)

1. GapResult type vs alias over existing schemas.
2. `proposing` as CE status vs ExecutionState scratch.
3. Exact Step Context Registry layout beyond the DECOMPOSITION vs TODOS block.
4. Whether old parent flips to `superseded` at replacement claim vs commit.
5. P2 dual-write duration (lean: skip or ≤1 release).
6. Whether non-StrangeLoop CoreAgent sessions keep stock write_todos prompts (lean: **yes**, stock prompts outside step THREAD).
7. Whether the optional sloop turn-guard ships in P1 or only after observed violations (lean: **P1 envelope only**; guard if needed).

---

## 18. Self-Review Notes

- Recommendations from design critique folded in (§3.1, §5 caps, §6.1, §8).
- Pass1 retained explicitly; earlier “remove both passes” retracted.
- B-lazy no longer uses `decomposed→pending` same-id revival.
- Completion vs proposal visibility split removes the worst wave-join tax
  without incremental reconcile.
- §5.1 adds normative THREAD prompt copy so `write_todos` cannot be mistaken
  for StepDAG decomposition (stock LangChain wording would collide).
- `decompose_task` is explicitly **not** CoreAgent middleware; executor-bound
  tool + envelope, with optional host turn-guard only.

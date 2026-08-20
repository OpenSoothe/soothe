# RFC-905: StrangeLoop Eval Thread

**RFC**: 905
**Title**: StrangeLoop Eval Thread
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-08-20
**Updated**: 2026-08-20
**Authors**: Soothe Team
**Dependencies**: RFC-904, RFC-219, RFC-630, RFC-901, RFC-214
**Related**: RFC-213, RFC-220, RFC-622, RFC-624, IG-751
**Revises**: RFC-904 §ROOT_EVAL (assess-only / MUST NOT `decompose_task`; GapResult new-root continuation)

---

## Abstract

StrangeLoop **Eval** is a first-class coverage step: an engine-injected
`StepNode` (`kind=eval`) that runs in a **fresh CoreAgent thread** with
**readonly inspect tools** plus executor-bound **`decompose_task`**.

Eval answers two questions the action DAG cannot:

1. Was the **user goal** achieved **successfully and completely**?
2. Are worker leftovers (next actions, recommendations, pending tasks)
   **in-scope**, **necessary**, and **safe** to schedule as new children?

Eval is **not** a worker (no writes, no shell) and **not** FINALIZE
(RFC-219 user-facing synthesis, no tools). Continuation of incomplete
in-scope work uses Eval's `decompose_task`, not RFC-904 P4 GapResult
new-root re-dispatch.

---

## Motivation

RFC-904 replaced per-iteration assess/generate with do-or-decompose.
`ROOT_EVAL` was specified as **assess-only** at **tree-green**, and
**MUST NOT** call `decompose_task`. The landed station
(`RootEvalNode`) is a **structural stub**: `tree_green()` → FINALIZE.
IG-751 P4 GapResult re-dispatch is unimplemented.

That model fails a common long-horizon pattern: a worker LLM
**early-terminates** — it writes a report plus “next steps”,
recommendations, or leftover TODOs, then marks the step `completed`.
The StepDAG looks green; the **user goal** is not.

Coverage is not a boolean on leaf status. It needs:

- A **fresh** auditor thread (not the worker chat that talked itself into stopping).
- **Evidence** against the workspace (readonly tools).
- A **scoped continuation** tool (`decompose_task`) that CE can reject
  when proposals are out of scope or unsafe.

---

## Non-Goals

1. Replacing RFC-219 FINALIZE / goal-completion synthesis.
2. Autopilot `evaluate_goal_completion` / consensus (outside StrangeLoop).
3. Reviving per-iteration `EVALUATE` / `PlanGapAnalysis` / `StatusAssessment`.
4. Keyword or regex judgment of worker prose (RFC-630). Early-exit is a
   **structured** `StepCloseReport`.
5. Merging goal-level decomposition (`apply_llm_subgoals`) with step Eval.
6. Implementing this RFC in the same change as the spec (follow-on IG).

---

## Guiding Principles

1. **Eval is coverage audit, not execution.** Readonly inspect + schedule
   remaining in-scope work; never mutate the workspace.
2. **Fresh thread.** Empty CoreAgent checkpoint history; envelope is the
   user goal plus intra-goal StepDAG history/status, not the last worker
   transcript as the primary context.
3. **User goal is the scope bar.** Worker “pending / next / recommended”
   items are **untrusted candidates**. Eval **MUST NOT** pass them through
   unless they are necessary to complete the original user goal.
4. **No distraction, no drive-by features.** Out-of-scope proposals are
   rejected at reconcile (`out_of_scope`), not committed.
5. **Engine-injected step.** Eval is not LLM-scheduled. DISPATCH / ROOT_EVAL
   inserts `kind=eval` when the **action tree** is green and Eval is required.
6. **Structured light-LLM fields** for early-exit and subtask scope
   (RFC-630). No keyword lists on user or worker text.
7. **B-lazy workers, root-verify via Eval.** Happy-path interior action
   nodes are not re-invoked; coverage runs as an Eval step when required.

---

## Mental Model

| Role | Job | Tools |
|------|-----|--------|
| Plan (worker THREAD) | Do-or-decompose this step | Full tool set + `decompose_task` |
| Exec | Finish claimed `action` / `ask_user` steps | Full tool set (action) |
| **Eval** | Did the user goal succeed completely? Is leftover work in-scope and safe to schedule? | **Readonly** inspect + `decompose_task` |
| FINALIZE | User-visible answer from the ledger | No tools |

**Early-terminal pattern Eval exists to catch:**

- Worker completes with a report plus recommended next steps / pending tasks.
- Remaining work is still **the same user goal** → Eval **MAY**
  `decompose_task` in-scope children.
- Remaining work is **out of scope** (new products, unrelated polish) →
  Eval **MUST NOT** schedule it; if the user goal itself is done, complete
  Eval without children → FINALIZE.

---

## Topology

Keep RFC-904 DISPATCH ⇄ EXECUTE → RECORD_PROGRESS → RECONCILE.
ROOT_EVAL becomes the **gate** that inserts or skips the eval `StepNode`,
then routes DISPATCH (eval pending) or FINALIZE (eval not required, or last
eval `completed` with no committed children).

```text
RECONCILE
  ├─ ready action / ask_user steps → DISPATCH → EXECUTE (worker)
  └─ action-tree green
        ├─ eval required → insert kind=eval (if none pending) → DISPATCH
        │                    → EXECUTE (eval thread)
        │                    → RECORD → RECONCILE
        │                         ├─ in-scope children committed → DISPATCH workers
        │                         └─ eval completed, no children → FINALIZE
        └─ eval not required → FINALIZE
```

`evaluate_step_deliverable` remains execute-local retry (not loop Eval).

---

## Eval as a StepNode

Engine injects a `StepNode` with **`kind=eval`** (alongside `action` and
`ask_user`).

| Field | Rule |
|-------|------|
| `kind` | `eval` |
| Scheduling | Engine only; workers **MUST NOT** create eval nodes via `decompose_task` |
| `parent_step_id` | Goal root (or current coverage parent) |
| Continuation children | Children of **this eval node**; eval → `decomposed` when proposals commit |
| Claim | Same as other `pending` steps: DISPATCH → EXECUTE → RECORD → RECONCILE |
| Thread | New `fork_thread_id` per eval step; **MUST NOT** reuse the last action thread |

**Outcomes:**

| Eval result | DAG / graph |
|-------------|-------------|
| No proposals; eval `completed` | Coverage-green → FINALIZE |
| In-scope proposals committed | Children `pending` → DISPATCH workers |
| Out-of-scope proposals | Reconcile **rejects** (`out_of_scope`); eval **MAY** still `completed` if the user goal is done |

Unresolved `failed` action leaves still **FAIL** before Eval (RFC-904 B-lazy
budget). Failed eval step: treat as coverage failure (do not FINALIZE as
success); retry within `max_eval_rounds` or FAIL.

---

## When Eval Runs

### Action-tree green

No `pending` / `active` **action** or **ask_user** leaves. Unresolved
`failed` blocks Eval. Ignore eval nodes already `completed` / `decomposed`
when deciding whether **another** eval is needed.

### Eval required

When the action tree is green **and** any of:

1. Any node is `decomposed` (a `decompose_task` committed this goal), or
2. More than one completed **action** leaf, or
3. A completed action step has structured **early-exit** (`StepCloseReport`).

### Skip (FINALIZE without Eval)

- No-CE `terminal_after_execute` one-shot (RFC-226).
- Chitchat / non-task intake (never entered the StepDAG).
- Action-tree green and Eval **not** required.

### Eval rounds

Cap with `agent.loop.eval.max_eval_rounds` (default **MUST** align with
`agent.loop.decompose.max_waves`, currently 10). Identical continuation
fingerprint (same accepted/rejected child set as the previous eval wave)
→ **FAIL** closed; do not loop.

`plan_iteration` / wave accounting: increment on Eval-spawned continuation
waves the same way RFC-904 increments on gap re-dispatch (impl **MUST**
pick one counter; **MUST NOT** unbounded silent re-eval).

---

## StepCloseReport (early-exit, RFC-630)

At the end of each **action** step, a **fast-model structured call**
**MUST** produce a `StepCloseReport` so workers cannot omit the field by
skipping a tool. Do **not** regex worker prose for “next steps”.

```text
StepCloseReport:
  goal_portion_complete: bool
  early_exit: bool
  deferred_items: list[{description, claimed_in_scope}]
  recommendations: list[str]
```

Persist on the `StepNode` or step execution record.

**Eval required** at next action-tree green when `early_exit` is true **or**
`deferred_items` is nonempty.

Eval's envelope lists `deferred_items` and `recommendations` as
**untrusted proposals**, not accepted work.

**Open (impl-time):** always-on `StepCloseReport` vs only when a probe flag
is set. Default **SHOULD** be always-on for action steps so early-exit
cannot be skipped.

---

## Eval Thread: Evidence and Tools

### Envelope (user message)

- Original user query and goal text.
- StepDAG table: id, kind, status, description, `expected_output`, close report.
- Bounded ledger excerpts (RFC-214).
- Deferred items / recommendations labeled untrusted.

**MUST NOT** dump the full last worker checkpoint as the primary prompt.

### Policy (system)

Eval is coverage audit, not a worker. Verify against the workspace.
Complete the **user** goal only. Refuse drive-by / out-of-scope / “nice to
have”. Call `decompose_task` only for **necessary remaining in-scope
work**. After `decompose_task` returns, **stop** (same terminal semantics
as worker decompose). If the goal is complete, do not decompose; emit a
short coverage verdict.

**MUST NOT** inject worker `THREAD_POLICY_SYSTEM_ADDENDUM` (finish-vs-split).
New fragment (impl): `soothe.prompts` / `fragments/eval/eval_policy_system.xml`.

### Tool allow / deny

**Allow (builtin, not config):**

- Filesystem / search **read**: `read_file`, `grep`, `glob`, `ls`,
  `list_files`, `file_info`.
- `decompose_task` (RFC-904 executor binding; parent = this eval step id).

**Deny:**

- Writes, apply/edit, shell/execute, process control.
- `write_todos` as a scheduler (omit from the eval tool list).
- Subagent spawn / `task`.
- Mutating MCP.

Middleware (impl): configurable `soothe_eval_step_id` — filter to the
readonly allowlist and ensure `decompose_task`. Sibling of
`GoalStepGuardMiddleware` (synthesis: **no** tools) and
`DecomposeTaskMiddleware` (workers: full tools + decompose + THREAD policy).
OperationSecurity (RFC-901) **MUST** still deny mutating `operation_kind`
if a tool slips the allowlist.

Eval **SHOULD** use readonly tools to gather evidence before `completed` or
`decompose_task` (prompt-normative). A structural “at least one successful
read” gate is **SHOULD**, not MUST, unless it can be enforced without
content heuristics.

### `decompose_task` during Eval

Each proposed subtask **MUST** include:

- `in_scope: bool`
- `necessary_for_user_goal: bool`

CE reconcile **MUST** drop any subtask where either is false (`out_of_scope`
or `not_necessary`). Workers **MUST NOT** be required to send these fields
(or they default true for action-thread decompose). Eval **MUST** send them.

---

## Graph / RFC-904 Delta

| RFC-904 | RFC-905 |
|---------|---------|
| ROOT_EVAL assess-only; MUST NOT `decompose_task` | **Superseded.** Eval thread **MAY** `decompose_task` |
| Recoverable gaps → new root + `GapResult` projection | **Superseded** as the continuation mechanism. Eval children on the eval node |
| `tree_green` → coverage assess | **Action-tree green** + skip/require predicates → insert eval or FINALIZE |
| P4 GapResult type / fingerprint FAIL | Continuation fingerprint on Eval child sets; `max_eval_rounds` |

DISPATCH, THREAD (action), RECONCILE, B-lazy interior failure, and
`tree_green()` as a DAG helper remain RFC-904. Impl **MAY** keep
`tree_green()` for “no pending/active/failed” and add **action-tree green**
that ignores pending eval insertion until the gate runs.

ROOT_EVAL station id **MAY** remain; its **behavior** is the insert/skip
gate, not silent finalize.

---

## Observability

Additive events (catalog at impl): `loop.eval`, `step.eval_started`,
`step.eval_completed`, `step.close_report`. Retain `loop.root_eval` as a
legacy alias of the gate decision or migrate in the IG.

User-visible logs/CLI **MUST NOT** mention RFC-905 / IG identifiers.

---

## Config (impl)

```yaml
agent:
  loop:
    eval:
      max_eval_rounds: 10   # default: same as decompose.max_waves
```

Readonly inspect tools are a **builtin** Eval allowlist (not YAML).
`StepCloseReport` uses the existing fast-model role. No `enabled` flag
that silently skips Eval when it is required.

---

## Testing Requirements

- Early-exit `StepCloseReport` (`early_exit` or nonempty `deferred_items`)
  triggers Eval at action-tree green.
- Single completed action leaf, no `decomposed` nodes, no early-exit →
  **skip** Eval → FINALIZE.
- Multi-leaf or any `decomposed` node → Eval required even without
  early-exit.
- Out-of-scope / not-necessary subtasks rejected; not claimable.
- Eval tool list cannot write or execute shell (unit on middleware).
- Eval `decompose_task` children are claimable `action` steps; eval parent
  becomes `decomposed`.
- Fresh `fork_thread_id` for eval (not last action thread).
- Identical continuation fingerprint → FAIL, not another eval wave.
- Chitchat and no-CE `terminal_after_execute` never insert eval.
- Autopilot `apply_llm_subgoals` unaffected.

Do not weaken tests to treat worker “next steps” prose as early-exit
without `StepCloseReport`.

---

## Implementation Placement

Follow-on IG (not this RFC). Package: `soothe` (`sloop`, `context`,
`prompts`). Do not reverse the monorepo DAG. Eval prompts in
`soothe.prompts` / `fragments/eval/`.

---

## Open Items (impl-time)

1. Builtin Eval inspect names: `read_file`, `grep`, `glob`, `ls`,
   `list_files`, `file_info` (plus `decompose_task`).
2. `StepCloseReport` always-on vs `requires_eval_probe`.
3. Whether `kind=eval` nodes participate in `tree_green()` or only in
   action-tree green (lean: exclude pending eval from worker-green;
   include completed eval in coverage-green before FINALIZE).
4. Whether `max_eval_rounds` is a new key or an alias of `max_waves`.

---

## Related Documents

- [RFC-904](RFC-904-sloop-recursive-decomposition.md) — recursive decompose topology
- [RFC-219](RFC-219-goal-completion-module.md) — FINALIZE / synthesis
- [RFC-630](RFC-630-start-phase-llm-intake-and-branch-routing.md) — no keyword heuristics
- [RFC-901](RFC-901-operation-security-protocol.md) — operation security
- [RFC-214](RFC-214-strangeloop-loop-message-surface.md) — ledger / envelopes
- [RFC Index](rfc-index.md)
- [RFC Methodology Guide](../rfc-methodology-guide.md)

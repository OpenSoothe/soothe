---
title: "PlannerProtocol & Planner Subagent"
parent: Protocols
grand_parent: Wiki
nav_order: 6
description: >-
  Planning contracts and the intake-only planner subagent. The host PlannerProtocol
  interface is defined but unimplemented; live planning is the nano wire subagent
  (RFC-633) and the recursive decomposition spine (RFC-904, Proposed).
---

# PlannerProtocol & Planner Subagent

**RFCs**: 304 (Planner protocol), 633 (planner subagent: readonly recon → solution report → human review), 904 (recursive decomposition spine, Proposed)
**Locations**:
- `packages/soothe-sdk/src/soothe_sdk/protocols/planner.py` — `PlannerProtocol` interface + plan data models
- `packages/soothe/src/soothe/runner/resolver/__init__.py` — `resolve_planner()` (host resolution)
- `soothe-nano` (PyPI): `subagents/plan/` — the live intake-only planner subagent
**Status**: Interface defined, no host implementation. `resolve_planner` returns `None`. Live planning is delegated to the nano wire subagent (RFC-633) and the proposed recursive decomposition spine (RFC-904).

> **Post-deletion note (2026-08-19).** The former host `LoopPlannerProtocol`
> (two-phase assess→generate) and its continuation routing
> (trivial/simple/complex) were deleted by
> [IG-752](../../impl/IG-752-delete-legacy-plan-spine.md) (plan-spine station
> removal) and [IG-753](../../impl/IG-753-delete-llm-planner.md)
> (`LLMPlanner` / `PlanPhase` removal). RFC-904 supersedes that design. The
> historical two-phase architecture is documented below for reference only; it
> is **not** present in the codebase.

## What Planning Looks Like Now

Soothe no longer has an in-process host planner driving a plan/eval/execute
spine. After the RFC-904 DISPATCH cutover, planning splits into two surfaces:

1. **`PlannerProtocol`** (interface only) — a marker protocol in
   `soothe_sdk.protocols.planner` that CoreAgent / runner builders may accept.
   The host provides **no implementation**: `resolve_planner()` returns `None`.
   The protocol exists to keep the `planner=` builder parameter and the plan
   data models (`Plan`, `PlanStep`, `StepResult`, `Reflection`, …) stable across
   the deletion.
2. **Planner subagent** (live) — an intake-only nano wire subagent (RFC-633,
   Draft) that produces a **solution report** artifact for human review. This
   is the only active "planner" a user interacts with.
3. **Recursive decomposition spine** (Proposed, partial) — RFC-904 replaces the
   deleted plan spine with DISPATCH / THREAD / RECONCILE / ROOT_EVAL stations
   and an executor-bound `decompose_task`. The deletion half has landed; the
   topology half is still Proposed.

## PlannerProtocol (interface, no host implementation)

### Location

`packages/soothe-sdk/src/soothe_sdk/protocols/planner.py`

`PlannerProtocol` is a `@runtime_checkable` marker `Protocol` — it declares no
methods. It marks "a planner implementation attached to CoreAgent." The same
module ships the plan data models the rest of the system still references:

- `Plan` / `PlanStep` — structured decomposition with DAG `depends_on` and
  `execution_hint` (`tool` | `subagent` | `remote` | `auto`).
- `ConcurrencyPolicy` (from `soothe_sdk.protocols.concurrency`) — parallelism
  knobs carried on `Plan.concurrency`.
- `StepResult` / `StepReport` / `GoalReport` — execution evidence and reports.
- `PlanContext` — context bundle (recent messages, capabilities, completed
  steps, routing classification, workspace, thread id).
- `Reflection` / `GoalDirective` — reflection output and goal-management
  directives.

### Host resolution: `resolve_planner() → None`

`packages/soothe/src/soothe/runner/resolver/__init__.py` exposes
`resolve_planner(config, model)`. After the RFC-904 DISPATCH cutover
(IG-752/IG-753), it **always returns `None`**: StrangeLoop no longer constructs
an `LLMPlanner`. The function is kept as a stable API for runner / CoreAgent
builder callers that still pass `planner=` into nano `AgentBuilder`; those
callers receive `None` and proceed without a host planner.

## Planner Subagent (RFC-633, Draft — the live planner)

The active planner is an **intake-only nano wire subagent** defined in
`soothe-nano` (`subagents/plan/`, layout per IG-659). It is invoked from
StrangeLoop pass2/slash via `invoke_wired_subagent(planner)` and runs a
**readonly grounding → solution report → human review** workflow:

1. **Readonly recon** — the planner may bind readonly filesystem tools
   (`ls`, `glob`, `grep`, `read_file`, `file_info`) to ground a solution. Tool
   output is **internal evidence**, not the deliverable; recon must gather
   enough fact that the report can prescribe edits without scheduling further
   reads. Each tool call emits `soothe.stream.tool_call.update` via the wire
   bridge (orphan SubAgent card shows tool activity).
2. **Solution report artifact** — the deliverable is a markdown report
   (Goal, Solution, optional Design principles / Architecture changes,
   concrete Changes as edit/add/remove steps, Evidence, risks, open questions)
   persisted at `{workspace}/.soothe/plans/{UTC-compact}-{slug}.md`. Changes
   must be concrete edits, **not** an investigation roadmap of further reads.
3. **Human review** — StrangeLoop pauses via the RFC-622 clarification relay
   (origin `planner_subagent_review`) so the operator can:
   - **Approve** — grounds the DISPATCH root THREAD with the approved artifact.
     After RFC-904, Approve **must not** enter `plan_generate` (that station no
     longer exists); CE `StepDAG` children come from `decompose_task`.
   - **Reject** — `goal_completion` with a rejected status.
   - **More comments** — re-invoke the planner with the prior plan + comments,
     then review again.

> **Naming.** `planner_subagent_review` is the intake **planner subagent**
> human gate. It is **not** the deleted StrangeLoop `plan_generate` /
> `plan_assess` host planning-stage nodes.

### Non-goals (RFC-633)

- Does **not** compile the approved markdown directly into an `AgentDecision`.
- Does **not** enter `plan_generate` (removed).
- Does **not** auto-start a second CE goal after Approve (same-loop handoff
  only).
- Does **not** revive nested `task` / explore subagents.

## Recursive Decomposition Spine (RFC-904, Proposed — partial)

RFC-904 replaces the rigid plan/exec/eval station spine with **recursive,
LLM-driven step decomposition**, where the Context Engine (CE) is the active
source of truth for a goal's `StepDAG`.

- After intake **pass1** (chitchat vs task — retained), a task becomes the
  **root step** of its StepDAG.
- Each step thread either **completes** or calls executor-bound
  **`decompose_task`**, which emits a `DecompositionProposal`.
- CE **reconciles** proposals (deterministic by default; LLM only on conflict)
  and commits children. Completions/failures land immediately; only proposals
  wait on the reconcile barrier.
- Interior failure uses **B-lazy** replacement nodes. Coverage is an
  engine-injected **Eval** step when required
  ([RFC-905](../../specs/RFC-905-sloop-eval-thread.md)): fresh readonly
  CoreAgent thread plus `decompose_task`. GapResult new-root re-dispatch is
  withdrawn.
- **Pass2** (trivial/simple/complex) is **removed**. **Pass1** is **retained**.
- CoreAgent **`write_todos`** remains intra-step UX and **must not** create
  StepDAG nodes. Autopilot goal-level decomposition (`apply_llm_subgoals`) is
  unchanged and unmerged.

### Implementation status (2026-08-19)

The **deletion portion** has landed:

- [IG-752](../../impl/IG-752-delete-legacy-plan-spine.md) — removed plan-spine
  stations (`generate_plan` / `assess` / `evaluate` / `gather_evidence` /
  `commit_plan` / `check_limits`); clarification resume remapped to DISPATCH;
  iteration budget gate re-homed onto DISPATCH.
- [IG-753](../../impl/IG-753-delete-llm-planner.md) — removed `LLMPlanner` /
  `PlanPhase`; `resolve_planner` → `None`; deleted `StatusAssessment` /
  `PlanGapAnalysis` / `ContinuationAssessment`; trimmed the pass2 prompt stack
  and `plan_evaluate_*` / `plan_structural_keep_*` config.

The **recursive decomposition topology** — DISPATCH / THREAD / RECONCILE /
ROOT_EVAL stations, executor-bound `decompose_task`, CE reconciliation
(deterministic + conflict LLM), B-lazy failure replacement, RFC-905 Eval
thread (ROOT_EVAL gap / GapResult withdrawn), and StepDAG schema extensions (`parent_step_id`, `replacement_of`,
`decomposed` / `superseded` statuses) — remains **Proposed** and is not yet
implemented. RFC status stays **Proposed** pending topology implementation; the
deletion landings are tracked under IG-752 / IG-753 rather than advancing
RFC-904 to Implemented.

## Historical: LoopPlannerProtocol (deleted)

> This section describes code that **no longer exists**. It is retained for
> historical context only. The design was deleted by IG-752/IG-753 and
> superseded by RFC-904.

The former `LoopPlannerProtocol` was the StrangeLoop Plan phase: each loop
iteration it answered "is the goal complete? If not, what's the next executable
fragment?" via a unified `PlanResult` with `plan_action` of `'keep'` or
`'new'`.

### Two-phase architecture (RFC-604, deleted)

Assessment and generation were separate phases:

- **Phase 1 — `assess_status(...) → StatusAssessment`**: a lightweight
  complete/incomplete/failed check (continue / retry / abort).
- **Phase 2 — `generate_from_assessment(...) → PlanResult`**: expensive plan
  generation, only when assessment said work remained.

If Phase 1 returned `complete`, Phase 2 was skipped. The unified `plan()`
method orchestrated both. These types (`StatusAssessment`, `PlanGapAnalysis`,
`ContinuationAssessment`) and the `assess` / `generate_plan` stations were
deleted by IG-752/IG-753.

### Continuation routing (RFC-226, deleted)

Mid-loop follow-ups coordinated an **intake label** with optional
**continuation-assess**:

| Intake (continuation turn) | Former route | Continuation-assess LLM |
|----------------------------|-------------|-------------------------|
| `trivial` | `plan_assess` → bootstrap or `plan_generate` | Only for ambiguous trivial goals |
| `simple` | `plan_assess` → bootstrap or `plan_generate` | Enabled (same discriminator path) |
| `complex` | `bounded_evidence_gather` → full spine | Skipped |
| `continue` keyword | deterministic bootstrap | Skipped |

`assess_continuation()` was the continuation discriminator (`bootstrap` vs
`plan_generate`) for `trivial` and `simple` follow-ups. RFC-904 removes pass2
(trivial/simple/complex) entirely; pass1 chitchat gating is retained. The
`plan_assess` / `plan_generate` / `assess_route` / `plan_route` graph channels
were collapsed by IG-753.

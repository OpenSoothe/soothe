# Design Draft: Autopilot Report-Commit Judgment

**Status**: Formalized into Autopilot RFC set (2026-08-08) — see RFC-204 §1.3, RFC-222 report-commit subsection, RFC-625 `commit_goal_report`, RFC-231 invariant, RFC-230/228/232/624 cross-links  
**Date**: 2026-08-08  
**Scope**: Polish Autopilot so LoopRail owns DAG decompose/run, StrangeLoop ledger reports are the CE SoT for completion evidence, and AutopilotService judges + optionally revises the CE DAG only on `goal_report_committed` — without re-collecting evidence.  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md), [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md), [RFC-231](../specs/RFC-231-looprail-rail-exec.md), [RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md), [RFC-624](../specs/RFC-624-context-engine.md), [RFC-228](../specs/RFC-228-autopilot-job-ipc.md), [RFC-230](../specs/RFC-230-job-maturity-assessment.md), [RFC-232](../specs/RFC-232-waveplan-flat-semistructured-ingest.md). Canonical trigger: `goal_report_committed` from CE `commit_goal_report`.

---

## Problem

Today Autopilot completion handling still behaves like a second investigation:

1. StrangeLoop finishes a subgoal and produces a ledger/report contribution.
2. Autopilot synthesizes a wire “response” and runs an LLM consensus judge that can send_back when the narrative looks thin.
3. Operators see thrash (e.g. integrate goals re-planning merges for hours) even when the loop already recorded what it did.
4. Judgment is tied to worker-completion callbacks / status churn rather than a single durable CE artifact.
5. DAG hygiene (pending briefs, deps, priorities) is split across monitor/health paths and is not systematically driven by the new goal report.

The intended product model is simpler: **rail decomposes and runs the DAG; the loop always records a report; CE stores that report; Autopilot reacts to report commit by judging and (bounded) revising the pending plan — trusting the StrangeLoop report, not re-gathering evidence.**

---

## Goal

1. LoopRail remains the decomposer and phase driver for rail-bound jobs (deterministic builtins/guards).
2. Every StrangeLoop loop end persists a report in the StrangeLoop ledger and CE projects it onto `GoalNode.report`.
3. CE emits a canonical **`goal_report_committed`** signal when a goal report is upserted.
4. AutopilotService subscribes to that signal only for LLM judgment (not bare `pending`/`active` status changes).
5. Judge input is a **projection** of the CE-stored goal report (+ relevant CE DAG slice) — no host workspace probes, no second evidence mission.
6. Judge returns `accept` / `send_back` / `fail` plus optional **bounded DAG ops**; send_back brief uses the same call’s `reasoning`.
7. Remove/replace the inline post-worker consensus wire path so judgment cannot bypass report-commit.

---

## Non-Goals

- A second “reactor” LLM that chooses LoopRail verbs / next builtins.
- Firing the judge on every CE status transition.
- Unconstrained spawn/cancel/decompose/merge from the judge (rail/monitor allowlists only).
- Changing WorkerPool mechanics beyond where judgment is invoked.
- Reintroducing `evidence_follow_up` / host `collect_evidence` turns.

---

## Decisions

| Topic | Decision |
|-------|----------|
| Approach | Event-centric Autopilot (report-commit as sole judgment entrypoint) |
| Judge | Light structured LLM; decisions `accept` / `send_back` / `fail` |
| Judge input | Projection of CE `GoalNode.report` (ledger-backed) + CE DAG slice |
| Trigger | Pure report-commit only |
| Missing report | Worker/host must write a minimal report on any loop end; if still missing → no LLM, engine recovery only |
| Rail advance | Deterministic LoopRail after verdict |
| Send_back brief | Same judge call `reasoning` |
| DAG revise | Bounded ops: wire/unwire deps, priority, pending briefs/plan fields; spawn/cancel only via existing allowlists |
| Deterministic gates | Existing structural gates (e.g. WavePlan present) may short-circuit before/instead of LLM using CE/rail state |
| Idempotency | Keyed by `(goal_id, report_revision)` |
| Scope | Broad: new/normalized commit event + refactor decompose/dispatch/judgment around it |

---

## Architecture

```text
                    ┌─────────────┐
  job submit ──────►│  LoopRail   │  decompose / spawn / wire (YAML)
                    └──────┬──────┘
                           │ CE Goal DAG
                           ▼
                    ┌─────────────┐
                    │ Dispatch    │  ready goals → WorkerPool (status only)
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ StrangeLoop │  always ledger report on loop end
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │     CE      │  GoalNode.report upsert
                    │ commit_goal │──► goal_report_committed
                    │   _report   │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │ Autopilot   │  project → LLM judge → verdict + DAG ops
                    │  Service    │──► accept / send_back / fail
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  LoopRail   │  deterministic notify (goal_completed, …)
                    └─────────────┘
```

Control-plane split:

- **Structure & schedule**: LoopRail + dispatch + CE status/deps.
- **Evidence SoT**: StrangeLoop ledger → CE `GoalNode.report`.
- **Judgment & soft plan**: Autopilot on `goal_report_committed` only.

---

## Components

### 1. StrangeLoop finalize (report author)

On any loop end (completed, failed, cancelled, crash/max_iter), persist a report in the StrangeLoop ledger. Minimum fields when work was thin or aborted:

- `outcome` (done / blocked / failed / cancelled / crashed)
- short `summary`
- optional claimed deliverables / effects / refs already known to the loop

No host process invents a parallel forensic narrative by scanning the workspace.

### 2. CE `commit_goal_report`

- Upsert serialized report onto `GoalNode.report`.
- Assign/bump `report_revision` (monotonic per goal).
- Emit canonical **`goal_report_committed`** (normalize existing `GoalReportEvent` / `AUTOPILOT_GOAL_REPORTED` into one Autopilot subscription contract; avoid dual judges).
- Status updates may accompany the commit but **must not** be the judge trigger by themselves.

### 3. Report projector

Pure function: `(GoalNode description, GoalNode.report, DAG slice) → judge prompt / structured context`.

Rules:

- Include only CE-resident data.
- Do not call tools, open workspaces, or re-run evidence gather.
- Truncate large ledger blobs by structured preference (summary → effects → step highlights), not by re-summarizing from git.

### 4. Completion judge (AutopilotService handler)

Structured LLM result:

```text
verdict: accept | send_back | fail
reasoning: str          # send_back brief when applicable
dag_ops: list[DagOp]    # optional, bounded
```

Bounded `DagOp` kinds:

| Op | Allowed |
|----|---------|
| `wire_depends` / `unwire_depends` | yes |
| `set_priority` | yes |
| `update_pending_brief` / pending-plan fields | yes |
| `spawn_goal` / `cancel_goal` | only if matching existing rail/monitor allowlists |
| free-form decompose/merge/new topology | **no** |

Apply order: validate ops → apply CE mutations → apply verdict (accept / send_back / fail) → notify rail.

### 5. Dispatch loop

Claims ready goals and runs workers. **Must not** invoke consensus/judge inline on worker return. Worker return’s job is ledger→CE report commit (or ensure commit happened).

### 6. LoopRail executor

Unchanged deterministic `flow[]` advancement on rail events after Autopilot finalizes the verdict. Judge does not select builtins.

---

## Data flow

1. Rail binds job → `plan_milestones` / fan-out / integrate / … per YAML.
2. Dispatch runs a ready subgoal in StrangeLoop.
3. Loop ends → ledger report → `CE.commit_goal_report` → `goal_report_committed`.
4. Autopilot handler (idempotent):
   - if goal already terminal for this `report_revision` → no-op
   - project CE report + DAG slice
   - optional deterministic gate (WavePlan, etc.)
   - else LLM judge → `dag_ops` + verdict
5. On `accept`: mark goal completed in CE (if not already), notify rail `goal_completed`.
6. On `send_back`: `CE.send_back_goal(reason=reasoning)`, notify `goal_send_back`; pending plan/briefs updated via `dag_ops` when provided.
7. On `fail`: CE fail + rail/monitor recovery paths (existing budgets).

---

## Error handling

| Case | Behavior |
|------|----------|
| Loop end without report | Worker/host writes minimal report; retry commit |
| Report still missing | No Autopilot LLM; engine recovery / retries only |
| Judge LLM failure | Fail closed to host recovery (do not silent-accept) |
| Duplicate commit event | Idempotent on `(goal_id, report_revision)` |
| Invalid `dag_ops` | Drop/reject illegal ops; still apply verdict if safe, or fail closed if ops were required for consistency |
| `max_send_backs` exhausted | Fail goal (existing budget) |
| Deterministic gate fail (e.g. missing WavePlan) | `send_back` or `fail` without needing workspace scrape |

---

## Migration

1. Introduce `commit_goal_report` + canonical event; ensure all loop-end paths write a report.
2. Add Autopilot subscriber/handler with projector + judge + bounded DAG ops.
3. Dual-run shadow mode (optional): log old vs new verdict without applying new path.
4. Cut over: remove inline `_apply_consensus_and_finalize` wire consensus from worker completion; worker completion only ensures report commit.
5. Keep structural WavePlan gate as CE/rail-state check inside the handler.
6. Update tests that assumed post-worker consensus inputs from synthesized wire strings.

---

## Testing

**Unit**

- Projector includes report fields and excludes workspace/tool side effects.
- Idempotent handler for duplicate `(goal_id, report_revision)`.
- `dag_ops` allowlist validation (illegal spawn rejected).
- Send_back applies judge `reasoning` as rework brief.

**Integration**

- Maker completes → report commit → accept → rail `spawn_integrate`.
- Thin/minimal report → send_back; goal re-queued with reasoning; no evidence-follow-up turn.
- Crash-minimal report → fail or send_back without host git probes.
- Accept + `update_pending_brief` / wire op updates CE pending plan before next dispatch.

**Regression**

- Dispatch/worker completion path does not call legacy consensus entrypoints after cutover.
- Bare status `active`/`pending` transitions do not invoke the judge.

---

## Success criteria

- Autopilot LLM judgment runs only after CE goal report commit.
- Judge never opens the workspace or starts a collect-evidence sub-loop.
- Rail phase order remains YAML-deterministic.
- Pending CE plan can be revised in-band with judgment via bounded ops.
- Integrate/completion thrash from “thin narrative vs re-probe” is addressable by trusting ledger reports and send_back briefs grounded in that report.

---

## Open points (resolved in brainstorm)

| Question | Resolution |
|----------|------------|
| Replace consensus? | Light LLM on CE report projection; keep send_back/fail |
| Trigger | Pure report-commit |
| Missing report | Always write minimal; else engine recovery, no LLM |
| Rail after verdict | Deterministic; send_back uses same reasoning |
| Scope | Broad event + dispatch/judgment refactor |
| DAG revise | Bounded ops (B) |

---

## Suggested spec touchpoints (post-draft)

- Revise RFC-204 consensus section toward report-commit judgment.
- Align RFC-625 `GoalNode.report` / monitor unification with commit event contract.
- Align RFC-231 rail notify sequencing (after Autopilot verdict, not parallel re-judge).
- Implementation guide for cutover + allowlisted `DagOp` application.

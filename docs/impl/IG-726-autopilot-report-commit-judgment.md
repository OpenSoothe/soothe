# IG-726: Autopilot report-commit judgment

**Created**: 2026-08-08  
**Status**: Implemented (P0–P3 production)  
**Related**: [RFC-204 §1.3](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[RFC-231](../specs/RFC-231-looprail-rail-exec.md),
design draft
[2026-08-08-autopilot-report-commit-judgment-design.md](../drafts/2026-08-08-autopilot-report-commit-judgment-design.md),
[IG-725](IG-725-remove-evidence-turns-trust-sloop.md),
[IG-710](IG-710-consensus-trust-sloop-response.md),
[IG-707](IG-707-autopilot-automatic-consensus-no-operator-suspend.md)

---

## Goal

Cut Autopilot per-goal completion over to **CE report commit** as the sole
LLM judgment entrypoint:

1. StrangeLoop loop end always yields a ledger-backed report on CE
   (`GoalNode.report` + `report_revision`).
2. CE emits `goal_report_committed`.
3. AutopilotService judges from a **projection of that CE report** (accept /
   send_back / fail + optional bounded DAG ops).
4. No second evidence collection; no judgment on bare status churn; LoopRail
   stays deterministic for phase verbs.

---

## Background

IG-725 removed evidence-follow-up turns but judgment still ran inline on the
worker wire `evidence_summary` via `_apply_consensus_and_finalize`. Specs now
require report-commit SoT (RFC-204 §1.3). Thin wire narratives still caused
send_back thrash when the loop had already recorded work in its ledger.

---

## Design rules (MUST)

1. **Always commit a report** on any loop end (completed / failed /
   needs_replan / crash-minimal) before Autopilot LLM judgment.
2. **Sole trigger**: judgment runs after `commit_goal_report` for that
   `(goal_id, report_revision)`. Bare `pending`/`active` MUST NOT judge.
3. **Judge input**: CE projection only (goal description + `GoalNode.report`
   + DAG slice for ops). Host MUST NOT open the workspace for this gate.
4. **Verdict**: `accept | send_back | fail`; send_back brief = same call
   `reasoning`.
5. **Bounded `dag_ops`**: wire/unwire deps, set priority, update pending
   briefs; spawn/cancel only via existing allowlists. No free-form topology.
6. **Deterministic gates** (e.g. WavePlan) remain host-owned and run in the
   same finalize path using CE/rail state + committed report fields.
7. **Idempotent** on `(goal_id, report_revision)`.
8. **Missing report after best-effort minimal write** → no LLM; engine
   recovery only.

---

## Target flow

```text
GoalCompletionChunk / loop end
  → build report dict from ledger wire (summary, findings, effects, outcome)
  → CE.commit_goal_report(goal_id, report) → report_revision++
  → emit goal_report_committed
  → Autopilot handler (or same-stack finalize after commit):
        project(CE report) → [WavePlan gate |] LLM judge → dag_ops? → verdict
        accept → complete_goal → rail goal_completed
        send_back → send_back_goal(reasoning) → rail goal_send_back
        fail → fail_goal → rail / recovery
```

v1 may keep the handler co-located in `AutopilotService` immediately after
`commit_goal_report` (same call stack) as long as the SoT is CE report and
there is no parallel wire-only judge. A bus subscriber can follow once the
commit API is stable.

---

## Implementation plan

### P0 — CE commit API

- [x] Add `GoalNode.report_revision: int = 0`
- [x] `ContextEngine.commit_goal_report(goal_id, report: dict) -> int`
  - upsert `report`, bump revision, touch goal
- [x] Helper to build minimal report from completion chunk fields
  (`soothe.autopilot.verify.report_projection`)

### P1 — Autopilot finalize cutover

- [x] Before judge: always `commit_goal_report` from chunk/contribution
- [x] `project_goal_report_for_judge(report) -> str` (summary/findings/effects)
- [x] `evaluate_goal_completion` uses projection (prompt: Goal Report)
- [x] Document `_apply_consensus_and_finalize` as report-commit finalize
  (symbol kept for callers/tests)
- [x] needs_replan / fail paths also commit a minimal report when possible

### P2 — Bounded DAG ops

- [x] Extend structured judge result with optional `dag_ops: list[DagOp]`
- [x] Validate + apply: wire/unwire, priority, pending brief updates
- [x] Reject illegal spawn/cancel unless allowlisted (default deny)

### P3 — Production hardening

- [x] Emit `InternalGoalReportCommittedEvent` from `_commit_loop_end_report`
  (same-stack finalize remains; bus is observability + future subscribers)
- [x] `GoalNode.judged_report_revision` + skip re-judge on same revision /
  already-terminal goals
- [x] No-completion-chunk path commits minimal CE report before `fail_goal`
- [x] `AutopilotConfig.judge_allow_structural_dag_ops` + config template sync
- [x] Unit: commit bumps revision; projector; finalize commits before judge
- [x] Unit: judge prompt built from CE Goal Report; emit + idempotency
- [x] Accept path still completes (IG-725 / wave-plan gate suites)
- [x] Align IG-680/IG-697 tests to report-commit semantics
- [x] Unit: bounded dag_ops apply / allowlist skip / allowlisted spawn
- [x] `./scripts/verify_finally.sh`

---

## Non-goals

- Second reactor LLM choosing LoopRail verbs
- Full event-bus rewrite of dispatch in P0–P1 (same-stack after commit OK)
- Changing WorkerPool / sticky affinity
- Job maturity (RFC-230) — stays job-layer

---

## Acceptance criteria

- [x] Every successful judge path reads `GoalNode.report` after commit
- [x] No Autopilot LLM judgment without a committed report (skip if commit empty)
- [x] WavePlan architecture gate still works
- [x] Send_back uses judge `reasoning`
- [x] `goal_report_committed` emitted; judge idempotent on revision / terminal
- [x] Crash / no-completion path still commits a minimal report
- [x] verify_finally green

---

## Revision history

| Date | Change |
|------|--------|
| 2026-08-08 | Initial IG from report-commit design + RFC refine commit |
| 2026-08-08 | P0/P1 implemented: commit_goal_report, projection, finalize cutover |
| 2026-08-08 | P2: bounded dag_ops on judge + apply (spawn/cancel deny-by-default) |
| 2026-08-08 | P3: bus emit, judged_report_revision, crash commit, config allowlist |

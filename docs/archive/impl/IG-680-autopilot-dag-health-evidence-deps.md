# IG-680: Autopilot DAG Health Guardrails, Consensus Evidence, and Decompose Deps

**Created**: 2026-08-04  
**Status**: Implemented  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-624](../specs/RFC-624-context-engine.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[IG-678](IG-678-autopilot-ce-rails-production-readiness.md),
[IG-677](IG-677-autopilot-job-loop-index.md),
[analysis: goal intake / DAG flow](../analysis/autopilot_goal_intake_dag_flow.md)

**Eval evidence**: `/tmp/soothe-autopilot-eval/EVAL_REPORT.md` (2026-08-04 long-running
taskkit job `22f98dd1`)

---

## Executive Summary

Close four production gaps found in a long-running autopilot eval where the
**workspace deliverable succeeded** but the **job terminal status was
misleading** (`cancelled` / false `send_back` / premature `failed`):

| ID | Gap | Severity |
|----|-----|----------|
| AH-1 | DAG health auto-cancels job roots / live umbrellas via `remove_goals` | **P0** |
| AH-2 | Consensus judges empty / wrong-path evidence (`files_touched` stub; no workspace inherit) | **P0** |
| AH-3 | LLM decompose creates pipeline subgoals with `depends_on=[]`; health cannot wire deps | **P1** |
| AH-4 | Post-completion + health re-decompose explode the DAG after design completes | **P1** |

This IG is the implementation backlog for those findings. Spec errata live in
RFC-625 / RFC-222 / RFC-204 (see Related). IG-678 Phase 3 soak remains optional;
these fixes are **blocking** for trustworthy multi-goal jobs even before soak.

---

## Problem (eval causal chain)

```text
Health/LLM decompose root
  → subgoals with deps=none + missing parent.workspace
  → parallel test/implement/review; workers land in isolated ws_* dirs
  → consensus send_back / "no narrative" despite on-disk success
  → DAG clutter → health marks umbrella "redundant"
  → CE.cancel_goal(root, dag_health_verification)
  → job cancelled while workspace SUCCESS; design keeps spawning children
```

### AH-1 — Health cancels umbrella roots

**Symptom:** Root `22f98dd1` cancelled with reason `dag_health_verification`
while children were still non-terminal.

**Code today:**

- `GoalDAGVerifier.apply_health_report` maps `suggest_remove` →
  `ContextEngine.cancel_goal(..., reason="dag_health_verification")` with **no**
  root / subtree / operator guard (`goal_dag_verifier.py`).
- Removals do **not** go through `AutopilotService.cancel_goal` (no worker
  cascade / reservation release).
- Merge suggestions are log-only (never applied).

**Spec drift:** RFC-625 §7 describes `remove_goal` as validating no dependents;
runtime health apply does not enforce that, and treats “scope covered by
children” as removable.

### AH-2 — Consensus ignores on-disk evidence

**Symptom:** Repeated `send_back` citing “no TASK.md read / no modules”; test
goal failed with `no narrative` while `/tmp/soothe-autopilot-eval` already had
passing pytest and `SUMMARY.md`.

**Code today:**

- `_runner_autopilot_worker._build_contribution` leaves `files_touched` /
  `tool_call_stats` empty (explicit stub).
- `_apply_consensus_and_finalize` uses `evidence_summary or goal.description`
  as the “agent response” — empty evidence becomes a restatement → send_back.
- `GoalPlanningSubengine.create_subgoals` does **not** copy `parent.workspace`;
  subgoals resolve to per-loop `~/.soothe/data/workspaces/anonymous/ws_*`.
- Headless veritas defer / empty `PlanResult` → fail with literal `"no narrative"`.

### AH-3 — Flat `depends_on` on decompose

**Symptom:** Parse → design → implement → test → review all ready at once;
worker pool saturated at `max_loops`; test ran before implement finished.

**Code today:**

- `apply_llm_subgoals` trusts LLM `depends_on` (usually `[]`).
- Health schema has no `wire_dependencies` action; `ContextEngine.update_dependencies`
  exists in RFC-625 but is unused by `apply_health_report`.
- Priority ordering is not a hard gate under parallel dispatch.

### AH-4 — Over-decomposition after completion

**Symptom:** After design `3fb6e354` completed, children kept spawning (ADRs,
schemas, API contracts, more tests) even after the deliverable existed.

**Code today:**

- Uncoordinated spawners: post-completion handler + health `suggest_decompose`
  + worker `goal_directives`.
- Post-completion often sees empty CE step counts → LLM assumes unfinished work.
- Follow-up `source='reflection'` may fail GoalNode validation (fails open while
  health still decomposes).
- No deliverable / idempotency guard (no artifact probe; no description dedupe).

---

## Non-goals

- Full dreaming distillation product (still IG-678 / follow-on).
- Auto-applying LLM merge suggestions without a separate design pass.
- Fine-grained per-path file locks (RFC-222 still defers to workspace reservation).
- Changing StrangeLoop invariant (one goal per worker loop).

---

## Design principles

1. **Job roots are sacred** — health may suggest cleanup; it must not cancel an
   active or suspended job root (or any goal with non-terminal descendants)
   without an explicit operator/rail action.
2. **Workspace is lineage** — every decomposed child inherits the parent job
   workspace unless the intake explicitly overrides it.
3. **Consensus needs grounded evidence** — never judge on goal-description echo;
   prefer contribution + workspace artifact probes.
4. **Pipeline order is structural** — decompose of multi-phase work must produce
   hard `depends_on` edges (LLM optional; deterministic chain as fallback).
5. **Decompose is idempotent** — at most one post-completion / health decompose
   wave per completed goal per budget window; dedupe by normalized description.

---

## Phase 0 — P0 correctness (blocking)

| ID | Work | Closes |
|----|------|--------|
| P0-1 | Health remove guardrails: refuse auto-cancel when `parent_id is None` (job root), or any non-terminal descendant exists, or status is `active`/`suspended` with live workers; only auto-remove cancelled/failed clutter with zero dependents | AH-1 |
| P0-2 | Route approved removals through `AutopilotService.cancel_goal` (cascade + reservation) or introduce CE `archive` / soft-remove that does not mark job failed for operators | AH-1 |
| P0-3 | Inherit `workspace` (and job lineage) in `create_subgoals` / `apply_llm_subgoals` from parent | AH-2 |
| P0-4 | Populate `GoalDispatchContextContribution.files_touched` / tool stats from execute ledger (or equivalent runner telemetry) | AH-2 |
| P0-5 | Consensus: if `evidence_summary` empty, do **not** fall back to `goal.description`; suspend or run workspace artifact probe when `goal.workspace` set | AH-2 |
| P0-6 | Map headless clarification / empty PlanResult to `needs_replan` or `suspend`, not `failed` + `"no narrative"` | AH-2 |

### Acceptance (P0)

- [x] Health report suggesting remove of an active root with children is **not**
      applied; root stays non-cancelled
- [x] Subgoal dispatch uses the same client workspace as the job root
- [x] Consensus with empty evidence cannot `send_back` solely because response
      equals the goal text
- [x] Unit tests cover remove guards + workspace inherit + consensus empty-evidence path

---

## Phase 1 — Pipeline deps + decompose budget (P1)

| ID | Work | Closes |
|----|------|--------|
| P1-1 | After pipeline-style decompose, deterministically chain sibling order when LLM omits deps (e.g. sequential `depends_on` by list order, or phase tags) | AH-3 |
| P1-2 | Extend health report with `wire_dependencies: [{goal_id, depends_on}]` and apply via `CE.update_dependencies` in `apply_health_report` | AH-3 |
| P1-3 | Tighten verifier prompts/examples: every decomposed subgoal MUST include `depends_on` when a pipeline is implied | AH-3 |
| P1-4 | Decompose budget: max one health/post-completion decompose per completed goal per N minutes; hash-dedupe descriptions under the same parent | AH-4 |
| P1-5 | Fix follow-up `GoalNode.source` (`reflection` → allowed or map to `decomposition`) | AH-4 |
| P1-6 | Skip post-completion / health decompose when workspace deliverable probe passes (config-driven paths or VERIFY criteria) | AH-4 |
| P1-7 | Feed post-completion context from worker contribution, not empty CE step counters alone | AH-4 |

### Acceptance (P1)

- [x] Five-phase taskkit-style decompose produces a ready-chain (test not ready
      until implement completes) under unit/integration fixture
- [x] Completing a design goal twice does not double-spawn identical children
- [x] Health can repair a flat pipeline by applying `wire_dependencies`

---

## Phase 2 — Eval regression + docs

| ID | Work | Closes |
|----|------|--------|
| P2-1 | Daemon/integration soak: submit multi-phase job → assert deps edges, shared workspace, root not health-cancelled, consensus accept when artifacts exist | AH-1…AH-4 |
| P2-2 | Operator notes: health remove is clutter-only; how to interpret job vs workspace success | — |
| P2-3 | Close RFC-625 / RFC-222 / RFC-204 errata checkboxes once code lands | — |

### Acceptance (P2)

- [x] Unit regression suite covers root protect / workspace inherit / consensus
      grounding / deps chain / decompose cooldown (full live soak remains IG-678 P3)
- [x] Spec status notes match shipped behavior (RFC-204/222/624/625 errata)

---

## Key files

| Area | Paths |
|------|--------|
| Health apply | `packages/soothe/src/soothe/autopilot/goal_dag_verifier.py` |
| Prompts / models | `verifier_reasoner.py`, `verifier_prompts.py`, `monitor_models.py` |
| Subgoal create | `packages/soothe/src/soothe/context/planning_goal_planner.py` |
| Consensus | `packages/soothe/src/soothe/autopilot/consensus.py`, `service.py` (`_apply_consensus_and_finalize`) |
| Worker evidence | `packages/soothe/src/soothe/runner/_runner_autopilot_worker.py` |
| CE deps API | `packages/soothe/src/soothe/context/engine.py` (`update_dependencies`, `cancel_goal`) |
| Tests | `packages/soothe/tests/unit/core/autopilot/`, new health-guard + workspace-inherit cases |
| Specs | RFC-204 / 222 / 625 (+ this IG) |

---

## Suggested order

```text
P0-1,P0-2  health remove guards (stops false job cancel)
P0-3       workspace inherit
P0-4,P0-5,P0-6  evidence + consensus honesty
    ↓
P1-1…P1-3  deps chain + wire_dependencies
P1-4…P1-7  decompose budget + post-completion honesty
    ↓
P2-*       eval regression + RFC checkbox closeout
```

---

## Verification

After each phase:

1. Cleanse related dead stubs only (AGENTS rule 6).
2. `./scripts/verify_finally.sh`
3. Phase acceptance checkboxes above.

Do not weaken consensus tests by stubbing empty evidence as accept.

---

## Exit criteria

1. Health cannot cancel a job root or a goal with live descendants.
2. Decomposed children share the parent workspace by default.
3. Consensus decisions are grounded in contribution and/or workspace probes.
4. Pipeline decompose produces hard dependency edges (or health can wire them).
5. Post-completion / health decompose is budgeted and idempotent.
6. RFC-204 / 222 / 625 errata for these gaps marked resolved.

When met, set **Status: Implemented** and keep IG-678 Phase 3 soak as optional
broader evidence (Postgres crash E2E, rail soak).

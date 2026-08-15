# RFC-230: Job Maturity Assessment for Autopilot Rails

**RFC**: 230
**Title**: Job Maturity Assessment for Autopilot Rails
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-08-05
**Updated**: 2026-08-08
**Authors**: Soothe Team
**Depends on**: RFC-204, RFC-222, RFC-228, RFC-624, RFC-625, RFC-630
**Related**: [RFC-231](RFC-231-looprail-rail-exec.md) (LoopRail + Rail Exec;
§8–§9 streaming spawn / deprecated wave barriers),
[RFC-232](RFC-232-waveplan-flat-semistructured-ingest.md) (flat WavePlan wire),
LoopRail design draft (`docs/drafts/2026-07-11-loop-rail-design.md`; promoted by RFC-231),
design draft `docs/drafts/2026-08-08-streaming-slice-dag-worktree-lifecycle-design.md`,
design draft `docs/archive/drafts/2026-08-08-autopilot-report-commit-judgment-design.md`,
IG-678, IG-680, IG-687, IG-691, IG-692

## Abstract

Define **job-level maturity assessment** as a host responsibility of
`AutopilotService` + `ContextEngine`, distinct from per-goal **report-commit
judgment** (RFC-204 §1.3) and from StrangeLoop execution. Maturity may use
host workspace probes at the **job** layer; per-goal judgment MUST NOT
re-collect evidence and trusts the CE GoalReport projection. Maturity
snapshots drive LoopRail guards (`needs_feedback`, `job_complete`) and the
`acceptance_met` latch.
Rail-bound jobs spawn follow-up goals **only** through LoopRail builtins;
`AutopilotMonitor` / `GoalDAGVerifier` must not invent phases on rail jobs.
Production emits `dag_idle` so rails can complete job roots that are never
dispatched as workers.

## 1. Problem

Incident class (job `20999e64`, `greenfield-system`):

| Observation | Gap |
|-------------|-----|
| Wave makers + integrate + (ad hoc) review/QA completed | Workflow topology progressed |
| Quality-gate narrative claimed PASS | Per-goal report-commit judgment accepted a writeup |
| GOAL demos (`return N`, `printf`) failed / ELF header-only | No job-level acceptance check |
| Root stayed `pending`; scheduler skipped rail root | No `dag_idle` → `complete_job` |
| `RailJobState.acceptance_met` stayed `false` forever | Flag never written from evidence |
| Verifier decomposed review/QA outside the rail | Dual orchestration paths |

Rails today are **phase machines** (tags, pending counts). They do not assure
**product maturity** against the job contract (`GOAL.md` / `verification_rules`
/ architecture milestones). RFC-228 documents `verification_rules` but leaves
structured evaluation as a future enhancement; that enhancement is this RFC.

## 2. Goals

1. **JobMaturityAssessor** in Autopilot evaluates the job root against an
   acceptance contract and writes a durable `JobMaturitySnapshot` on CE.
2. Snapshot updates **`acceptance_met`** on `RailJobState` (and CE mirror).
3. LoopRail guards consume maturity; builtins spawn the next goals.
4. **Rail exclusivity** for rail-bound jobs: verifier/monitor must not create
   goals; at most forward events / health without decompose-spawn.
5. Production **`dag_idle`** when a rail job has no runnable descendants.
6. Prefer **structured LLM contract judgment** (RFC-630) over language-specific
   executable probes. Workspaces may be coding, writing, planning, research, or
   other domains — `acceptance_met` is latched only from structured maturity
   verdicts, never from cargo/pytest/fixture exit codes alone.

## 3. Non-goals

- StrangeLoop learning DAG shape, siblings, or rail policy (RFC-222 invariant).
- Replacing LoopRail with more verifier LLM decompose.
- Hardcoding language toolchains (cargo/pytest/npm/…) as the job accept latch.
- Specifying LoopRail / Rail Exec itself (see **RFC-231**); maturity hooks here
  remain the contract rails and Exec consume.

## 4. Architectural invariant

> **StrangeLoop executes one goal and writes a ledger report. CE commits the
> report. AutopilotService judges on `goal_report_committed` (RFC-204 §1.3).
> LoopRail decides *when*. ContextEngine applies *what* to the DAG.
> AutopilotService also schedules workers and runs job maturity assessment.**

```text
goal_report_committed
  → per-goal report-commit judgment (RFC-204)  # accept / send_back / fail [+ dag_ops]
  → CE.complete_goal (if accept)
  → notify_rail(goal_completed)                # only spawner for rail jobs
  → if qa/verify-class: JobMaturityAssessor → CE + rail acceptance_met
  → if job idle: notify_rail(dag_idle)
  → rail guard → Rail Exec catalog verb (feedback / complete_job / next wave)
```

Child accept **≠** job accept. A QA narrative cannot latch `acceptance_met`
without the assessor.

## 5. Acceptance contract sources

Resolved in order for contract text (all available sources feed the assessor
evidence pack):

| Priority | Source | Notes |
|----------|--------|-------|
| 1 | `GoalNode.verification_rules` | From `job_create` (RFC-228) |
| 2 | Workspace `GOAL.md` (or submit text when it *is* GOAL body) | Common operator pattern |
| 3 | Job DAG outcomes | Child statuses / roles / tags / descriptions |
| 4 | Shallow workspace inventory | Presence/absence signal only — no command runners |
| 5 | Latest QA/verify StrangeLoop response | Optional narrative from the trigger goal |

Assessor stores the resolved criteria list inside the snapshot (not only the
raw string).

## 6. Data model

### 6.1 `JobMaturitySnapshot` (CE, on job root)

```text
JobMaturitySnapshot {
  assessed_at: datetime
  level: scaffold | wave_partial | wave_integrated
       | acceptance_candidate | accepted | blocked
  acceptance_met: bool
  criteria: list[{
    id: str
    description: str
    status: pass | fail | unknown | skipped
    evidence: str          # criterion evidence excerpt
  }]
  blockers: list[str]
  suggested_rail_signal: needs_feedback | slices_ready_to_spawn
                       | job_complete | none
                       # legacy alias ready_for_next_wave MUST NOT withhold
                       # ready slice spawn (RFC-231 §8–§9)
  probe_summary: str       # assessment summary text
}
```

Persisted on the root `GoalNode` (field or CE sidecar keyed by job id). Mirrored
into `RailJobState.acceptance_met` and optional `RailJobState` maturity blob for
guard short-circuits / restart (IG-691 `rail_state.json` pattern).

### 6.2 Maturity levels (informative)

| Level | Meaning |
|-------|---------|
| `scaffold` | Little contract evidence; early DAG / empty workspace |
| `wave_partial` | Some makers done; job branch not fully landed (informative name; not a spawn barrier — RFC-231 §9) |
| `wave_integrated` | Job-branch merges progressed; acceptance not met (informative; host merge replaces batch integrate) |
| `acceptance_candidate` | Verify-class goal completed; contract not yet met |
| `accepted` | `acceptance_met=true` |
| `blocked` | Hard contract failure / budget / operator suspend |

Levels are derived; **`acceptance_met` is the latch rails trust**.

## 7. JobMaturityAssessor

### 7.1 Placement

- Package: `soothe` (host), under `autopilot/verify/job_maturity.py`.
- Invoked by `AutopilotService` (not StrangeLoop, not rail interpreter).
- Reads CE DAG + workspace inventory + contract text; writes CE snapshot + rail
  state via existing rail executor annotate/persist APIs.
- Uses the Autopilot judgment / light model (configured via the daemon
  consensus/reflection model role).

### 7.2 Evidence pack (deterministic gather)

Host gathers **facts**; the LLM judges the contract:

| Source | Role |
|--------|------|
| `verification_rules` / `GOAL.md` | Acceptance contract text |
| Job DAG child one-liners | Status / role / tags / descriptions |
| Shallow workspace inventory | File/dir names only (capped) — no `cargo`/`pytest`/shell |
| Latest QA/verify response | Optional StrangeLoop narrative from the trigger goal |

Structured `GoalEffect` claims on the dispatch contribution / bundle
(`PlanResult.effects` → contribution → projector `prior_effects`) remain
**wire / hydration metadata only** — never a consensus or maturity latch
(IG-710 / IG-711 / IG-712). Host must not infer effects from prose or the
filesystem.

### 7.3 Structured LLM latch

`JobMaturityAssessor.assess` calls structured output
(`MaturityAssessmentVerdict`: `acceptance_met`, `level`, `criteria`,
`blockers`, `suggested_rail_signal`, `reasoning`). **No keyword judgment of
agent prose** for free-text decision parsing (RFC-630).

Fail closed: missing model or LLM failure → leave `acceptance_met=false`
(do not invent accept). Language-specific command runners are **out of scope**
for the host latch.

### 7.4 When to run

| Trigger | Behavior |
|---------|----------|
| Consensus **accept** on goal tagged `qa` or (`feedback` ∧ `verify`) | Full assess |
| Before evaluating `job_complete` on `dag_idle` | Re-assess (cheap cache OK if workspace mtime unchanged) |
| Operator resume / explicit re-verify | Full assess |

Maker / integrate / review completions do **not** set `acceptance_met=true`.

## 8. LoopRail integration

Normative LoopRail / Rail Exec: **RFC-231**. Maturity remains a host latch that
guards and verb recipes consume; this section only specifies the maturity
contract.

### 8.1 Guards

Structural short-circuits MUST read CE/rail maturity:

- `needs_feedback`: verify/QA completed ∧ `not acceptance_met` ∧ rounds remain ∧ not inflight
- `job_complete`: idle descendants ∧ `acceptance_met` (or exhausted feedback under operator policy)
- `slices_ready_to_spawn`: catalog has unspawned slices whose deps are satisfied
  (RFC-231 §8.1 / §9.3). Legacy name `ready_for_next_wave` MUST NOT be used as a
  barrier that keeps ready slices out of the CE DAG.

Empty trigger tags after restart: **fail closed** — repair from CE `rail_tags`
(IG-691) before skipping phase transitions.

### 8.2 Catalog verbs / Rail Exec

- Enrich `qa_verify` / feedback verify goal descriptions from maturity criteria
  (not only `"QA verify for job {id}"`) — prefer YAML verb-body briefs (RFC-231)
  over hardcoded executor strings.
- `complete_job` requires `acceptance_met` (or explicit exhausted-feedback policy
  recorded on the snapshot).
- `spawn_feedback_cycle` skipped when `acceptance_met` (already coded; make the
  latch real).

### 8.3 Production `dag_idle`

`AutopilotService` MUST emit `notify_rail("dag_idle", job_id)` when:

- Job root has `rail_id`
- No active/pending descendants (except root)
- No in-flight workers for that job subtree

Test harness already ticks `dag_idle`; production must match.

## 9. Rail exclusivity (Monitor / Verifier)

For any goal whose job root has `rail_id`:

| Operation | Allowed? |
|-----------|----------|
| Health: wire_deps among non-root, remove cancelled clutter | Yes (careful) |
| Health: reset rail **root** to runnable | **No** |
| Health / post-completion: **create** subgoals / decompose | **No** |
| Post-completion: forward event to rail only | Yes |

Jobs without `rail_id` keep current monitor/verifier behavior (RFC-625).

This matches LoopRail design §11 (Monitor forwards events; rail owns
job-scoped restructuring).

## 10. Report-commit judgment relationship (RFC-204)

Per-goal report-commit judgment (RFC-204 §1.3): **goal text + CE GoalReport
projection** (StrangeLoop ledger) only. Host workspace probes are **not**
per-goal judgment inputs (they belong to this RFC’s job maturity assessor).

Unchanged for **non-rail child** goals: accept / send_back / fail (IG-707).

Rail-bound children (IG-693):

1. Child accept does not complete the job root.
2. Send-back budget exhaustion → **`failed`** + LoopRail `goal_failed` (not
   silent suspend). Rails may `retry_maker` / equivalent — Autopilot does not
   invent git/commit/pytest accept overrides for rail or non-rail judgment.
3. Job acceptance is latched only by the maturity LLM assessor (job latch),
   never as soft/hard per-goal judgment overrides (no git/pytest hard-accept
   on the report-commit path).

## 11. IPC / observation (RFC-228)

- `job_create.verification_rules` remains write-once opaque text at submit;
  evaluation semantics are defined here (not “LLM only at completion”).
- `job_status` / `autopilot_top` SHOULD expose maturity `level`,
  `acceptance_met`, and top blockers.
- For **rail** jobs, absence of `verification_rules` does not mean “children
  done ⇒ root done” — rail + maturity apply. Non-rail jobs may complete when
  all children are terminal if no other policy applies.

## 12. Failure modes

| Failure | Behavior |
|---------|----------|
| Maturity model missing | Fail closed: `acceptance_met=false`; surface blocker |
| Assessor / LLM exception | Log; leave prior snapshot; do not set `acceptance_met=true` |
| `dag_idle` but not accepted | Rail may `spawn_feedback_cycle` or suspend with blockers |
| Max feedback rounds | Snapshot `blocked` or policy-complete without accept; surface in status |
| Tag loss | Hydrate from CE (IG-691); refuse silent phase skip |

## 13. Phased delivery

| Phase | Scope |
|-------|--------|
| **P0** | Emit `dag_idle`; write `acceptance_met`; ban verifier spawn on rail jobs |
| **P1** | Wire `verification_rules` / GOAL.md into assessor; enrich QA goal text; tag repair |
| **P2** | Maturity levels in CE + top/CLI; feedback driven by snapshot |
| **P3** | LLM-primary contract judgment for all domains (IG-711); drop coding probe latch |

Implementation tracking: **IG-692** (P0–P2), **IG-711** (LLM-primary latch).

## 14. Acceptance criteria (spec)

- [ ] Rail job with all children complete and `acceptance_met=false` does not
      leave root pending forever without `dag_idle` / feedback / blocked status
- [ ] `acceptance_met=true` only after structured LLM maturity verdict
- [ ] Verifier cannot create review/QA goals under a `rail_id` job
- [ ] Greenfield `needs_feedback` / `job_complete` short-circuits observe the latch
- [ ] Unit tests for assessor + rail guard + idle emission; no user-facing
      IG/RFC strings in runtime logs

## 15. Revision history

| Date | Change |
|------|--------|
| 2026-08-05 | Initial draft from job `20999e64` hang + GOAL maturity gap analysis |
| 2026-08-05 | Clarify consensus: rail exhaust → fail+rail recovery (IG-693); no
  engine git/pytest hard-accept for rail jobs |
| 2026-08-06 | Flip latch to LLM contract judgment (IG-711); remove coding probe registry
  as accept mechanism; domain-agnostic workspaces |
| 2026-08-06 | Note GoalEffect wire metadata (IG-712); drop `build_files_touched` latch wording |
| 2026-08-08 | Align with report-commit judgment (RFC-204 §1.3); maturity remains
  job-layer only; rename §10 from “consensus”; drop legacy/compat hedges |

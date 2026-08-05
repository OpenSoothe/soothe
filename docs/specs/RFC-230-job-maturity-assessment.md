# RFC-230: Job Maturity Assessment for Autopilot Rails

**RFC**: 230  
**Title**: Job Maturity Assessment for Autopilot Rails  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-08-05  
**Authors**: Soothe Team  
**Depends on**: RFC-204, RFC-222, RFC-228, RFC-624, RFC-625, RFC-630  
**Related**: LoopRail design draft (`docs/drafts/2026-07-11-loop-rail-design.md`),
IG-678, IG-680, IG-687, IG-691, IG-692

## Abstract

Define **job-level maturity assessment** as a host responsibility of
`AutopilotService` + `ContextEngine`, distinct from per-goal consensus
(RFC-204) and from StrangeLoop execution. Maturity snapshots drive LoopRail
guards (`needs_feedback`, `job_complete`) and the `acceptance_met` latch.
Rail-bound jobs spawn follow-up goals **only** through LoopRail builtins;
`AutopilotMonitor` / `GoalDAGVerifier` must not invent phases on rail jobs.
Production emits `dag_idle` so rails can complete job roots that are never
dispatched as workers.

## 1. Problem

Incident class (job `20999e64`, `greenfield-system`):

| Observation | Gap |
|-------------|-----|
| Wave makers + integrate + (ad hoc) review/QA completed | Workflow topology progressed |
| Quality-gate narrative claimed PASS | Per-goal consensus accepted a writeup |
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
6. Prefer **structural / executable probes** (RFC-630); LLM only for residual
   non-machine criteria — never alone to set `acceptance_met=true`.

## 3. Non-goals

- StrangeLoop learning DAG shape, siblings, or rail policy (RFC-222 invariant).
- Replacing LoopRail with more verifier LLM decompose.
- Fully parsing arbitrary natural-language GOAL into a complete test suite in v1
  (probe registry + optional fixture conventions; LLM residual OK).
- Promoting the LoopRail draft to an RFC in this document (referenced as draft;
  maturity hooks are specified here so rails can consume them).

## 4. Architectural invariant

> **StrangeLoop executes one goal. LoopRail decides *when*. ContextEngine
> applies *what* to the DAG. AutopilotService schedules workers and runs
> job maturity assessment.**

```text
goal_completed
  → per-goal consensus (RFC-204)          # child accept / send_back / suspend
  → CE.complete_goal (if accept)
  → notify_rail(goal_completed)           # only spawner for rail jobs
  → if qa/verify-class: JobMaturityAssessor → CE + rail acceptance_met
  → if job idle: notify_rail(dag_idle)
  → rail guard → CE builtin (feedback / complete_job / next wave)
```

Child accept **≠** job accept. A QA narrative cannot latch `acceptance_met`
without the assessor.

## 5. Acceptance contract sources

Resolved in order (first non-empty wins for criteria text; all available
sources may contribute probes):

| Priority | Source | Notes |
|----------|--------|-------|
| 1 | `GoalNode.verification_rules` | From `job_create` (RFC-228) |
| 2 | Workspace `GOAL.md` (or submit text when it *is* GOAL body) | Common operator pattern |
| 3 | Architecture / milestone artifacts | e.g. plan acceptance tables under `docs/` |
| 4 | Rail defaults | e.g. greenfield: build + tests + wave QA semantics |

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
    evidence: str          # probe output excerpt / path
  }]
  blockers: list[str]
  suggested_rail_signal: needs_feedback | ready_for_next_wave
                       | job_complete | none
  probe_summary: str
}
```

Persisted on the root `GoalNode` (field or CE sidecar keyed by job id). Mirrored
into `RailJobState.acceptance_met` and optional `RailJobState` maturity blob for
guard short-circuits / restart (IG-691 `rail_state.json` pattern).

### 6.2 Maturity levels (informative)

| Level | Meaning |
|-------|---------|
| `scaffold` | Workspace / crates / stubs; demos fail or absent |
| `wave_partial` | Some makers done; integrate incomplete |
| `wave_integrated` | Integrate (+ commit) done; acceptance not met |
| `acceptance_candidate` | Verify-class goal completed; probes mixed/unknown |
| `accepted` | `acceptance_met=true` |
| `blocked` | Hard probe failure / budget / operator suspend |

Levels are derived; **`acceptance_met` is the latch rails trust**.

## 7. JobMaturityAssessor

### 7.1 Placement

- Package: `soothe` (host), under `autopilot/` (e.g. `maturity.py`).
- Invoked by `AutopilotService` (not StrangeLoop, not rail interpreter).
- Reads CE DAG + workspace; writes CE snapshot + rail state via existing
  rail executor annotate/persist APIs.

### 7.2 Probe registry (structural first)

Pluggable probes selected by workspace markers:

| Marker | Probe examples |
|--------|----------------|
| `Cargo.toml` | `cargo build`, `cargo test`; optional GOAL fixtures (compile+run `return N`, printf/stdout) |
| `pyproject.toml` + `tests/` | Existing pytest probe (`evidence_grounding`) |
| Generic | Named binaries from GOAL; non-trivial artifact size/sections |

Probes return machine `pass|fail|skipped` + evidence string. **No keyword
judgment of agent prose** for latching acceptance (RFC-630).

### 7.3 LLM residual

Only for criteria that remain `unknown` after probes. Structured output:
per-criterion status + short reasoning. If any required criterion is still
`fail` or `unknown`, `acceptance_met` stays **false**.

### 7.4 When to run

| Trigger | Behavior |
|---------|----------|
| Consensus **accept** on goal tagged `qa` or (`feedback` ∧ `verify`) | Full assess |
| Before evaluating `job_complete` on `dag_idle` | Re-assess (cheap cache OK if workspace mtime unchanged) |
| Operator resume / explicit re-verify | Full assess |

Maker / integrate / review completions do **not** set `acceptance_met=true`.

## 8. LoopRail integration

### 8.1 Guards

Structural short-circuits MUST read CE/rail maturity:

- `needs_feedback`: verify/QA completed ∧ `not acceptance_met` ∧ rounds remain ∧ not inflight
- `job_complete`: idle descendants ∧ `acceptance_met` (or exhausted feedback under operator policy)
- `ready_for_next_wave`: existing greenfield rules; may require acceptance or feedback_done

Empty trigger tags after restart: **fail closed** — repair from CE `rail_tags`
(IG-691) before skipping phase transitions.

### 8.2 Builtins

- Enrich `qa_verify` / feedback verify goal descriptions from maturity criteria
  (not only `"QA verify for job {id}"`).
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

## 10. Consensus relationship (RFC-204)

Unchanged for **child** goals: accept / send_back / suspend.

Additions:

1. Child accept does not complete the job root.
2. For `qa` / `verify` goals, consensus grounding SHOULD include the latest
   probe excerpt when available (or run a light probe pre-consensus).
3. Structural override (e.g. pytest PASS) remains language-specific; Cargo/GOAL
   probes extend the same idea — still not narrative-only PASS.

## 11. IPC / observation (RFC-228)

- `job_create.verification_rules` remains write-once opaque text at submit;
  evaluation semantics are defined here (not “LLM only at completion”).
- `job_status` / `autopilot_top` SHOULD expose maturity `level`,
  `acceptance_met`, and top blockers (additive fields; backward compatible).
- Absence of `verification_rules` no longer means “complete when all children
  completed” for **rail** jobs — rail + maturity apply. Non-rail jobs may keep
  legacy “all children terminal” completion.

## 12. Failure modes

| Failure | Behavior |
|---------|----------|
| Probe timeout / tool missing | Criterion `unknown` or `skipped`; do not latch accept |
| Assessor exception | Log; leave prior snapshot; do not set `acceptance_met=true` |
| `dag_idle` but not accepted | Rail may `spawn_feedback_cycle` or suspend with blockers |
| Max feedback rounds | Snapshot `blocked` or policy-complete without accept; surface in status |
| Tag loss | Hydrate from CE (IG-691); refuse silent phase skip |

## 13. Phased delivery

| Phase | Scope |
|-------|--------|
| **P0** | Emit `dag_idle`; assessor stub (Cargo build/test + fixture runner if present); write `acceptance_met`; ban verifier spawn on rail jobs |
| **P1** | Wire `verification_rules` into assessor; enrich QA goal text; tag repair hard-fail path |
| **P2** | Maturity levels in CE + top/CLI; feedback driven by snapshot |
| **P3** | Broader probe registry; golden contracts from architecture plans |

Implementation tracking: **IG-692**.

## 14. Acceptance criteria (spec)

- [ ] Rail job with all children complete and `acceptance_met=false` does not
      leave root pending forever without `dag_idle` / feedback / blocked status
- [ ] `acceptance_met=true` only after assessor probes (or residual LLM with no
      required fails/unknowns)
- [ ] Verifier cannot create review/QA goals under a `rail_id` job
- [ ] Greenfield `needs_feedback` / `job_complete` short-circuits observe the latch
- [ ] Unit tests for assessor + rail guard + idle emission; no user-facing
      IG/RFC strings in runtime logs

## 15. Revision history

| Date | Change |
|------|--------|
| 2026-08-05 | Initial draft from job `20999e64` hang + GOAL maturity gap analysis |

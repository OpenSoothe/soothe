# IG-692: Job Maturity Assessment + Rail-Exclusive Spawn

**Created**: 2026-08-05  
**Status**: In progress (P0 + P1 landed)  
**Related**: [RFC-230](../specs/RFC-230-job-maturity-assessment.md),
[RFC-228](../specs/RFC-228-autopilot-job-ipc.md),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[IG-678](IG-678-autopilot-ce-rails-production-readiness.md),
[IG-680](IG-680-autopilot-dag-health-evidence-deps.md),
[IG-687](IG-687-greenfield-system-rail.md),
[IG-691](IG-691-integrate-thrash-rail-tag-loss.md),
LoopRail design draft

---

## Goal

Implement RFC-230 so Autopilot + ContextEngine **assure job maturity** and
LoopRail remains the **only** spawner for rail-bound jobs.

Incident motivation: job `20999e64` (`greenfield-system`) reached narrative
QA PASS while GOAL demos failed; root hung `pending` (no `dag_idle`);
verifier spawned review/QA outside the rail; `acceptance_met` never latched.

---

## Deliverables

### P0 — Latch + idle + exclusivity

- [x] `JobMaturityAssessor` module (`soothe.autopilot.maturity`)
- [x] Persist `JobMaturitySnapshot` on job root CE node (`GoalNode.maturity`) +
      mirror `acceptance_met` in `rail_state.json` via `set_acceptance_met`
- [x] Structural probes: Cargo `build`/`test`; optional GOAL fixture compile+run
      (stub ELF size / exec fail → not accepted); pytest probe for Python
- [x] Invoke assessor after consensus accept on `qa` / `feedback+verify` goals
- [x] Emit production `dag_idle` from AutopilotService (post-accept + schedule scan)
- [x] Ban `GoalDAGVerifier` / post-completion **create/decompose** under
      `rail_id` jobs; skip health reset of rail roots
- [x] Unit tests: `test_job_maturity.py`

### P1 — Contract + QA text + tags

- [x] Feed `GoalNode.verification_rules` + workspace `GOAL.md` into criteria /
      `acceptance_contract_brief`
- [x] Enrich `qa_verify` / feedback diagnose+verify goal descriptions from contract
- [x] Fail-closed tag repair: `ensure_trigger_tags` + interpreter hydrate before guards
- [x] `job_status` / top snapshot: expose `maturity` (+ `acceptance_met` on status)

### P2 — Levels + feedback loop

- [ ] Derive maturity levels per RFC-230 §6.2
- [x] Ensure `needs_feedback` / `job_complete` short-circuits use latch
      (`dag_idle` → feedback when unmet; never `complete_job` without latch
      on greenfield — fixed after premature complete of `20999e64`)
- [ ] Exhausted feedback → `blocked` snapshot + operator-visible status
- [ ] CLI/top polish for maturity (optional; may share IG-686/679 surface)

### P3 — Probe registry expansion

- [ ] Registry API for language/rail-specific probes
- [ ] Architecture-plan golden contracts (optional)

---

## Design notes (implementation)

### Control flow

```text
_apply_consensus_and_finalize (accept)
  → complete_goal
  → _notify_rail("goal_completed")
  → if rail tags qa|verify: assessor.run(job_id) → persist
  → _maybe_emit_dag_idle(job_id)

scheduling / after finalize
  → if rail job idle: _notify_rail("dag_idle")
```

### Files (expected)

| Area | Path |
|------|------|
| Assessor | `packages/soothe/src/soothe/autopilot/maturity.py` |
| Probes | Cargo/GOAL fixture in maturity; pytest via `evidence_grounding` |
| Service hooks | `autopilot/service.py` |
| Rail guards | `autopilot/rail/guards.py` |
| QA builtin text | `autopilot/rail/builtins_exec.py` |
| Verifier gate | `autopilot/goal_dag_verifier.py`, `verifier_prompts.py` |
| CE model | `context/models.py` (`maturity` / snapshot field) |
| Tests | `tests/unit/core/autopilot/test_job_maturity.py`, rail tests |

### Out of scope

- StrangeLoop maturity logic
- Full GOAL NL → test synthesis
- Auto-picking greenfield rail (still `--rail`)

---

## Acceptance

- [x] Rail job children complete + `acceptance_met=false` → `dag_idle` fires and
      either feedback spawns or job is explicitly blocked — **not** infinite
      “Skipping schedule for rail job root”
- [x] `acceptance_met=true` only via assessor (probes; LLM residual cannot alone
      latch if required criteria fail/unknown)
- [x] No verifier-created review/QA under `rail_id` job
- [x] Greenfield guards observe latch in unit tests
- [x] `./scripts/verify_finally.sh` green
- [x] No IG-/RFC- identifiers in user-facing runtime strings

---

## Test plan

1. Unit: Cargo workspace fixture with header-only ELF → `acceptance_met=false`
2. Unit: mock probes all pass → latch true → `job_complete` guard matches
3. Unit: rail job idle → `dag_idle` event delivered to interpreter
4. Unit: post-completion decompose skipped when `root.rail_id` set
5. Unit: empty in-memory tags + CE `rail_tags=["integrate"]` → commit path
6. Integration (optional): greenfield harness tick through QA → feedback when
   acceptance false

---

## References

- Diagnosis: job `20999e64` hang + GOAL.md maturity gap (2026-08-05)
- RFC-230 normative design
- IG-691 tag persistence (prerequisite for reliable phase transitions)

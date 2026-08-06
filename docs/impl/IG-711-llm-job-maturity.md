# IG-711: LLM-primary job maturity (domain-agnostic)

**Created**: 2026-08-06  
**Status**: Done  
**Related**: [RFC-230](../specs/RFC-230-job-maturity-assessment.md),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
[IG-692](../archive/impl/IG-692-job-maturity-assessment.md),
[IG-710](IG-710-consensus-trust-sloop-response.md)

---

## Goal

Job maturity must work for **any** workspace domain (coding, papers, travel
plans, research, …). Coding-only structural probes (`cargo` / `pytest` / GOAL
`ccc` fixtures) must not latch `acceptance_met`. Host assessor uses structured
LLM contract judgment over an evidence pack.

## Deliverables

- [x] Rename `autopilot/verify/maturity.py` → `job_maturity.py`
- [x] Delete cargo/pytest/`ccc` probe latch; async `JobMaturityAssessor.assess`
- [x] Evidence pack: GOAL.md / verification_rules / DAG summary / shallow inventory /
      optional QA response
- [x] Wire `_consensus_model` from `AutopilotService._maybe_assess_job_maturity`
- [x] Fail closed when model missing or LLM fails (no invent-accept)
- [x] Broaden `plan_contribution` path tokens (metadata only; not a latch)
- [x] Revise RFC-230 (LLM-primary); note IG-710 probe wording superseded
- [x] Unit tests for LLM mock accept/reject/missing model

## Design rules

1. Per-goal consensus stays goal text + sloop response (IG-710) — unchanged.
2. Job latch is **only** `MaturityAssessmentVerdict.acceptance_met`.
3. No language toolchain runners in the maturity module.
4. `plan_contribution.build_files_touched` remains wire contribution metadata.

## Out of scope

- Operator-declared shell commands as evidence
- StrangeLoop owning maturity
- Re-adding a coding probe registry as the accept latch

# IG-710: Consensus trusts StrangeLoop response (drop host evidence grounding)

**Created**: 2026-08-06  
**Status**: Done  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-230](../specs/RFC-230-job-maturity-assessment.md),
[IG-707](IG-707-autopilot-automatic-consensus-no-operator-suspend.md),
[IG-680](../archive/impl/IG-680-autopilot-dag-health-evidence-deps.md) (historical),
[IG-685](../archive/impl/IG-685-consensus-full-output-evidence.md) (historical)

---

## Goal

Autopilot per-goal consensus MUST NOT invent host-side “evidence grounding”
(workspace deliverable markers, pytest soft/hard accept, contribution packing
as a gate). StrangeLoop’s Plan-Execute-Eval already decides when a goal is
done; the host consensus LLM compares **goal text** vs **StrangeLoop response**
(`PlanResult` evidence / full output seeded on the wire).

Structural probes remain **job maturity only** (RFC-230), not Layer-3 consensus.

---

## Design rules

1. `_apply_consensus_and_finalize` passes `goal.description` + worker
   `evidence_summary` (sloop response) into `evaluate_goal_completion`.
2. No empty-grounded pre-gate that send_backs before the judge runs.
3. No workspace artifact probe append; no pytest PASS hard-accept override.
4. Remove deliverable-marker skip-decompose gates from `GoalDAGVerifier`.
5. Move `workspace_pytest_probe` into `maturity.py`; delete consensus-oriented
   helpers (`enrich_workspace_evidence`, `format_contribution_evidence`,
   `_DELIVERABLE_MARKERS`, …).
6. Keep worker helpers that synthesize the **wire response** / contribution
   from `PlanResult` (rename module to `plan_contribution.py`).

---

## Spec updates

- RFC-204 §1.3 — replace evidence-grounding normative note
- RFC-230 §7.2 / §10 — probes are maturity-only; consensus is goal+response
- IG-707 — drop “empty grounded evidence → send_back” rule

---

## Test plan

- [x] Empty `evidence_summary` still invokes consensus (mock accept → completed)
- [x] Workspace markers alone do not complete / do not skip decompose
- [x] Non-empty sloop response + mock accept → completed
- [x] Maturity pytest probe still works from `maturity.py`
- [x] `./scripts/verify_finally.sh` green

---

## Out of scope

- Changing StrangeLoop Plan-Exec-Eval internals
- Expanding maturity probe registry beyond relocating pytest
- Architecture WavePlan host gate (IG-704)

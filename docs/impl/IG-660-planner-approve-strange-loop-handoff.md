# IG-660: Planner Approve → StrangeLoop Implement Handoff

**Created**: 2026-07-29  
**Status**: Implemented  
**Related**: [RFC-633](../specs/RFC-633-planner-plan-artifact-and-human-review.md), [IG-658](IG-658-planner-readonly-tools-plan-review.md), [IG-659](IG-659-planner-goal-completion-proposal.md)

---

## Executive Summary

After the operator **Approves** an intake planner solution report, keep the same
CE goal continuous: clear the planner wire (“exit plan mode”) and hand off onto
the StrangeLoop spine (`plan_generate` → execute → …) with the approved artifact
as grounding. Reject still completes the goal; More comments still revises.

---

## Design

### A. Approve semantics (host)

1. Mark artifact frontmatter `status: approved`.
2. Ledger a short note only (`Plan approved. Proceeding to implement.` + path) —
   do **not** treat the plan body as `ledger_direct` final answer.
3. Set one-shot `planner_implement_handoff` on scratch + graph state.
4. Synthesize a fresh-loop `StatusAssessment` so `plan_generate` can run.
5. Clear `preferred_subagent` / wired `intent_route`; clear clarification fields.
6. Leave original user goal on `LoopState` / CE (not the answer text “Approve”).

### B. Routing

- `route_after_wired_subagent`: handoff → `plan_generate`; reject / other wires →
  `goal_completion`; pending review → `await_clarification`.
- Graph builder edges for `invoke_wired_subagent` include `plan_generate`.

### C. Plan-generate grounding

- When handoff is active, inject an **Approved plan** section (path + body,
  frontmatter stripped) into the plan-generate user message with instruction to
  implement via StrangeLoop steps without re-litigating the Solution unless blocked.
- Clear handoff (and approved-plan injection fields) after the first
  `plan_generate`.

### D. Specs

- Amend RFC-633 architecture, answer semantics, acceptance, and Non-goals.
- Point IG-659 out-of-scope at this IG.

---

## Acceptance

- [x] Approve → `route_after_wired_subagent` returns `plan_generate`
- [x] Reject → `goal_completion`; More comments → re-invoke planner
- [x] Approve does not ledger the full plan body as final report
- [x] Plan-generate prompt includes Approved plan when handoff is set
- [x] Handoff cleared after first `plan_generate`
- [x] Unit tests green for approve routing, ledger, and prompt grounding
- [x] `./scripts/verify_finally.sh` green for owned packages

---

## Out of scope

- Compiling Changes markdown directly into `AgentDecision`
- Auto-starting a second CE goal
- Desktop-specific UI

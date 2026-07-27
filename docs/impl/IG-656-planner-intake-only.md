# IG-656: Planner Intake-Only (Not CoreAgent `task`)

**Created**: 2026-07-27
**Status**: In progress
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-600](../archive/impl/IG-600-intake-only-wire-subagent-exposure.md), [IG-601](IG-601-intake-only-subagent-dual-registry.md)

---

## Executive Summary

Move `planner` into `INTAKE_ONLY_WIRE_SUBAGENTS` so it is reachable only via Pass 2 / slash → `invoke_wired_subagent` (streamed direct invoke → `goal_completion`), and **not** via CoreAgent open `task` or plan-wave `delegate`.

---

## Design

1. Add `planner` to `INTAKE_ONLY_WIRE_SUBAGENTS` (same exposure as `browser_use` / `deep_research` / `academic_research`).
2. Wired `planner` uses the intake-only direct-invoke path (orphan SubAgent card); drop catalog resolve → execute for this specialist.
3. Update plan-generate / CoreAgent prompts so `delegate` / `task` no longer advertise `planner`.
4. Update RFC-630 §6.3.1–6.3.2 and rfc-namings; adjust unit tests that assumed dual-expose.

---

## Acceptance

- [ ] `planner` in intake-only set; filtered from task catalog partition
- [ ] Wired planner → direct invoke → `goal_completion` (no resolve/execute)
- [ ] `task(subagent_type="planner")` blocked by intake guard
- [ ] Plan-wave `delegate=planner` ignored
- [ ] Verify green

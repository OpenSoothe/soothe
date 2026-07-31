# IG-656: Planner Intake-Only (Not CoreAgent `task`)

**Created**: 2026-07-27
**Status**: Implemented
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-600](../archive/impl/IG-600-intake-only-wire-subagent-exposure.md), [IG-601](IG-601-intake-only-subagent-dual-registry.md), [IG-602](IG-602-orphan-wired-subagent-card.md)

---

## Executive Summary

Move `planner` into `INTAKE_ONLY_WIRE_SUBAGENTS` so it is reachable only via Pass 2 / slash → `invoke_wired_subagent` (streamed direct invoke → `goal_completion`), and **not** via CoreAgent open `task` or plan-wave `delegate`.

---

## Design

1. Add `planner` to `INTAKE_ONLY_WIRE_SUBAGENTS` (same exposure as `browser_use` / `deep_research` / `academic_research`).
2. Wired `planner` uses the intake-only direct-invoke path (orphan SubAgent card); drop catalog resolve → execute for this specialist.
3. Collapse `_BUILTIN_WIRE_SUBAGENTS` into the intake-only allowlist; remove `wired_route_next` / resolve edge from the wired branch.
4. Update plan-generate / CoreAgent prompts so `delegate` / `task` no longer advertise `planner`.
5. Update RFC-630 §6.3.1–6.3.2 and rfc-namings; adjust unit tests that assumed dual-expose.

---

## Cleanse

- Removed dual-expose catalog path in `invoke_wired_subagent` (always direct invoke).
- Removed `wired_route_next` graph state + resolve_decision edge after wired node.
- Plan-wave `resolve_step_wire_subagent` / `delegate` → always no-op (no catalog keep-path).
- Dropped `user_wire_subagent` plan-generate prompt branch for dual-exposed wires.

---

## Acceptance

- [x] `planner` in intake-only set; filtered from task catalog partition
- [x] Wired planner → direct invoke → `goal_completion` (no resolve/execute)
- [x] `task(subagent_type="planner")` blocked by intake guard
- [x] Plan-wave `delegate=planner` ignored
- [x] Related dual-expose / catalog-wire dead paths cleansed
- [x] `soothe` / `soothe-daemon` verify green (CLI card-ledger WIP failures are out of scope)

---

## Follow-up

[IG-669](IG-669-remove-inferred-wire-subagent.md) removed the always-`None`
step-level plumbing this IG left behind (`resolve_step_wire_subagent`,
`apply_step_wire_subagents`, `StepAction.wire_subagent`) and dropped Pass 2
specialist inference, so wired specialists are reachable by slash command only.

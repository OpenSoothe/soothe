# IG-600: Intake-Only Wire Subagent Exposure

**Created**: 2026-07-14
**Status**: Implemented (superseded for registration by [IG-601](IG-601-intake-only-subagent-dual-registry.md))
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-599](IG-599-pass2-wired-subagent-direct-route.md), [IG-601](IG-601-intake-only-subagent-dual-registry.md)

---

## Executive Summary

Specialist wire subagents `browser_use`, `deep_research`, and `academic_research` become **intake-only**: reachable via Pass 2 / slash → `invoke_wired_subagent`, but hidden from the open CoreAgent `task` catalog and StrangeLoop plan `delegate` surface. **`planner` stays dual-exposed** (intake route **and** open task catalog / plan delegate).

IG-601 completes true invisibility: intake-only specs are not passed to `create_deep_agent` at all.

---

## Scope

### In Scope

- Shared `INTAKE_ONLY_WIRE_SUBAGENTS` frozenset + helpers (allowlist filter).
- Filter advertised CoreAgent capabilities / StrangeLoop `PlanContext`.
- Prompt updates (`_SUBAGENT_GUIDE`, plan-generate `delegate`).
- RFC-630 exposure section; unit tests.
- ~~deepagents advertise-subset catalog filter~~ — removed in IG-601 (registration partition is enough).

### Out of Scope

- Plugin subagents (remain task-catalog by default).
- Changing IG-599 graph topology (see IG-601 for direct invoke).

---

## Exposure matrix

| Subagent | Intake / wired | Open `task` catalog | Plan `delegate` |
|----------|----------------|---------------------|-----------------|
| `planner` | Yes | Yes | Yes |
| `browser_use` | Yes | No | No |
| `deep_research` | Yes | No | No |
| `academic_research` | Yes | No | No |

---

## Design (historical → IG-601)

1. ~~Keep registering all four in CoreAgent~~ → IG-601: partition; intake-only on parallel registry only.
2. Catalog advertisement omits intake-only names.
3. ~~Allow `task` when wired directive matches~~ → IG-601: always reject intake-only `task` (belt-and-suspenders); wired path uses direct `ainvoke`.
4. Planner prompts / PlanContext never advertise the three intake-only names.

---

## Cleanse (related dead / dual paths)

- Plan-generate `delegate` schema + execution policies: drop browser/deep_research as open delegates.
- `_apply_preferred_subagent_to_decision` no-ops for intake-only names.
- IG-601: removed `wired_directive_allows_intake_only` and wired-allow exception in ToolEnforcement.

## Verification

- Unit: catalog filter, capabilities, invoke guard deny, plan prompt
- `./scripts/verify_finally.sh`

---

## Acceptance

- [x] IG authored
- [x] Intake-only set excludes `planner`
- [x] Open hops cannot freely invoke the three
- [x] RFC-630 updated
- [x] Related dead dual-path plumbing cleansed (continued in IG-601)
- [x] Verify green

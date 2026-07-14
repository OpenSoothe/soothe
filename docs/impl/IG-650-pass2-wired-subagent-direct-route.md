# IG-650: Pass 2 Wired-Subagent Direct Route

**Created**: 2026-07-14
**Status**: Implemented
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-554](IG-554-two-pass-intake-classification-implementation.md), [IG-349](../archive/impl/IG-349-unified-subagent-routing.md)

---

## Executive Summary

When Pass 2 (or slash `preferred_subagent`) determines the user goal is a dedicated call to a wired specialist subagent (`browser_use`, `deep_research`, `academic_research`, `planner`), StrangeLoop skips plan assess/generate and routes through a new graph node `invoke_wired_subagent` → `resolve_decision` → execute → `goal_completion`. The subagent result becomes the goal completion report; user goal + report are written to the CE ledger via the existing completion path.

---

## Scope

### In Scope

- Expand Pass 2 `wire_subagent` allowlist to include `academic_research` (keep `planner` as the canonical id for `/plan`).
- Harden Pass 2 post-parse validation against the allowlist.
- Polish Pass 2 prompt: set `wire_subagent` when the **primary intent** is to run that specialist.
- Promote resolved wire into `RoutingClassification.preferred_subagent` / `routing_hint=subagent`.
- `init_or_resume`: when a wired subagent resolves, inject the 1-step terminal plan and set `intent_route=wired_subagent`.
- New node `invoke_wired_subagent` + `route_by_intent` priority (after chitchat, before continuation).
- Update RFC-630, diagram docs, and unit tests.

### Out of Scope

- Restoring the archived runner `_run_direct_subagent` bypass (IG-349 stays: stay inside StrangeLoop).
- Plugin/dynamic subagent names beyond the built-in wire allowlist.
- Changing CoreAgent `task` tool semantics or subagent internals.
- Wire protocol / event envelope changes.

---

## Design

### Routing priority (`route_by_intent`)

1. Chitchat `fast_path` → `__end__`
2. **`intent_route == wired_subagent`** → `invoke_wired_subagent`
3. Continuation overlays (trivial/simple → `plan_assess`; complex → evidence gather)
4. Fresh trivial / simple / complex (unchanged)

### `invoke_wired_subagent` node

Thin graph node:

- Ensures `scratch.plan_result` is the wired 1-step terminal plan (`build_trivial_plan` with `wire_subagent` + `terminal_after_execute=True`).
- Emits plan-phase status (`Delegating to <name>`).
- Unconditional edge → `resolve_decision` → validate → execute → (terminal) → `goal_completion`.

Ledger Human(goal) + AI(report) uses the existing `goal_completion` path (`ledger_direct` / synthesize); no parallel ledger writer.

### Resolution order for wired name

1. Slash / daemon `preferred_subagent` (when in allowlist)
2. Pass 2 `intent.wire_subagent` (when in allowlist)
3. Else no wired route

Canonical allowlist: `planner`, `browser_use`, `deep_research`, `academic_research`.

---

## Files

| File | Action |
|------|--------|
| `foundation/sloop/state/schemas.py` | Expand `_BUILTIN_WIRE_SUBAGENTS` |
| `foundation/sloop/intention/models.py` | Merge Pass 2 wire into routing classification |
| `foundation/sloop/intention/pass2_classifier.py` | Allowlist coerce |
| `prompts/.../intake_pass2_system.xml` | Prompt polish |
| `orchestrator/state.py` | `IntentRoute` += `wired_subagent` |
| `orchestrator/nodes/init_or_resume.py` | Inject wired plan + intent_route |
| `orchestrator/nodes/invoke_wired_subagent.py` | New node |
| `orchestrator/routing.py` | Priority branch |
| `orchestrator/builder.py` | Register node + edges |
| `docs/specs/RFC-630-*.md` | Spec update |
| `scripts/visualize_strange_loop_graph.py` | Diagram summary text |
| `docs/diagrams/*` | Regenerate |

---

## Verification

- Unit: allowlist, `route_by_intent` wired branch, `init_or_resume` inject, node smoke
- `./scripts/verify_finally.sh`
- Regenerate: `python scripts/visualize_strange_loop_graph.py`

---

## Cleanse (related dead / dual paths)

- Plan inject for wired route owned solely by `invoke_wired_subagent` (removed duplicate inject from `init_or_resume`).
- Trivial branch no longer threads Pass 2 `wire_subagent` (allowlisted names take the wired route).
- `resolve_user_requested_wire_subagent` collapsed to a single allowlist filter over slash → routing → Pass 2 (dropped redundant `resolve_step_wire_subagent` dual path).

## Acceptance

- [x] IG authored
- [x] Pass 2 allowlist + prompt include `academic_research` + `planner`
- [x] Wired route skips plan_assess / plan_generate / evidence gather
- [x] Execute uses `soothe_step_subagent`; terminal → goal_completion ledger
- [x] RFC-630 + diagrams updated
- [x] Related dead dual-path plumbing cleansed
- [x] Verify green

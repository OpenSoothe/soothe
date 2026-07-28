# IG-658: Planner Readonly Tools, Plan Artifact, and Human Review

**Created**: 2026-07-28  
**Status**: Implemented  
**Related**: [RFC-633](../specs/RFC-633-planner-plan-artifact-and-human-review.md), [RFC-618](../specs/RFC-618-plan-subagent-delegation.md), [RFC-622](../specs/RFC-622-coreagent-clarification-relay.md), [IG-656](IG-656-planner-intake-only.md)

---

## Executive Summary

Give the intake-only planner readonly filesystem recon (orphan card tool rows),
persist plans to `{workspace}/.soothe/plans/`, and gate completion on human
Approve / Reject / More comments via the RFC-622 clarification relay.

---

## Design

### A. soothe-nano planner

1. `subagents/plan/tools.py` — `get_planner_readonly_tools(workspace)` whitelist.
2. `PlanSubagentConfig` — `enable_recon`, `max_recon_rounds`.
3. `engine.py` — recon loop (`bind_tools` → `ToolNode` → collect findings) →
   plan_iteration → emit_final; emit `soothe.stream.tool_call.update` via wire
   bridge during recon. Tools must run through `ToolNode` so `ToolRuntime` is
   injected (bare `tool.ainvoke(args)` fails FilesystemMiddleware tools).
4. Factory passes `work_dir` / workspace from resolver context.

### B. soothe host

1. `sloop/plans/artifact.py` — path slug + write/update frontmatter status.
2. `invoke_wired_subagent` — for `planner` only: save artifact; set
   `pending_clarification` (origin `planner_subagent_review`); on answer resume
   Approve/Reject/Comments.
3. Expand wire forwarder to stamp/forward `tool_call.update` onto the query stream.
4. Routing: `route_after_wired_subagent` → `await_clarification` when pending;
   `route_after_clarification` → `invoke_wired_subagent` for `planner_subagent_review`.
5. Extend `ClarificationOrigin` with `planner_subagent_review` (distinct from
   StrangeLoop `plan_generate` / `plan_assess`).


### C. soothe-cli

1. Clarification UI keys off `origin_node=planner_subagent_review` (title/placeholders).
2. Existing two-input clarification widget maps to action + comments (no new widget required for v1).
3. Root-ns stamped tool updates route onto the orphan SubAgent card (not the main tool buffer).
4. Manual clarification mounts even when no execute step card exists (intake-only).

### D. Specs

1. RFC-633 (new).
2. RFC-618 — note explore superseded; pointer to RFC-633.
3. RFC-622 / rfc-namings — `planner_subagent_review` origin + StrangeLoop
   `plan_generate`/`plan_assess` naming contrast.

---

## Cleanse

- Drop planner prompt language that forbids all recon on the planner thread
  (replace with “readonly tools only; no mutating tools”).
- Do not revive explore subagent.

---

## Acceptance

- [x] Readonly tools available to planner; tool updates forward to orphan card
- [x] Plan file written under `.soothe/plans/`
- [x] Review clarification after planner; Approve/Reject/Comments behavior
- [x] Planner-subagent review origin forced manual by default
  (`force_manual_origins` includes `planner_subagent_review` only — not
  StrangeLoop `plan_generate`/`plan_assess`)

- [x] Non-planner wires unchanged
- [x] Unit tests (artifact writer, review parse, routing, planner tools filter)
- [x] `./scripts/verify_finally.sh` green for owned packages

**Status**: Implemented

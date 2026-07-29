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

1. Readonly tools via `get_planner_readonly_tools(workspace)` (in `engine.py`
   after IG-659 layout collapse; was `tools.py`).
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

1. Clarification UI keys off `origin_node=planner_subagent_review`.
2. Unified plan-review card: full draft markdown preview (expanded in-box,
   no inner scroll), `Plan saved to:` path
   footer, Approve / Reject / More comments buttons; comments `Input` only when
   More comments is selected (Approve/Reject submit immediately).
3. Root-ns stamped tool updates route onto the orphan SubAgent card (not the main tool buffer).
4. Manual clarification mounts even when no execute step card exists (intake-only).
5. Wire answers remain `["Approve"|"Reject"|"More comments", comments]`.

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
- Drop two-text-input plan-review UX and Q1-embedded `(plan: path)` questions;
  review uses plan body + path footer + action buttons only.
- Drop pre-review ledger “awaiting Approve / Reject” footer (widget owns that UX).
- Drop unused `plan_path` arg on `_planner_subagent_review_pending_payload` and
  text-input synonym parsing (`a`/`yes`/`r`/`no`) for review answers.
- Clarification resume must not create a CE goal titled with the answer
  (`Approve` / `Reject` / …); reuse the active CE goal and restore its
  description onto `LoopState` so ledger Human rows keep the original planning goal.
- Orphan planner card shows tool rows only (no start/recon/draft activity notes);
  planner stage is shown on the Running status line (``Running · recon 1/4…``);
  planner tool calls and results are logged at INFO.

---

## Acceptance

- [x] Readonly tools available to planner; tool updates forward to orphan card
- [x] Plan file written under `.soothe/plans/`
- [x] Review clarification after planner; Approve/Reject/Comments behavior
  (full plan preview + path footer + action buttons; comments only for More comments)
- [x] Planner-subagent review origin forced manual by default
  (`force_manual_origins` includes `planner_subagent_review` only — not
  StrangeLoop `plan_generate`/`plan_assess`)
- [x] Clarification resume reuses CE goal / original goal text (answers only for
  `Command(resume)`)
- [x] Planner orphan card: tool call rows only; stage on Running status line;
  tool call/result INFO logs

- [x] Non-planner wires unchanged
- [x] Unit tests (artifact writer, review parse, routing, planner tools filter,
  resume goal helpers, planner tool logging)
- [x] `./scripts/verify_finally.sh` green for owned packages

**Status**: Implemented

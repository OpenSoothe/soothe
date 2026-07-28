# RFC-633: Planner Plan Artifact and Human Review

**RFC**: 633  
**Title**: Planner Plan Artifact and Human Review  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-07-28  
**Authors**: Soothe Team  
**Depends on**: RFC-618, RFC-622, RFC-630, RFC-656 (IG-656 intake-only planner)  
**Related**: RFC-621 (workspace host convention), RFC-628 (step/orphan cards)

## Abstract

Evolve the intake-only **planner** subagent from a text-only plan-design loop into a
**readonly-recon → markdown plan artifact → human review** workflow:

1. Planner may call **readonly** filesystem tools (`ls`, `glob`, `grep`, `read_file`,
   `file_info`) so the orphan SubAgent card shows tool activity.
2. Host persists the plan under `{workspace}/.soothe/plans/{timestamp}-{slug}.md`.
3. StrangeLoop pauses via the RFC-622 clarification relay so the operator can
   **Approve**, **Reject**, or supply **More comments** (with a free-text input).

This RFC updates the post-IG-547 planner (explore removed) and the IG-656
intake-only `ledger_direct` completion path, which previously finished the goal
without human gate or workspace artifact.

## 1. Problem

| Gap | Effect |
|-----|--------|
| Planner has no tools | Orphan planner card never shows tool rows; plans lack workspace grounding |
| Intake → `goal_completion` / `ledger_direct` | Plan text is treated as the final answer; no Approve/Reject |
| No durable plan file | Cannot discuss or iterate on a shared markdown artifact in the workspace |

## 2. Goals

1. **Readonly recon** inside the planner graph (not explore subagent; not mutating tools).
2. **Plan artifact** at `{workspace}/.soothe/plans/<UTC-compact>-<slug>.md`.
3. **Human review** using RFC-622 interrupt + TUI clarification UI:
   - Action: Approve | Reject | More comments
   - Free-text comments field (required when choosing More comments)
4. **Orphan card tool rows** for planner recon (wire-bridge `tool_call.update` + step_id stamp).
5. Non-planner intake wires (`browser_use`, `deep_research`, `academic_research`) unchanged.

## 3. Non-goals

- Replacing StrangeLoop `LLMPlanner` / plan-execute waves for complex intake.
- Nested `task` / explore subagent revival.
- Desktop-specific plan UI (TUI first; AppKit can consume the same wire events later).
- Auto-executing approved plans into CoreAgent steps in v1 (Approve finalizes the
  goal with the accepted plan artifact; a later continue/execute wave may consume it).

## 4. Architecture

```
Pass2/slash → invoke_wired_subagent(planner)
              ├─ recon rounds (readonly tools) → orphan card tool rows
              ├─ plan_iteration rounds → plan_markdown
              └─ emit_final AIMessage
host        → write `.soothe/plans/...md`
            → pending_clarification (origin=planner_subagent_review)
            → await_clarification (RFC-622 interrupt)
TUI         → Q1 action + Q2 comments
resume      → Approve → goal_completion (ledger = plan + path)
              Reject  → goal_completion (rejected status text)
              Comments→ re-invoke planner with prior plan + comments → review again
```

> Naming: ``planner_subagent_review`` is the intake **planner subagent** human
> gate. It is **not** StrangeLoop ``plan_generate`` / ``plan_assess`` (those are
> the host planning-stage nodes on the complex spine).

### 4.1 Planner engine (soothe-nano)

- Config: `enable_recon` (default true), `max_recon_rounds`, existing `max_plan_rounds`.
- Recon: `model.bind_tools(readonly_tools)` → LangGraph `ToolNode` (injects
  `ToolRuntime`) → collect findings; emit `soothe.stream.tool_call.update` via
  wire bridge for each tool; findings feed the plan prompt. Do **not** call
  middleware tools with bare `tool.ainvoke(args)`.
- Plan design: existing structured `PlanRefinement` loop.
- Tools whitelist: `glob`, `grep`, `ls`, `read_file`, `file_info` from
  `SootheFilesystemMiddleware` (no write/edit/delete/execute).

### 4.2 Plan artifact (host)

- Writer: host node after successful planner invoke (not planner `write_file`).
- Path: `{workspace}/.soothe/plans/{YYYYMMDDTHHMMSSZ}-{slug}.md`
- Optional YAML frontmatter: `goal_id`, `loop_id`, `status` (`draft` | `approved` |
  `rejected`), `created_at`.
- Body: full markdown plan.

### 4.3 Clarification shape

Questions (stable order):

1. `Action for this plan: Approve, Reject, or More comments`
2. `Additional comments (required for More comments; optional otherwise)`

Event payload includes `plan_path` and a short plan preview for TUI copy.

`ClarificationOrigin` gains `planner_subagent_review` (planner **subagent**
gate only; not StrangeLoop `plan_generate`/`plan_assess`, not other wired
subagents).  
`route_after_wired_subagent` → `await_clarification` when pending.  
`route_after_clarification` → `invoke_wired_subagent` for `planner_subagent_review`.

### 4.4 Answer semantics

| Parsed action | Behavior |
|---------------|----------|
| Approve | Mark plan frontmatter `status: approved`; clear clarification; `goal_completion` with ledger report including path |
| Reject | Mark `status: rejected`; `goal_completion` with short rejection note |
| More comments | Append comments to planner input; re-run planner; rewrite plan file; re-enter review |

Parsing is case-insensitive prefix / synonym match on Q1 (`approve`/`a`/`yes`,
`reject`/`r`/`no`); otherwise treat as comments (Q1 and/or Q2 body).

## 5. Package boundaries

| Concern | Package |
|---------|---------|
| Readonly tools + plan graph | `soothe-nano` |
| Save artifact, review gate, routing | `soothe` |
| Clarification UI (action + comments) | `soothe-cli` |
| Wire event types | `soothe-sdk` (reuse existing stream + clarification events) |

## 6. Acceptance criteria

1. Wired `planner` intake with `enable_recon` may emit ≥1 tool update on the orphan card when recon runs.
2. Successful planner invoke writes a file under `{workspace}/.soothe/plans/`.
3. Loop pauses on clarification; TUI shows two fields (action + comments).
   Origin ``planner_subagent_review`` is in
   ``agent.clarification.force_manual_origins`` by default so veritas does not
   auto-Approve/Reject even when clarification mode is ``auto``. This does not
   force-manual StrangeLoop ``plan_generate`` / ``plan_assess`` clarifications
   or other wired subagents.
4. Approve / Reject complete the goal; More comments revises the plan and asks again.
5. Non-planner intake wires still route directly to `goal_completion` (no review gate).

## 7. References

- RFC-618 — Plan subagent (explore collection superseded; readonly tools here).
- RFC-622 — Clarification relay.
- IG-656 — Planner intake-only.
- IG-658 — Implementation guide for this RFC.

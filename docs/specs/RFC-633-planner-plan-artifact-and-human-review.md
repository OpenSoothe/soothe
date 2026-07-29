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
**readonly grounding → solution report artifact → human review** workflow:

1. Planner may call **readonly** filesystem tools (`ls`, `glob`, `grep`, `read_file`,
   `file_info`) to ground a solution (orphan SubAgent card shows tool activity).
   Tool output is internal evidence — not the deliverable. Recon must gather enough
   fact that the report can prescribe edits without scheduling further reads.
2. Deliverable is a **solution report** (Goal, Solution, Design principles and
   Architecture changes when needed, Changes as concrete edit/add/remove steps,
   Evidence, risks, open questions) persisted under
   `{workspace}/.soothe/plans/{timestamp}-{slug}.md`. Changes must not be an
   investigation roadmap ("read X", "diagnose Y"). Design principles /
   Architecture sections may be `None` for trivial local fixes.
3. StrangeLoop pauses via the RFC-622 clarification relay so the operator can
   **Approve**, **Reject**, or supply **More comments** (with a free-text input).

This RFC updates the post-IG-547 planner (explore removed) and the IG-656
intake-only `ledger_direct` completion path, which previously finished the goal
without human gate or workspace artifact. Module layout and solution-report
framing are refined in IG-659.

## 1. Problem

| Gap | Effect |
|-----|--------|
| Planner has no tools | Orphan planner card never shows tool rows; plans lack workspace grounding |
| Intake → `goal_completion` / `ledger_direct` | Plan text is treated as the final answer; no Approve/Reject |
| No durable plan file | Cannot discuss or iterate on a shared markdown artifact in the workspace |

## 2. Goals

1. **Solution report** as the planner product (decided Solution + concrete Changes
   that complete the user goal), not a findings collection and not an
   investigation roadmap of further reads.
2. **Readonly grounding** inside the planner graph (not explore subagent; not mutating tools).
3. **Plan artifact** at `{workspace}/.soothe/plans/<UTC-compact>-<slug>.md`.
4. **Human review** using RFC-622 interrupt + TUI clarification UI:
   - Action: Approve | Reject | More comments
   - Free-text comments field (required when choosing More comments)
5. **Orphan card tool rows** for planner grounding (wire-bridge `tool_call.update` + step_id stamp).
6. Non-planner intake wires (`browser_use`, `deep_research`, `academic_research`) unchanged.

## 3. Non-goals

- Replacing StrangeLoop `LLMPlanner` / plan-execute waves for complex intake
  (Approve hands the approved artifact to StrangeLoop `plan_generate`; it does
  **not** compile Changes markdown directly into an `AgentDecision`).
- Nested `task` / explore subagent revival.
- Desktop-specific plan UI (TUI first; AppKit can consume the same wire events later).
- Auto-starting a **second** CE goal after Approve (same-loop handoff only).

## 4. Architecture

```
Pass2/slash → invoke_wired_subagent(planner)
              ├─ recon rounds (readonly tools) → orphan card tool rows
              ├─ plan_iteration rounds → plan_markdown
              └─ emit_final AIMessage
host        → write `.soothe/plans/...md`
            → pending_clarification (origin=planner_subagent_review)
            → await_clarification (RFC-622 interrupt)
TUI         → plan body + path footer + Approve/Reject/More comments
resume      → Approve → plan_generate → execute… → goal_completion
              Reject  → goal_completion (rejected status text)
              Comments→ re-invoke planner with prior plan + comments → review again
```

> Naming: ``planner_subagent_review`` is the intake **planner subagent** human
> gate. It is **not** StrangeLoop ``plan_generate`` / ``plan_assess`` (those are
> the host planning-stage nodes on the complex spine).

### 4.1 Planner engine (soothe-nano)

- Layout (IG-659): `subagents/plan/__init__.py` + `engine.py` only (schemas,
  events, readonly tools, factory, and graph live in `engine.py`).
- Config: `enable_recon` (default true), `max_recon_rounds`, existing `max_plan_rounds`.
- Grounding: `model.bind_tools(readonly_tools)` → LangGraph `ToolNode` (injects
  `ToolRuntime`) → collect internal evidence; emit `soothe.stream.tool_call.update`
  via wire bridge for each tool; evidence feeds the proposal prompt. Do **not**
  call middleware tools with bare `tool.ainvoke(args)`.
- Proposal design: structured `PlanRefinement` loop emitting a **solution report**
  in `plan_markdown` (Goal / Solution / Design principles / Architecture changes /
  Changes / Evidence / …). Design principles and Architecture changes are required
  sections but may be `None` when not applicable. Changes are concrete
  edit/add/remove steps — never read/diagnose/investigate steps.
- Tools whitelist: `glob`, `grep`, `ls`, `read_file`, `file_info` from
  `SootheFilesystemMiddleware` (no write/edit/delete/execute).

### 4.2 Plan artifact (host)

- Writer: host node after successful planner invoke (not planner `write_file`).
- Path: `{workspace}/.soothe/plans/{YYYYMMDDTHHMMSSZ}-{slug}.md`
- Optional YAML frontmatter: `goal_id`, `loop_id`, `status` (`draft` | `approved` |
  `rejected`), `created_at`.
- Body: full markdown plan.

### 4.3 Clarification shape

Questions (stable order; path/markdown are **not** embedded in Q1):

1. `Action for this plan: Approve, Reject, or More comments`
2. `Revision comments (when choosing More comments)`

`clarification.requested` extras for TUI plan-review card:

- `plan_path` — workspace artifact path (or omitted if memory-only)
- `plan_markdown` — full draft body (frontmatter stripped in the TUI for display)

TUI layout (top → bottom):

1. Full draft plan markdown preview (expanded in-box; no inner scroll —
   the chat list scrolls if needed)
2. `Plan saved to: {path}` footer under the body
3. Approve / Reject / More comments action buttons
4. Comments input **only after** More comments is selected

Event payload includes `plan_path` and full `plan_markdown` for TUI copy.
Approve / Reject submit immediately with empty comments; More comments requires
non-empty free text before resume.

`ClarificationOrigin` gains `planner_subagent_review` (planner **subagent**
gate only; not StrangeLoop `plan_generate`/`plan_assess`, not other wired
subagents).  
`route_after_wired_subagent` → `await_clarification` when pending;  
→ `plan_generate` when Approve sets `planner_implement_handoff`;  
→ `goal_completion` otherwise (Reject / non-planner wires).  
`route_after_clarification` → `invoke_wired_subagent` for `planner_subagent_review`.

### 4.4 Answer semantics

| Parsed action | Behavior |
|---------------|----------|
| Approve | Mark plan frontmatter `status: approved`; clear clarification and planner wire; short ledger note; set `planner_implement_handoff`; route to StrangeLoop `plan_generate` with the approved artifact as grounding (same CE goal) |
| Reject | Mark `status: rejected`; `goal_completion` with short rejection note |
| More comments | Append comments to planner input; re-run planner; rewrite plan file; re-enter review |

Parsing uses case-insensitive prefixes on Q1 (`approve`, `reject`,
`more`/`comments`); otherwise treat the answer body as revision comments.

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
3. Loop pauses on clarification; TUI shows the full draft plan body, a saved-path
   footer, then Approve / Reject / More comments controls (comments field only
   for More comments). Origin ``planner_subagent_review`` is in
   ``agent.clarification.force_manual_origins`` by default so veritas does not
   auto-Approve/Reject even when clarification mode is ``auto``. This does not
   force-manual StrangeLoop ``plan_generate`` / ``plan_assess`` clarifications
   or other wired subagents.
4. Reject completes the goal; Approve hands off to StrangeLoop `plan_generate`
   (does not complete yet); More comments revises the plan and asks again.
5. Non-planner intake wires still route directly to `goal_completion` (no review gate).

## 7. References

- RFC-618 — Plan subagent (explore collection superseded; readonly tools here).
- RFC-622 — Clarification relay.
- IG-656 — Planner intake-only.
- IG-658 — Implementation guide for plan artifact + human review.
- IG-659 — Goal Completion Proposal framing + `plan/` module layout collapse.
- IG-660 — Approve → StrangeLoop implement handoff.

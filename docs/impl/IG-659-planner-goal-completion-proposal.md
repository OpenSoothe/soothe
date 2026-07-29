# IG-659: Planner Goal Completion Proposal and Module Layout

**Created**: 2026-07-29  
**Status**: Implemented  
**Related**: [RFC-633](../specs/RFC-633-planner-plan-artifact-and-human-review.md), [RFC-618](../specs/RFC-618-plan-subagent-delegation.md), [IG-658](IG-658-planner-readonly-tools-plan-review.md)

---

## Executive Summary

Reframe the intake **planner** subagent so its deliverable is a **solution report**
for the user goal (decided Solution + concrete Changes), not a findings dump and
not an investigation roadmap of further reads. Readonly filesystem tools remain
the only tool surface and exist to ground the report during recon. Collapse
`soothe-nano` `subagents/plan/` micro-modules into `__init__.py` + `engine.py`
(each well under 1000 lines).

---

## Design

### A. Product contract (soothe-nano)

1. Given a user goal query, planner produces a **solution report** in
   `plan_markdown` with sections: **Goal**, **Solution**, **Design principles**,
   **Architecture changes**, **Changes**, **Evidence**, **Risks & assumptions**,
   **Open questions**. Design principles / Architecture changes are filled when
   the goal implies structural or principled work; otherwise `None`.
2. **Solution** states the decided outcome. **Changes** are concrete
   edit/add/remove steps with workspace-relative paths — never
   read/diagnose/investigate steps (recon already did that).
3. Recon (readonly `ls` / `glob` / `grep` / `read_file` / `file_info`) gathers
   facts so the report can prescribe changes; tool output stays internal
   (findings / orphan card rows), never the final AIMessage.
4. Human review gate (host RFC-633) unchanged: Approve / Reject / More comments
   on the report artifact.
5. Plugin description and system prompts match this contract (no “collect
   findings” or “we will first read…” framing).

### B. Module layout (soothe-nano `subagents/plan/`)

Target (≤1000 lines per module):

```text
subagents/plan/
  __init__.py   # PlanPlugin + public re-exports; loads engine for event side-effects
  engine.py     # schemas, events, readonly tools, factory, LangGraph, prompts
```

Delete: `implementation.py`, `tools.py`, `schemas.py`, `events.py`.

Soft cap: split again only if `engine.py` approaches ~900 LOC (prefer
`prompts` or expanded tools first).

### C. Specs

1. Amend RFC-633 abstract/goals: deliverable is goal-completion proposal;
   recon is grounding, not the product.
2. Point RFC-618 / IG-658 readers at this IG for layout + proposal framing.

### D. Host / CLI

No behavioral change required beyond consuming the same markdown artifact
(proposal-shaped body). Orphan tool rows and review UX stay as IG-658.

---

## Cleanse

- Drop micro-module import paths (`plan.schemas`, `plan.tools`, `plan.events`,
  `plan.implementation`); re-export from `plan` / `plan.engine`.
- Drop findings-first prompt language; findings labeled as grounding evidence
  in draft prompts only.
- `subagents/__init__.py` imports plan package/engine for wire registration
  (no separate `plan.events` module).

---

## Acceptance

- [x] Planner system prompts require solution-report sections (Goal / Solution /
  Design principles / Architecture changes / Changes)
- [x] Prompts forbid investigation-roadmap Changes (read / diagnose / determine whether)
- [x] Readonly tools only; final message is solution report markdown, not recon dump
- [x] `subagents/plan/` is `__init__.py` + `engine.py` only; each &lt; 1000 lines
- [x] Tests import from `plan.engine` / package; event progress still registers
- [x] Prompt-contract unit tests green in soothe-nano
- [x] RFC-633 amended for solution-report framing

---

## Out of scope

- Auto-executing approved proposals into StrangeLoop plan-execute waves
- Mutating / shell tools on the planner thread
- Host artifact path or clarification origin changes

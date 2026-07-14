# IG-538: Unified Planner Prompt Assembly

**IG**: 538  
**Title**: Unified Planner Prompt Assembly  
**Status**: Implemented  
**Created**: 2026-07-01  
**RFCs**: RFC-214 §4 / P6, RFC-226  
**Draft**: `docs/archive/drafts/2026-07-01-unified-planner-prompt-projection-design.md`

## Overview

Unify continuation-discriminate, plan-assess, and plan-generate prompt assembly: **system + projected ledger + task envelope**. Two projection modes (`new_goal` / `mid_goal`). Plain-text `GOAL:` / `PRIOR GOALS:` / `TASK:` sections.

## Scope

| In | Out |
|----|-----|
| `project_planner_ledger(mode)` phase filter | `goal_id` on ledger messages |
| `assemble_planner_prompt` / `PromptBuilder` delegation | Config template sync (defaults only) |
| Continuation via same assembler | Execute envelope changes |
| PRIOR GOALS nested list + completion dedup | Recording continuation in ledger |

## Files

| File | Change |
|------|--------|
| `prompts/plan_ledger_projection.py` | `resolve_planner_projection_mode`, `project_planner_ledger` |
| `prompts/planner_assembly.py` | mode + completion-in-ledger helpers |
| `prompts/builder.py` | unified assembly, remove ledger skip |
| `prompts/user_message.py` | GOAL preview, PRIOR GOALS tree, continuation TASK |
| `prompts/fragments/instructions/plan_continuation_discriminate.xml` | continuation system fragment |
| `cognition/planner.py` | `assess_continuation` uses builder |
| `orchestrator/nodes/plan_assess.py` | pass state/context/checkpoint to assess_continuation |
| tests | update continuation + projection tests |

## Acceptance

1. `new_goal`: assess and generate project identical ledger (plan + goal_completion; no execute).
2. No `PRIOR GOAL COMPLETION:` in envelope when completion is in projected ledger.
3. `PRIOR GOALS:` uses `GOAL: description (status)` nested list.
4. Continuation uses system + ledger + task (not inline prompt string).
5. `mid_goal`: all phases in ledger (unchanged behavior).
6. `./scripts/verify_finally.sh` passes.

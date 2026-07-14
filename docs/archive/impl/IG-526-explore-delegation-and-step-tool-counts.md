# IG-526: Explore Delegation Wiring and Step Tool-Count Accuracy

**IG**: 526  
**Title**: Wire planner explore hints to executor; fix inflated step-card tool counts  
**Status**: Done  
**Created**: 2026-06-29  
**Related RFCs**: RFC-628 (step-card activity model)  
**Motivation**: Loop `[0882]` analysis — step `LWZ-01` burned 35 main-graph tools before a late `general-purpose` task delegation; TUI status line showed ~70 tools because server totals included subgraph tools.

---

## Summary

Three coordinated fixes improve tool-call efficiency and TUI accuracy for readonly recon steps:

1. **Planner → executor subagent wiring** — `execution_hint='subagent'` + `subagent='explore'` on plan steps now resolve to `wire_subagent` and flow into `soothe_step_subagent` on the first LLM hop (middleware enforces explore routing).
2. **`general-purpose` → `explore` remap** — When explore is registered, the patched `task` tool remaps LLM-chosen `general-purpose` to `explore` before invoke.
3. **Main vs subgraph tool counts** — Executor stores main-graph and subgraph counts separately; TUI step cards display main-only totals so delegated steps no longer double-count subagent tools in the footer.

**Explicitly out of scope:** runtime keyword/grep-failure heuristics to nudge explore (not general enough for production).

---

## Problem (loop 0882)

| Observation | Root cause |
|-------------|------------|
| 35 `[ExecuteTool]` before `task`, ~39 `[SubagentTool]` after | Late delegation; core agent searched directly instead of routing early |
| `task` used `subagent_type='general-purpose'` | deepagents default; explore not enforced on first hop |
| `wire_subagent=None` at step start | Planner hints (`execution_hint`, `subagent`) were prompt-only — not in structured schema or executor config |
| TUI showed ~70 tools | Server `tool_call_count` = main + subgraph; step card treated server fallback as authoritative |

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| `PlanGenerateStep` / `StepAction` execution routing fields | Grep-failure keyword heuristic policy |
| `resolve_wire_subagent_for_step()` (planner hint > wire routing) | Demoting/removing `general-purpose` from soothe_deepagents tool description |
| Explore workspace-relative path hints in execution envelope | SubAgent card footer changes (IG-515) |
| `general-purpose` → `explore` remap in task tool patch | |
| Split `StepResult.tool_call_count` / `subgraph_tool_call_count` | |
| TUI main-only stats in status line and row classifier | |

---

## Design

### 1. Planner structured output

Added to `PlanGenerateStep` and `StepAction`:

- `execution_hint`: `tool` | `subagent` | `remote` | `auto`
- `subagent`: capability name when hint is `subagent`
- `wire_subagent`: resolved executor hint (computed, not LLM-authored)

Helpers:

- `resolve_step_wire_subagent()` — maps `execution_hint='subagent'` → subagent name (default `explore`)
- `apply_step_wire_subagents()` — attaches `wire_subagent` on finalized steps
- `plan_generate_steps_to_step_actions()` — converts planner steps with wiring

Planner prompt updates:

- JSON example includes `execution_hint` / `subagent`
- Efficiency rule: heavy readonly recon → `execution_hint='subagent'`, `subagent='explore'`
- `_finalize_generated_plan_result()` and `_apply_preferred_subagent_to_decision()` set `wire_subagent`

### 2. Executor routing

- Single-step path: `resolve_wire_subagent_for_step(step, routing_classification)` replaces routing-only lookup
- Batch path (`_build_batch_human_messages`): per-step `wire_subagent` + workspace-relative path hints when explore
- Configurable: `soothe_step_subagent = wire_subagent` (existing middleware reads this on hop 0)

### 3. Task tool remap

In `_patch_task_tool.py`, before subagent invoke:

```python
if subagent_type == "general-purpose" and "explore" in subagent_graphs:
    subagent_type = "explore"
```

### 4. Tool count split

`_stream_and_collect` final yield is an 8-tuple: `(output, event, main_count, messages, delegate_final, outcomes, has_error, subgraph_count)`.

`StepResult`:

- `tool_call_count` — main-graph tools only (budget, wave metrics, TUI fallback)
- `subgraph_tool_call_count` — namespaced subagent tools

`step_completed` event payload includes `subgraph_tool_call_count`.

### 5. TUI step-card stats

`StepRowClassifier` / `stats_title_suffix()` use `main_tool_count`.

`row_counts_for_step_tool_total()` excludes:

- task rows and task-metadata-only rows
- rows with `parent_tool_call_id` (subgraph children)
- unified IDs with type `t`

`_status_tool_stats_suffix()` uses server `fallback_count` only when there are no local rows and no task delegations — prevents inflated main+subgraph server totals from overwriting tracked main-only counts.

---

## Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/foundation/sloop/state/schemas.py` | Routing fields, helpers, `StepResult.subgraph_tool_call_count` |
| `packages/soothe/src/soothe/foundation/sloop/engine/thread_selection.py` | `resolve_wire_subagent_for_step()` |
| `packages/soothe/src/soothe/foundation/sloop/engine/executor.py` | Per-step wiring, path hints, split counts |
| `packages/soothe/src/soothe/foundation/sloop/planning/planner.py` | Prompt + finalize wiring |
| `packages/soothe/src/soothe/foundation/core/agent/_patch_task_tool.py` | `general-purpose` → `explore` remap |
| `packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/execute_steps.py` | `subgraph_tool_call_count` in step_completed |
| `packages/soothe-cli/.../cognition_step_activity.py` | Main-only row classification and stats |
| `packages/soothe-cli/.../cognition_step.py` | Main-only status suffix logic |
| `packages/soothe/tests/...` | Schema, executor, planner, delegate-finals tests |
| `packages/soothe-cli/tests/...` | Activity and running-stats tests |

---

## Verification

```bash
./scripts/verify_finally.sh
```

Key behavioral checks:

- Planner step with `execution_hint='subagent'` → `soothe_step_subagent='explore'` on first hop
- Step card with 1 main tool + task delegation + subgraph tools → footer shows `1 tool, 1 task`, not ~70
- Server fallback with inflated count ignored when local main rows exist

---

## Expected impact

- Readonly recon steps delegate to explore on the first hop when the planner sets routing hints
- Accidental `general-purpose` task calls route to explore when available
- Step status lines reflect main-graph tool usage (~35 in loop 0882 scenario), with subgraph work visible on SubAgent cards

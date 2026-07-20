# IG-580: Ledger-Direct Structural Gates & Auto Final Response

**RFC**: [RFC-219](../specs/RFC-219-goal-completion-module.md)
**Created**: 2026-07-11
**Status**: Implemented

## Problem

Loop `2281` goal_1 (`continue` bootstrap, `require_goal_completion=False`) produced an ill-assembled completion report:

1. **`ledger_direct`** copied the last execute-step AI monologue (171 tool calls) with no synthesis pass.
2. **`execute_ai_ledger_max_tokens: 2048`** compacted the ledger row head-first (`strategy="last"`), yielding a report that started mid-word (`ion to "Complete only this step's deliverable"…`).
3. Legacy **content heuristics** (`is_rich_enough`, `overlaps_with_plan_output`) did not run on the `require_goal_completion=False` fast path anyway.

## Solution

### 1. Rename `final_response: adaptive` → `auto`

- Literal type: `auto | always_synthesize`
- Config accepts deprecated alias `adaptive` → `auto` (validator on `AgentConfig` and `StrangeLoopConfig`)
- Behavior unchanged except for narrowed `ledger_direct` (below)

### 2. Unified structural strategy tree

`determine_completion_strategy` now uses one decision tree:

| Order | Condition | Strategy |
|-------|-----------|----------|
| 1 | `always_synthesize` | synthesize |
| 2 | `require_goal_completion=True` | synthesize |
| 3 | `_dag_requires_synthesis(...)` | synthesize |
| 4 | empty ledger | synthesize |
| 5 | `_ledger_direct_eligible(...)` | ledger_direct |
| 6 | default | synthesize |

### 3. Remove legacy content heuristics

Deleted from `completion.py`:

- `can_return_directly_from_ledger`
- `is_rich_enough`
- `overlaps_with_plan_output`

Removed config fields:

- `structured_payload_min_lines`
- `rich_text_min_chars`
- `ledger_overlap_min_token_len`

### 4. New structural gate: `ledger_direct_max_tool_calls`

Default **50**. Loop 2281 (171 tools) would synthesize.

`_ledger_direct_eligible` also requires:

- `plan_wave_count <= 1`
- `failed_steps == 0`
- `total_steps <= simple_ledger_direct_max_steps` (default tightened to **1**)
- no DAG dependencies

`terminal_after_execute` (RFC-226) remains a routing flag only — does not force `ledger_direct`.

### 5. Raise execute AI ledger cap

`execute_ai_ledger_max_tokens`: **2048 → 65536** (safety net when `ledger_direct` is legitimately selected; does not replace synthesis for tool-heavy steps).

## Changes

| Area | File |
|------|------|
| Strategy logic | `packages/soothe/src/soothe/foundation/context/planning/completion.py` |
| Adapter wiring | `packages/soothe/src/soothe/foundation/context/planning/step_planner.py` |
| Config models | `packages/soothe/src/soothe/config/models.py` |
| Template + develop config | `config/config.template.yml`, `config/develop/config.yml` |
| RFC | `docs/specs/RFC-219-goal-completion-module.md` |
| Tests | `test_ig624_3_planning_submodule.py`, `test_goal_completion_policy.py`, orchestrator ledger tests |

## Config

```yaml
agent:
  final_response: auto   # legacy alias: adaptive

agent.loop:
  final_response: auto
  rules:
    completion:
      simple_ledger_direct_max_steps: 1
      ledger_direct_max_tool_calls: 50
  execute_prompt_ledger:
    execute_ai_ledger_max_tokens: 65536
```

## Verification

- `./scripts/verify_finally.sh`
- Unit: `test_ig624_3_planning_submodule.py` (`test_tool_heavy_wave_synthesizes`, `_ledger_direct_eligible`)
- Regression: continuation bootstrap with >50 tool calls → `action=synthesize` in goal_completion logs

## Cleanup (legacy removed)

- Content heuristics: `can_return_directly_from_ledger`, `is_rich_enough`, `overlaps_with_plan_output`
- Config fields: `structured_payload_min_lines`, `rich_text_min_chars`, `ledger_overlap_min_token_len`
- Dead stub: `docs/impl/IG-XXX-ledger-context-bounds.md`
- Removed `CompletionStrategy.SUMMARY` (fallback summary runs inside `SYNTHESIZE` when the stream is empty)
- Removed `normalize_final_response_mode` re-export from `completion.py`
- Renamed `test_strange_loop_adaptive_final.py` → `test_strange_loop_auto_final.py`
- Updated stale comments (`adaptive` → `auto`) in executor, act_wave_finalize, LoopState
- Updated `docs/wiki/changelog.md` config example

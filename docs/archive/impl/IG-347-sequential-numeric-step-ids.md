# IG-347: Sequential numeric step IDs (`1`, `2`, …)

## Status

Complete.

## Goal

Use stable, human-readable step identifiers (`"1"`, `"2"`, …) instead of UUID fragments or ad-hoc `step_0` strings. In-plan `dependencies` reference the same IDs; cross-wave references (e.g. prior `step_001` from evidence) stay unchanged (IG-346).

## Implementation

- Add `normalize_sequential_step_ids(decision)` in `state/schemas.py`.
- Invoke after `_resolve_decision` in `AgentLoop` so every execute path (parse, keep, bootstrap) is normalized.
- Align fallbacks: `_default_agent_decision` and `agent_decision_from_dict` use `"1"` / `str(i+1)` where applicable.

## Files

- `packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py`
- `packages/soothe/src/soothe/cognition/agent_loop/core/agent_loop.py`
- `packages/soothe/src/soothe/cognition/agent_loop/utils/reflection.py`
- `packages/soothe/tests/unit/cognition/agent_loop/state/test_schemas.py`

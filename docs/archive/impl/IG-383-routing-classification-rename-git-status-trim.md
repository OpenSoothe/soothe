# IG-383: `routing_classification` rename + trim `git_status.status`

## Scope

1. Rename AgentLoop / CoreAgent graph state field `unified_classification` → `routing_classification` (value remains `RoutingClassification`). `LoopState` and `PlanContext` accept legacy JSON key `unified_classification` via Pydantic `validation_alias`.
2. Remove `git_status["status"]` from `get_git_status()` output and skip `git status --short` (fewer subprocess calls). Middleware workspace XML no longer emits `<status>`.

3. `SystemPromptOptimizationMiddleware` still accepts legacy graph key `unified_classification` as a fallback when reading classification.

## Files

- `packages/soothe/src/soothe/core/workspace/resolution.py`
- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py`
- `packages/soothe/src/soothe/protocols/planner.py`
- `packages/soothe/src/soothe/core/agent_loop/core/{executor,agent_loop,planner}.py`
- `packages/soothe/src/soothe/core/runner/{routing_merge,_runner_phases,_runner_agentic,_runner_autonomous}.py`
- `packages/soothe/src/soothe/middleware/{system_prompt_optimization,_builder}.py`
- Tests: `test_system_prompt_optimization.py`, `test_autonomous_layer2_integration.py`, `test_dynamic_system_context.py`

## Verification

`./scripts/verify_finally.sh`

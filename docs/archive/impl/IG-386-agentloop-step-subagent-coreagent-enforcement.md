# IG-386: AgentLoop step subagent hint → CoreAgent enforcement

## Goal

When `Executor` passes `soothe_step_subagent` in `RunnableConfig.configurable` (from `StepAction.subagent`), the CoreAgent runtime must **delegate via the `task` tool** to that subagent on the first model hop—not call root filesystem/shell/web tools directly.

## Problem

Hints were only appended as advisory text (`ExecutionHintsMiddleware`). `SystemPromptOptimizationMiddleware` already enforced task-only + `<SUBAGENT_ROUTING_DIRECTIVE>` for wire routing (`routing_hint=subagent` + `preferred_subagent`), but **did not** read `soothe_step_subagent` from LangGraph config.

## Approach

In `SystemPromptOptimizationMiddleware.modify_request`, read `configurable["soothe_step_subagent"]` via `langgraph.config.get_config()`. When non-empty and the model turn is the first reply after the latest `HumanMessage`, apply the same behavior as explicit wire subagent routing:

- Set `_subagent_routing_directive` (prompt block + tool narrowing).
- Narrow tools to `task` only.

**Precedence:** Per-step `soothe_step_subagent` overrides wire `preferred_subagent` when both would enforce on the same hop (step-specific hint wins).

## Verification

- Unit tests in `test_system_prompt_optimization.py` for explore hint + task-only tools.
- `./scripts/verify_finally.sh`

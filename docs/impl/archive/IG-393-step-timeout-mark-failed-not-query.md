# IG-393 — Per-step LLM timeout: mark step failed, not whole query

**Status:** Historical. The runner’s legacy `_stream_phase` / `_runner_steps` DAG path was removed; interactive execution is **AgentLoop → `Executor._execute_step_collecting_events`**, which already maps per-call timeouts to `StepResult(success=False)` without surfacing a top-level `soothe.error.general` for the whole query when the failure is step-scoped.

When auditing timeout behavior, read:

- `packages/soothe/src/soothe/core/loop/engine/executor.py` — execute-wave streaming and step outcomes.
- `packages/soothe/tests/unit/core/loop/engine/` — executor timeout / HITL tests.

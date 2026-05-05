# IG-393: LLM timeout fails the plan step, not the whole query

## Requirement

When a per-call LLM timeout occurs **during DAG step execution** (`_run_step_loop` / `_execute_step`), the step must be marked failed (`PlanStepFailedEvent`, scheduler state) while the overall query must **not** surface as a top-level `soothe.error.general` failure.

## Implementation

- `packages/soothe/src/soothe/core/runner/_runner_phases.py`: `_stream_phase(..., suppress_global_error_on_llm_timeout=False)`. When True and the exception is `TimeoutError`, set `state.stream_error` as today but **omit** `yield _custom(emit_error_event(exc))`.
- `packages/soothe/src/soothe/core/runner/_runner_steps.py`: Call `_stream_phase` with `suppress_global_error_on_llm_timeout=True`. Improve empty timeout message to `"LLM call timed out"` for `step.result`.

**Note:** Default agentic execution (`AgentLoop` → `Executor._execute_step_collecting_events`) already returns `StepResult(success=False)` without runner `_stream_phase`; no change there.

## Tests

`packages/soothe/tests/unit/core/runner/test_stream_phase_step_timeout.py`

## Verification

`./scripts/verify_finally.sh`

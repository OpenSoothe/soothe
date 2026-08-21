# IG-756: Single intake classify LLM call

**Status**: superseded — the pre-graph social gate was removed; see below.
**Related**: RFC-630 (intake), RFC-220 (loop graph)

## Problem (original)

A new task turn ran two structured intake LLM calls:

1. Pre-graph social gate (`classify_social_gate`)
2. Graph-entry `classify_intake`

Both used the same schema. The gate result was discarded on the task path
(`state.intent` left unset), so the second sample drove routing and the step
card. Langfuse showed two `intake-classify` generations.

## Original change (superseded)

The original fix reused the pre-graph task verdict as loop intent so
`node_intent_classify` skipped the second LLM call. This introduced a
regression: the social gate ran **before CE was bound** and received no
`ledger_messages`, so the second goal's intake saw 0 projected messages and
wrote "No prior context provided" reasoning.

## Current design

The pre-graph social gate is **deleted entirely**. The in-graph
`node_intent_classify` (`stations/preprocess/intake.py`) is the sole intake
classification call site. It projects the full CE ledger (prior-goal completion
+ preamble) via `classify_intake` → `_project_ledger_for_intake` →
`project_last_goal_completion_for_intake`, so the second goal sees the first
goal's context.

### What was removed

- `classify_social_gate` on the `IntentClassifier` facade and
  `IntakeCoordinator`.
- `_task_intent_from_pre_graph_intake` helper in `strange_loop.py`.
- The pre-graph social-gate block in `strange_loop.run_with_progress` (~160
  lines): the `classify_social_gate` call, social-result chitchat fast-path
  yield, `social_gate_token_sink`, `gate_task_intent` promotion, and the
  loop-control override of a social verdict.
- `IntakeLangfuseSpan` / `open_intake_langfuse_span` module
  (`_intake_span.py`) — the graph node inherits the LangGraph RunnableConfig.
- `with_intake_parent_span` / `intake_parent_span_id` / `nest_under_intake_span`
  / `_intake_parent_handler` on `GoalLoopTrace`.
- `intake_langfuse_run_display_name` / `_HOST_INTAKE_RUN_NAME` — the fallback
  run name, never reached since `intake_invoke_config` defaults to
  `phase="intake_classify"`.
- `should_bypass_social_gate_fast_path` renamed to
  `should_bypass_chitchat_fast_path` (the social gate is gone; this is the
  in-graph chitchat bypass used by `enter_loop`).

### Chitchat path now

Chitchat no longer short-circuits before CE/graph setup. It flows:
INTAKE node classifies (with ledger) → chitchat verdict → `enter_loop`
fast-path → END. The structural continuation bypass
(`should_bypass_chitchat_fast_path`) is checkpoint-based and lives in
`enter_loop.py`.

## Validation

- `packages/soothe/tests/unit/core/loop/core/test_strange_loop_intake_progress.py`
- `packages/soothe/tests/unit/core/loop/orchestrator/test_loop_graph_langfuse_config.py`
- `packages/soothe/tests/unit/core/loop/orchestrator/stations/test_intake_langfuse_config.py`
- `./scripts/verify_finally.sh`

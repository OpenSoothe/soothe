# IG-756: Single intake classify LLM call

**Status**: done
**Related**: RFC-630 (intake), RFC-220 (loop graph)

## Problem

A new task turn ran two structured intake LLM calls:

1. Pre-graph social gate (`classify_social_gate`)
2. Graph-entry `classify_intake`

Both used the same schema. The gate result was discarded on the task path
(`state.intent` left unset), so the second sample drove routing and the step
card. Langfuse showed two `intake-classify` generations. The graph phase
`strange_loop_graph` was also aliased to the same display name.

## Change

Reuse the pre-graph task verdict as loop intent:

- Convert `IntakeLLMResult` → `IntentClassification` after the social gate
  confirms a task (including loop-control override of a social verdict).
- Set `LoopState.intent` / routing from that result so `node_intent_classify`
  skips the second LLM call.
- Yield `intent_classified_reasoning` from the gate result for the TUI.

`classify_intake` remains for paths that skip the gate (interrupt resume,
missing classifier result).

## Cleanse

- Dropped `_HOST_INTAKE_PHASE_RUN_NAMES["strange_loop_graph"] = "intake-classify"`
  so the loop graph root stays `strange-loop-graph` and only the classify LLM
  uses `intake-classify`.
- Removed unused `classify_intake` kwargs (`thread_id`, `context_engine`,
  `observability_phase`, `observability_component`) left from dual-call tracing
  and removed CE ledger writes.

## Validation

- `packages/soothe/tests/unit/core/loop/engine/test_strange_loop_intake_progress.py`
- `packages/soothe/tests/unit/core/loop/orchestrator/test_loop_graph_langfuse_config.py`
- `./scripts/verify_finally.sh`

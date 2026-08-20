# IG-746: Intake station span on the goal-loop Langfuse trace

**RFCs**: RFC-220 (Loop Graph), RFC-630 (two-pass intake)
**Related**: IG-663 (stem station run names), IG-672 (evaluate parent span),
IG-747 (generate_plan parent span)

## Problem

Langfuse showed no intake stage. `GoalLoopTrace` was allocated and intake calls
did receive `intake_invoke_config`, but nothing opened an observation for the
pre-graph station itself:

- The social gate runs **pre-graph**, so its generation is a LangChain *root* run.
  The pinned handler attaches it to the trace via `trace_context={"trace_id": …}`,
  which the Langfuse SDK resolves through a synthetic remote parent — the run
  lands at trace root, never under `strange-loop-graph`.
- The graph-entry classifier must inherit the graph callback handler; a separate
  pinned handler cannot resolve the LangGraph node's `parent_run_id`.
- On the social fast-path the turn returns before the graph runs, so
  neither `patch_goal_io` nor its `client.flush()` ever executed and the batched
  observations could be lost.

`evaluate` does not have this problem because it opens an explicit parent span.

## Approach

Mirror the evaluate station for the pre-graph social gate, but thread the parent
**explicitly** instead of via OTEL ambient context. Generator suspension points
could otherwise leak a current-span context manager into unrelated tasks. The
graph-entry classifier reuses the active graph callback hierarchy.

| Piece | Behavior |
|---|---|
| `_intake_span.open_intake_langfuse_span` | Opens a non-current `intake` span on the goal-loop trace; returns an inert handle when tracing is off or the client fails |
| `IntakeLangfuseSpan.end` | Idempotent close with optional output |
| `GoalLoopTrace.with_intake_parent_span` | Frozen-dataclass view carrying `intake_parent_span_id` |
| `GoalLoopTrace.intake_invoke_config` | Pins pre-graph intake to `{trace_id, parent_span_id}`; graph-entry classification flattens inherited graph handlers onto an explicit list so nano structured-output never sees LangGraph's `AsyncCallbackManager` |
| `intake_phase_langfuse_run_display_name` | Child run names `intake-pass1`, `intake-pass2`, `intake-classify` (default stays `intake`) |
| `SootheLangfuse.flush` | Exports buffered observations for turns that end before the graph |

`_client.host_langfuse_client` consolidates client resolution shared by the
intake span, the evaluate span, and flush.

## Call sites

- `StrangeLoop.run_with_progress`: opens the span only when intake actually runs
  pre-graph (no pre-classified intent, classifier present, not a clarification
  resume); passes the span-scoped trace to the social gate; closes on the task
  verdict, on the social fast-path (plus flush), and defensively in the outer
  `finally`.
- `node_intent_classify`: inherits the graph node's RunnableConfig so its model
  generation remains under the LangGraph `intake` observation.

## Result

Pre-graph social-gate generations nest under the explicit `intake` span.
Graph-entry `intake-classify` generations remain under the LangGraph `intake`
node, and social turns are exported instead of dropped.

## Cleanse (follow-up)

- Shared `_station_span` for evaluate + generate_plan; dropped evaluate-only
  planner phase alias in favor of `_planner_langfuse_phase_name`.
- `GoalLoopTrace.pinned_llm_invoke_config` for non-intake direct LLM calls;
  execute auxiliaries no longer mislabel as `intake`.
- Consolidated `resolve_loop_planner`; trimmed unused sync span re-exports.
- Pass 1/2 no-goal_trace fallbacks use `*:intake-pass{N}` naming.

## Validation

- `packages/soothe/tests/unit/core/loop/orchestrator/stages/test_intake_langfuse_span.py`
- `packages/soothe/tests/unit/core/loop/engine/test_strange_loop_langfuse_goal_trace.py`
- `./scripts/verify_finally.sh`

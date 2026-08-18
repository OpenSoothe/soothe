# IG-746: Intake station span on the goal-loop Langfuse trace

**RFCs**: RFC-220 (Loop Graph), RFC-630 (two-pass intake)
**Related**: IG-663 (stem station run names), IG-672 (evaluate parent span),
IG-747 (generate_plan parent span)

## Problem

Langfuse showed no intake stage. `GoalLoopTrace` was allocated and Pass 1 / Pass 2
did receive `intake_invoke_config`, but nothing opened an observation for the
station itself:

- Both passes run **pre-graph**, so their generations are LangChain *root* runs.
  The pinned handler attaches them to the trace via `trace_context={"trace_id": …}`,
  which the Langfuse SDK resolves through a synthetic remote parent — the run
  lands at trace root, never under `strange-loop-graph`.
- The graph entry station logs `Skipping graph entry classification (pre-classified: …)`
  on the normal path, so `intake` produced no observation there either.
- On the Pass 1 social fast-path the turn returns before the graph runs, so
  neither `patch_goal_io` nor its `client.flush()` ever executed and the batched
  observations could be lost.

`evaluate` does not have this problem because it opens an explicit parent span.

## Approach

Mirror the evaluate station, but thread the parent **explicitly** instead of via
OTEL ambient context: pre-graph Pass 1 and Pass 2 are separated by checkpoint and
Context Engine work and by generator suspension points, where a current-span
context manager would leak into unrelated tasks.

| Piece | Behavior |
|---|---|
| `_intake_span.open_intake_langfuse_span` | Opens a non-current `intake` span on the goal-loop trace; returns an inert handle when tracing is off or the client fails |
| `IntakeLangfuseSpan.end` | Idempotent close with optional output |
| `GoalLoopTrace.with_intake_parent_span` | Frozen-dataclass view carrying `intake_parent_span_id` |
| `GoalLoopTrace.intake_invoke_config` | Builds a handler pinned to `{trace_id, parent_span_id}` so intake generations nest under the span |
| `intake_phase_langfuse_run_display_name` | Child run names `intake-pass1`, `intake-pass2`, `intake-classify` (default stays `intake`) |
| `SootheLangfuse.flush` | Exports buffered observations for turns that end before the graph |

`_client.host_langfuse_client` consolidates client resolution shared by the
intake span, the evaluate span, and flush.

## Call sites

- `StrangeLoop.run_with_progress`: opens the span only when intake actually runs
  pre-graph (no pre-classified intent, classifier present, not a clarification
  resume); passes the span-scoped trace to both passes; closes on the Pass 2
  result, on the social fast-path (plus flush), and defensively in the outer
  `finally`.
- `node_intent_classify`: opens its own span for turns that classify inside the
  graph, closing it on success and on error.

## Result

One `intake` span per turn on the goal-loop trace, with `intake-pass1` /
`intake-pass2` (or `intake-classify`) generations nested under it, and social
turns exported instead of dropped.

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

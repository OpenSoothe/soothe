# IG-395: Langfuse trace input/output from goal and completion

## Purpose

Set Langfuse root trace `input` to the user goal text and `output` to the last goal-visible response so exports and the trace list show meaningful I/O (nested spans remain unchanged).

## Scope

- After `invoke_agent_loop_graph` completes, merge trace fields on the active Langfuse trace id
  (`last_trace_id` on the LangChain callback handler) via SDK-internal ``trace-create`` ingestion
  (`TraceBody`: `name`, `input`, `output`, optional `session_id`) so the trace row keeps the same
  display name as the graph run (e.g. `soothe-dev:agent-loop-graph`) and does not pick up a dummy
  span title. Fallback: `start_span(trace_context=...).update_trace(name=..., ...)`.
- Input: `LoopState.goal`.
- Output: `GoalExecutionRecord.goal_completion` when set; else fall back to `PlanResult.full_output`, `PlanResult.next_action`, or `last_execute_assistant_text`.

## Status

- Completed: `patch_langfuse_trace_goal_io` + `invoke_agent_loop_graph` post-hook; tests in
  `packages/soothe/tests/unit/utils/observability/test_langfuse_trace_goal_io.py` and
  `packages/soothe/tests/unit/core/agent_loop/graph/test_loop_runner_langfuse_output.py`.

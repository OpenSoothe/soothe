# IG-355: Subagent delegate finals → goal completion wire (headless parity)

## Status: Completed

## Problem

Headless CLI (`--no-tui`) shows RFC-614 loop–tagged assistant text only. Subagent work streams under LangGraph namespaces; intermediate subgraph AIMessages are intentionally excluded from root-graph act aggregation (`iter_messages_for_act_aggregation`). Goal completion (`skip`/`direct`) skipped replaying `phase=goal_completion`, assuming the user already saw the answer—false when the answer lived only in **`task` tool return bodies**.

## Approach (replaces IG-354 CLI workaround)

1. **Executor** [`packages/soothe/src/soothe/cognition/agent_loop/core/executor.py`](packages/soothe/src/soothe/cognition/agent_loop/core/executor.py): `_stream_and_collect` joins ordered **`task`** `ToolMessage` text into `delegate_final_text` (per-task / wave caps). `_record_execute_wave_for_finalize` sets `LoopState.last_execute_assistant_text` from those **delegate finals** when present (not subgraph AIMessage streams).

2. **LoopState** [`packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py`](packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py): `last_wave_answer_from_delegate_final` flags this source for wiring.

3. **AgentLoop** [`packages/soothe/src/soothe/cognition/agent_loop/core/agent_loop.py`](packages/soothe/src/soothe/cognition/agent_loop/core/agent_loop.py): `skip_goal_completion_wire_duplicate` is **False** when the completion path used delegate finals—so the runner emits one phased replay.

4. **Runner** [`packages/soothe/src/soothe/core/runner/_runner_agentic.py`](packages/soothe/src/soothe/core/runner/_runner_agentic.py): When `skip_goal_completion_wire_duplicate` is False and status is `done`, emit `loop_assistant_messages_chunk(..., phase="goal_completion")` from `full_output`, including **single-iteration** runs (not only `max_iterations > 1`).

5. **Namespaced ``task`` returns (Explore)** [`stream_normalize.iter_messages_for_delegate_task_scan`](packages/soothe/src/soothe/cognition/agent_loop/utils/stream_normalize.py): Compiled subgraphs (e.g. Explore) may emit the parent **`task`** `ToolMessage` only on **non-empty** LangGraph namespaces. Act aggregation intentionally skips those chunks for AIMessage/token metrics; delegate-final collection must still scan them so `last_execute_assistant_text` and goal-completion replay stay populated.

## Reverted

- IG-354 client flags (`headless_delegate_subgraph`) — removed.

## Verification

- `./scripts/verify_finally.sh`

## References

- IG-352 (evidence), RFC-614 (loop phases), RFC-201 (AgentLoop).

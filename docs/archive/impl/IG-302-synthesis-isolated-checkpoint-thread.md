# IG-302: Synthesis isolated checkpoint thread

## Problem

Goal-completion synthesis invoked `CoreAgent.astream` with the same `configurable.thread_id` as the AgentLoop run. LangGraph SQLite checkpointer replayed the full conversation (dozens of messages), so synthesis LLM traces were huge and slow despite a single new `HumanMessage`.

## Approach

1. Generate an ephemeral checkpoint key: `{parent_thread_id}__synth_gc__{uuid}`.
2. Pass that value as `configurable.thread_id` for `astream` only.
3. Keep `LoopHumanMessage.thread_id` and `tag_messages_stream_chunk_for_goal_completion(..., thread_id=state.thread_id)` as the **parent** thread so CLI/TUI and stream tagging stay correct.
4. Pass `configurable.workspace` when `LoopState.workspace` is set (same as Execute phase).

## Verification

`./scripts/verify_finally.sh`

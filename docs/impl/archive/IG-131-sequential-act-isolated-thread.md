# IG-131: Sequential Act isolated `thread_id` + merge

**Status**: DEPRECATED - Superseded by RFC-209

This implementation guide is superseded by RFC-209 (Executor Thread Isolation Simplification), which removes the need for manual thread ID generation and merge logic. The entire approach has been replaced with a simpler design that:

- Trusts langgraph's built-in concurrency handling for tool execution
- Leverages task tool's automatic isolation for subagent delegations
- Eliminates manual thread ID suffixes (`{thread_id}__l2act{uuid}`)
- Removes the merge logic (`_merge_isolated_act_into_parent_thread()`)

**No backward compatibility maintained**. Once RFC-209 is implemented, this guide becomes obsolete.

## Goal (Historical Context)

For Layer 2 **sequential** Act waves that are likely to delegate to a subagent, optionally run CoreAgent on a **fresh checkpoint branch** (no prior thread messages), then **merge** the produced `messages` back into the canonical `thread_id`.

## Config (`AgenticLoopConfig`)

- `sequential_act_isolated_thread` (default `false`): enable feature.
- `sequential_act_isolate_when_step_subagent_hint` (default `true`): when the above is true, isolate only if at least one `StepAction.subagent` is set; when `false`, isolate **every** sequential wave.

## Implementation

- `Executor._execute_sequential_chunk`: optional `child_thread_id = {main}__l2act{uuid}`; stream with that `configurable.thread_id`; on success, `aget_state(child)` → `aupdate_state(parent, {"messages": child_messages})`.
- Parallel steps already use per-step `thread_id` suffixes; not changed here.

## Caveats

- Isolated Act does **not** see prior Human/Assistant turns in LangGraph state; the model must rely on the step text, working memory, and Reason’s plan. Enable `subagent` hints on steps when Reason should delegate.
- Orphan child checkpoints may accumulate under SQLite until a future cleanup job exists.

## Reason vs checkpoint redundancy (review)

- **Reason** (`build_loop_reason_prompt` / `<SOOTHE_PRIOR_CONVERSATION>`) injects formatted excerpts from the checkpointer into a **separate** Reason LLM call.
- **Act** on the **same** `thread_id` loads the **full** `messages` channel from the checkpointer for CoreAgent. That is **not** the same forward pass as Reason, but the **same underlying history** is available twice across phases: once summarized/excerpted for Reason, once as native messages for Act.
- **System prompt** middleware does not duplicate the full thread by default; duplication is mainly **Reason excerpts vs Act message list** when both are sourced from the same checkpoint.
- With **isolated sequential Act** enabled for a wave, Act no longer sees prior turns during that wave; Reason (and step descriptions) become the only carriers of “what happened before,” reducing **cross-phase** overlap for that wave at the cost of stricter step authoring.

## Verification

`./scripts/verify_finally.sh`

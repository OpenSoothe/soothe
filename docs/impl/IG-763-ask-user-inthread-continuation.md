# IG-763: ask_user Answer Resume Continuation

**Created**: 2026-08-26
**Status**: Implemented
**Related**: RFC-622 (clarification relay), IG-762 (clarification-resume fatal)

## Problem

Observed on loop 6631: the user answers an `ask_user` question, the resume
records the answer, but no agent ever processes it.

The IG-762 synth path records the Q&A into the CE ledger and completes the
ask step, expecting "the next plan iteration re-reasons with the user's
answer." That assumption breaks when the ask step is the only step: the synth
marks it completed → action tree green → root_eval finalizes → the goal ends
with a summary. The answer reaches only the completion synthesis.

## Root cause

`Command(resume={iid: {"answers": [...]}})` cannot resume a CoreAgent
interrupt **because the executor's stream config inherits the parent graph's
checkpoint namespace** (found after ruling out several earlier theories —
see "Investigation trail" below).

`_executor_langfuse_merge_for_stream` merges the ambient StrangeLoop
execute-node config (`langgraph.config.get_config()`) into the CoreAgent
stream config to inherit tracing callbacks. That ambient config carries
`checkpoint_ns="execute:{task_id}"` — the StrangeLoop execute-node's own task
namespace. With it, langgraph runs the CoreAgent as a *parent subgraph*: its
checkpoints (including interrupts) are written under `execute:{task_id}` on
the step fork thread, the thread root stays empty, the stream surfaces the
interrupt as a raised `GraphInterrupt` instead of a graceful pause, and
`Command(resume)` on the thread root finds nothing. This single mechanism
explains the original loop-27d8 "namespace mismatch", the empty CE-step
recovery needs, and the dropped tool approvals.

Verified by A/B test with the real agent + real LLM (coreAgent invoked inside
an outer graph node, executor-style): contaminated config → fork thread has
only `execute:{uuid}` checkpoints, no root interrupt, resume impossible;
stripped config → root-namespace checkpoints, `Command(resume)` reaches the
interrupt, the approved `run_command` executes.

The first version of the strip also removed the config-injected
`__pregel_checkpointer` — the daemon attaches the checkpointer to the *main*
graph only (`agent.graph.checkpointer = ...`); the execution twin is compiled
without one and received it via the merged config. Stripping it made loop
776b run entirely checkpointer-less: no thread history at all, so the
answer's fresh turn continued nothing. The fix keeps the checkpointer and
strips only the coordinate keys.

### Investigation trail (ruled-out theories)

- *deepagents execute-node subgraph*: the `execute:{task_id}` namespaces are
  not part of the agent graph — they come from the inherited parent ns.
- *`durability="exit"`*: vanilla langgraph persists interrupt checkpoints at
  root even in exit mode; the A/B test confirms root checkpoints appear once
  the ns contamination is removed (durability unchanged).
- *tool-in-node vs middleware interrupt placement*: both pause gracefully in
  isolation.

## Design

With the checkpoint-ns fix restoring root-namespace interrupts, both
clarification resumes deliver **in-thread via `Command(resume=...)`**:

- **tool approval** (Branch 2): `{iid: {"decisions": [...]}}` — the HITL
  middleware returns the decision and the approved tool executes.
- **ask_user** (Branch 3): `{iid: {"answers": [...]}}` — the ask_user tool
  returns the formatted Q&A and the agent continues its turn on the original
  step thread.

Both verified end-to-end with the real agent, real LLM, and the daemon
topology (twin compiled checkpointer-less, checkpointer injected via the
stream config): approved `run_command` executed with its output; ask_user
returned `User answered: ... A: blue` and the agent continued.

An interim fresh-turn continuation envelope (Q&A in a `HumanMessage`) was
shipped while the root cause was still believed unfixable; it is removed by
this change — with root state persisting, a fresh input would land after the
dangling `ask_user` tool_call (broken conversation shape), while
`Command(resume)` answers it properly.

The Q&A pair is also appended to the loop ledger
(`_append_ask_user_loop_messages`) so the next plan iteration sees it.

The ledger synth path (IG-762) remains for planner-emitted `ask_user` steps
(no CoreAgent interrupt, nothing to continue).

## Changes

- `sloop/utils/graph_config.py` — `strip_parent_checkpoint_coordinates`
  (drops `checkpoint_ns` / `checkpoint_id` / `checkpoint_map`; **keeps** the
  config-injected `__pregel_checkpointer` — the execution twin is compiled
  without one and receives it via the config; stripping it too lost all
  persistence, the loop 776b regression).
- `sloop/engine/execute/executor.py` —
  `_executor_langfuse_merge_for_stream` strips the parent's checkpoint
  coordinates after the callback merge.
- `sloop/engine/completion/synthesis.py` — same strip for the goal-completion
  synthesis stream config (defensive; the direct-LLM stream does not
  checkpoint, but the leak is the same class).
- `sloop/stations/execute/execute.py` — CoreAgent ask_user answer resumes
  build `{iid: {"answers": [...]}}` and ride the same
  `Command(resume)` path as tool approvals (rebuild + executor + Q&A ledger
  append).

## Test coverage

- `test_stream_config_checkpoint_ns.py` — the strip helper drops the
  coordinate keys while preserving the config-injected checkpointer and
  tracing callbacks; the executor's merged stream config does the same.
- `node_execute`: an ask_user answer resume passes
  `{iid: {"answers": [...]}}` to the executor, rebuilds the decision on the
  original step, clears the channels, and appends the Q&A to the ledger.
- Executor: the resume payload is forwarded as the first CoreAgent input
  (`Command(resume=...)`), consumed one-shot.
- Planner-ask synth path tests (regression: `node_execute` →
  `node_record_iteration` with no fatal, recreated CE step completed).

## Follow-up: tool-approval resume (loop 573f)

The ask_user flow now works end-to-end (question → answer → fresh-turn
continuation → agent acts on the answer). Loop 573f then surfaced the
tool-approval path:

1. **Answer parsing (fixed).** The TUI's action selector submits
   ``[action, ""]`` — the action label plus a blank comment slot (the
   plan-review shape). For tool approval (one question), the interactive
   policy's ``_extract_answers`` hit ``any(not a ...)`` on the blank slot and
   dismissed every approval as "operator dismissed clarification (no
   answer)". Fixed by extending the action-selector tolerance (previously
   plan-mode-only) to ``tool_approval``: a non-empty action pads/truncates to
   the expected length.
2. **Delivery (fixed — checkpoint-ns contamination).** With the answer
   parsed, Branch 2 resumes via ``Command(resume={iid: {"decisions": ...}})``
   on the interrupted thread — which was silently dropped because the
   executor's stream config inherited the parent graph's
   ``checkpoint_ns="execute:{task_id}"`` (see Root cause), so the CoreAgent's
   interrupt never landed at the thread root. Fixed by stripping the parent's
   checkpoint coordinates from the merged stream config; verified by A/B test
   that the approved ``run_command`` now executes on resume. A host-side
   fresh-turn continuation is deliberately NOT used for tool approvals: the
   HITL middleware is stateless, so the agent re-issuing the approved tool
   call would re-trigger the interrupt — an approval click-loop.

## Verification

`./scripts/verify_finally.sh` green.

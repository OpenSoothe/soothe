# IG-198: AgentLoop prior thread excerpts for Plan phase

## Problem

Follow-up goals in the same LangGraph thread (e.g. "translate the report") did not see prior user/assistant turns in the **Reason/Plan** phase: `SootheRunner` computed `plan_conversation_excerpts` from the checkpointer and passed them to `AgentLoop.run_with_progress`, but that list was never merged into `LoopState.plan_conversation_excerpts` for new goals (parameter was marked unused).

## Change

- Merge `plan_conversation_excerpts` from the runner with goal-level excerpts and (when recovering) step-derived excerpts.
- Remove accidental `stderr` debug prints in `agent_loop.py`.
- Load and pass the same excerpts in `_runner_autonomous.py` (GoalEngine → AgentLoop), which previously omitted them.

## Verification

- `./scripts/verify_finally.sh`

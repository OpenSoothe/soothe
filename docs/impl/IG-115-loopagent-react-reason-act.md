# IG-115: LoopAgent ReAct (Reason + Act)

**Status**: Completed  
**Related**: RFC-201 Layer 2, RFC-0008

## Goal

Replace PLAN → ACT → JUDGE (two LLM calls per iteration) with **Reason → Act** (one LLM call per iteration). The Reason phase combines planning, progress assessment, and goal-distance estimation in a single structured response.

## Architecture

- **Reason**: `LoopReasonerProtocol.reason(goal, state, context) -> ReasonResult`
- **Act**: Existing `Executor` unchanged
- **Breaking**: `JudgeProtocol` removed; `PlannerProtocol.decide_steps` removed; event type `soothe.cognition.loop_agent.judgment` → `soothe.cognition.loop_agent.reason`

## Schema

- `ReasonResult`: `status`, `goal_progress`, `confidence`, `reasoning`, `user_summary`, `progress_detail`, `plan_action` (`keep` | `new`), `decision` (`AgentDecision | None`), `evidence_summary`, `next_steps_hint`, `full_output`
- `LoopState.previous_reason` replaces `previous_judgment`

## Event contract

- `LoopAgentReasonEvent`: `user_summary`, optional `progress_detail`, `status`, `progress`, `confidence`, `iteration`

## Files touched

- `src/soothe/protocols/loop_reasoner.py` (new)
- `src/soothe/protocols/judge.py` (removed)
- `src/soothe/cognition/loop_agent/reason.py` (new), `loop_agent.py`, `schemas.py`, `events.py`, `__init__.py`
- `src/soothe/backends/planning/simple.py`, `claude.py`, `router.py`
- `src/soothe/backends/judgment/` (remove `llm_judge` if unused)
- `src/soothe/core/runner/_runner_agentic.py`
- `src/soothe/ux/cli/stream/pipeline.py`
- Tests and checkhealth script as needed

## Verification

Run `./scripts/verify_finally.sh` before merge.

# IG-115: AgentLoop Plan-and-Execute (Plan + Execute)

**Status**: Completed  
**Related**: RFC-201 Layer 2, RFC-0008  
**Updated**: 2026-04-12 (terminology refactoring per IG-153)

## Goal

Replace PLAN → ACT → JUDGE (two LLM calls per iteration) with **Plan → Execute** (one LLM call per iteration). The Plan phase combines planning, progress assessment, and goal-distance estimation in a single structured response.

## Architecture

- **Plan**: `LoopPlannerProtocol.plan(goal, state, context) -> PlanResult`
- **Execute**: Existing `Executor` unchanged
- **Breaking**: `JudgeProtocol` removed; `PlannerProtocol.decide_steps` removed; event type `soothe.cognition.agent_loop.judgment` → `soothe.cognition.agent_loop.plan`

## Schema

- `PlanResult`: `status`, `goal_progress`, `confidence`, `reasoning`, `user_summary`, `progress_detail`, `plan_action` (`keep` | `new`), `decision` (`AgentDecision | None`), `evidence_summary`, `next_steps_hint`, `full_output`
- `LoopState.previous_plan` replaces `previous_judgment`

## Event contract

- `LoopAgentPlanEvent`: `user_summary`, optional `progress_detail`, `status`, `progress`, `confidence`, `iteration`

## Files touched

- `src/soothe/protocols/loop_planner.py` (new)
- `src/soothe/protocols/judge.py` (removed)
- `src/soothe/cognition/agent_loop/planning.py` (new), `loop_agent.py`, `schemas.py`, `events.py`, `__init__.py`
- `src/soothe/cognition/planning/simple.py`, `claude.py`, `router.py`
- `src/soothe/backends/judgment/` (remove `llm_judge` if unused)
- `src/soothe/core/runner/_runner_agentic.py`
- `src/soothe/ux/cli/stream/pipeline.py`
- Tests and checkhealth script as needed

## Verification

Run `./scripts/verify_finally.sh` before merge.

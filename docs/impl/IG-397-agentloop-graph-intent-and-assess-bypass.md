# IG-397: AgentLoop Graph Intent Classification and Assess Bypass

## Status
In Progress

## RFC Links
- RFC-220: LangGraph Agent Loop Orchestrator
- RFC-604: Plan Phase Robustness

## Goals
- Move intent classification into AgentLoop graph entry so runner no longer owns pre-loop classification.
- Apply the graph intent path for both agentic and autonomous AgentLoop execution paths.
- Bridge graph intent classification with Langfuse metadata for unified observability.
- Remove deprecated/backward compatibility helpers superseded by this cut-over.

## Scope
- `packages/soothe/src/soothe/core/agent_loop/graph/*`
- `packages/soothe/src/soothe/core/agent_loop/core/*`
- `packages/soothe/src/soothe/core/intention/*`
- `packages/soothe/src/soothe/core/runner/*`
- Prompt fragment updates under `packages/soothe/src/soothe/core/prompts/fragments/instructions/`
- Related unit tests under `packages/soothe/tests/unit/`

## Design Notes
- Graph entry node (`init_or_resume`) performs single-shot intent classification for each loop run.
- Fast-path intents (`chitchat`, `quiz`) emit an `intent_fast_path` event and terminate the graph before planning/execution nodes.
- Non-fast intents hydrate `LoopState.intent` and `LoopState.routing_classification` for downstream planner/executor use.

## Compatibility Decision (Cut Change)
- Remove backward-compat alias/function paths that duplicate routing merge naming.
- Keep one authoritative routing merge helper location.

## Verification Plan
- Add/adjust graph topology/routing tests.
- Add/adjust planner tests for assess bypass.
- Add/adjust runner tests for fast-path event handling.
- Run `./scripts/verify_finally.sh`.


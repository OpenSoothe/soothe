# IG-322: Explore subagent — prompt routing and parallel execution

**Status**: Completed  
**Scope**: Improve readonly `explore` delegation via prompts and AgentLoop policy text; optional parallel checkpoint isolation; keep tokens net-neutral or lower.

## Goals

1. Core system prompt documents `explore` (and `research`) for `task` delegation.
2. Simple planner workspace XML (`FORBIDDEN_ACTIONS`, `EFFICIENCY_RULES`) aligns with explore for non-trivial readonly work.
3. `execution_policies.xml` allows independent parallel readonly steps with disjoint scopes.
4. `AgentDecision` / `StepAction` schema field descriptions steer PlanGeneration without verbosity.
5. Explore subgraph prompts stay shorter and subgraph-local only.
6. Optional one-line architecture guide clause for large-repo recon.
7. Parallel Execute: branched `thread_id` in LangGraph config when multiple steps run concurrently (IG-322); logical `thread_id` preserved on `StepResult` and durability extras.

## Files

| Area | Path |
|------|------|
| Prompts | `packages/soothe/src/soothe/config/prompts.py` |
| Planner | `packages/soothe/src/soothe/cognition/agent_loop/core/planner.py` |
| Fragment | `packages/soothe/src/soothe/core/prompts/fragments/system/policies/execution_policies.xml` |
| Schemas | `packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py` |
| Explore | `packages/soothe/src/soothe/subagents/explore/prompts.py` |
| Executor | `packages/soothe/src/soothe/cognition/agent_loop/core/executor.py` |
| Tests | `packages/soothe/tests/unit/cognition/planning/test_planning.py`, `test_executor_hints.py` |

## Config (reference)

- `execution.concurrency.max_parallel_steps` — wave size for parallel AgentLoop steps.
- `agentic.max_subagent_tasks_per_wave` — cap on root `task` completions per Act wave (`0` = unlimited).

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- RFC-613 explore agent
- RFC-605 parallel spawning notes

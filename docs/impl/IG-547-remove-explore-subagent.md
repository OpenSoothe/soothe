# IG-547: Remove explore subagent

**Status:** complete

Execute-step CoreAgent threads already provide readonly recon via file tools (`glob`, `grep`, `read_file`, `ls`). The explore subagent duplicated that work and invited redundant `task(explore)` delegations mid-step.

## Removed

- `packages/soothe/src/soothe/subagents/explore/` package and tests
- Config `subagents.explore`, `/explore` slash route, plugin discovery entry
- Planner collection phase that invoked explore runnable
- Explore-specific tool budgets, card-ingest skips, TUI display name

## Behavior changes

- `execution_hint=subagent` without a valid `subagent` name → direct tools (`wire_subagent=None`)
- Invalid planner subagent names → direct tools (no explore fallback)
- Planner subagent: plan-design loops only (no internal explore passes)

## Readonly recon

Use execute-step threads with scoped `full_description` and file tools.

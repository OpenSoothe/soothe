# IG-703: Remove suggest_goal / ProposalQueue Mechanism

**Status**: Done  
**Created**: 2026-08-06  
**Related**: RFC-204 Group C (proactive path retired), RFC-222 deferred items

## Goal

Remove the unimplemented `suggest_goal` tool mechanism and its supporting
`ProposalQueue` plumbing. Dynamic DAG growth remains via LoopRail builtins,
AutopilotMonitor decompose (non-rail), intake, and reflection `GoalDirective`s.

## Removed

| Piece | Notes |
|-------|--------|
| `soothe.autopilot.proposal_queue` | `Proposal` / `ProposalQueue` |
| `_proposals_to_directives` | Worker convert of `suggest_goal` → create |
| `proposal_queue` injection | StrangeLoop → LoopRuntimeContext → Executor → configurable |
| Unit tests | `test_proposal_queue`, `test_proposals_to_directives`, RFC-204 proposal regression |

## Retained

- `GoalDirective` / `CE.apply_directives` / completion-chunk `goal_directives`
- Reflection directive extraction on the autopilot worker
- LoopRail + monitor spawn paths

## Docs updated

- RFC-204 (retire proactive ProposalQueue path)
- RFC-222 (drop deferred proposal-tools bullet)
- Wiki StrangeLoop + intake analysis

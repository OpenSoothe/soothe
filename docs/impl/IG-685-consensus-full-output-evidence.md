# IG-685: Consensus Evidence from Full Output / Run Ledger

**Created**: 2026-08-04  
**Status**: Implemented  
**Related**: [IG-680](IG-680-autopilot-dag-health-evidence-deps.md),
[RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)

---

## Problem

Autopilot consensus suspends successful no-artifact goals
(`insufficient evidence for consensus (empty summary and workspace probe)`)
even when StrangeLoop already produced a non-empty `PlanResult.full_output`
(e.g. `echo hello` → `ledger_direct chars=28`).

IG-680 correctly banned falling back to `goal.description`. The worker still
only shipped `evidence_summary` (often empty) and ignored `full_output` /
completed plan-step contribution fields.

## Fix

1. Goal completion: when `evidence_summary` is empty, seed it from `full_output`.
2. Autopilot worker: synthesize completion evidence from summary → full_output →
   completed decision steps before emitting `GoalCompletionChunk`.
3. Consensus grounding: include contribution `plan_steps_executed` and
   `tool_call_stats` as structural evidence (still never the goal description).
4. Empty after all sources → keep suspend (IG-680 invariant).

## Acceptance

- [x] `full_output` alone grounds consensus (accept path reachable)
- [x] Empty everything still suspends (no description fallback)
- [x] Contribution plan steps alone can ground when summary/probe empty
- [x] `./scripts/verify_finally.sh` green

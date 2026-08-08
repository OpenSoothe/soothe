# IG-731: Autopilot dispatch intake_scope (default null)

**Created**: 2026-08-08  
**Status**: Implemented  
**Package**: `soothe`  
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[IG-725](IG-725-remove-evidence-turns-trust-sloop.md)

---

## Goal

Make Autopilot-dispatched StrangeLoop intake scope configurable via
`agent.autopilot.intake_scope`. Product default is **`null`** (loop Pass 1+2).
Develop profile sets **`simple`** to skip intake LLM for local evals.

## Config

| Value | Behavior |
|-------|----------|
| `null` (default) | Loop runs Pass 1+2 and determines intake |
| `simple` / `trivial` / `complex` | Pre-classify scope; skip Pass 1+2 |

Plumbed on `LoopRunRequest.intake_scope` from `AutopilotService._dispatch_to_worker`.

# IG-370: AgentLoop evidence vs ledger deduplication

## Status

Completed (`./scripts/verify_finally.sh`).

## Goal

Align with RFC-214 / IG-368: the execute **ledger** (`loop_messages`) is the canonical narrative for Plan and synthesis. Reduce redundant use of `StepResult.to_evidence_string(truncate=False)` where the runtime already has a better source of truth.

## Changes

1. **Plan phase `full_output` (done)** — `LLMPlanner` already sets `full_output` from `state.last_execute_assistant_text` on early completion. `PlanPhase` must **not** overwrite non-empty `full_output` with joined step-evidence strings (those are metadata summaries, not the user-visible answer). Keep step-evidence join only as a **fallback** when `full_output` is empty (e.g. forced completion without assistant text).

2. **Scenario classifier `evidence_volume`** — Use `to_evidence_string(truncate=True)` per successful step for a rough size signal. Avoids allocating long `truncate=False` strings that duplicate ledger-scale content; the classifier only needs order-of-magnitude for routing.

## Files

- `packages/soothe/src/soothe/core/agent_loop/core/plan_phase.py`
- `packages/soothe/src/soothe/core/agent_loop/analysis/scenario_classifier.py`
- `packages/soothe/tests/unit/core/agent_loop/core/test_plan_phase_full_output.py` (new)

## Verification

`./scripts/verify_finally.sh`

# IG-542: Execute-Step Ledger Projection

**IG**: 542  
**Title**: Execute-Step Ledger Projection  
**Status**: Implemented  
**Created**: 2026-07-02  
**RFCs**: RFC-214 §3.1, RFC-225, RFC-226  
**Draft**: `docs/drafts/2026-07-02-execute-step-ledger-projection-design.md`

## Overview

Symmetric execute-step CoreAgent graph input with planner prompts (IG-538): **projected ledger slices + lightweight envelope**. Three slices at read time:

- **Slice A** — cross-goal: K prior-goal completion units (synthesized `goal_completion` or ledger-direct last `execute_step` pair)
- **Slice B** — intra-goal: transitive-predecessor `execute_step` Human/AI replay
- **Slice C** — current execute envelope (`EXECUTION TASK`, `PRIOR STEPS`, optional `PRIOR GOALS`, `EXPECTED OUTPUT`, `INSTRUCTIONS`, `EXECUTION METADATA`)

## Scope

| In | Out |
|----|-----|
| `project_execute_step_graph_input` | `goal_id` on ledger rows (P2) |
| `project_cross_goal_completion_tail` (K units) | Full prior-goal execute replay in Slice A |
| Envelope dedup (`PRIOR GOAL COMPLETION` when Slice A non-empty) | `quiz` terminal handoff |
| `ExecutePromptLedgerConfig` defaults | CE `project_for_core_agent` delegation (P2) |
| Executor + continuation bootstrap wiring | Plan-phase projection changes |

## Files

| File | Change |
|------|--------|
| `prompts/plan_ledger_projection.py` | Mode resolution, Slice A/B orchestrator |
| `engine/executor.py` | Unified projection + envelope dedup |
| `prompts/user_message.py` | `PRIOR GOALS` on execute envelope |
| `config/models.py` | `ExecutePromptLedgerConfig` |
| `orchestrator/nodes/execute_steps.py` | Pass checkpoint into `Executor` |
| `docs/specs/RFC-214-strangeloop-loop-message-surface.md` | §3.1 execute projection |
| tests | projection + executor continuation |

## Acceptance

1. At `goal_boundary`, graph input includes up to K prior-goal completion units (synthesized or ledger-direct per goal).
2. When Slice A is non-empty, envelope omits inline `PRIOR GOAL COMPLETION`.
3. Dependent steps receive Slice B + `PRIOR STEPS` metadata.
4. Mid-goal root steps receive neither Slice A nor Slice B.
5. `./scripts/verify_finally.sh` passes.

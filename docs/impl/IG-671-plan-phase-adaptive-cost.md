# IG-671: Plan-Phase Adaptive Cost

## Goal

Cut StrangeLoop mid-loop plan-phase wall-clock by skipping LLM work when the
in-flight plan is still valid, shrinking generate prompts, and using `think`
for plan-generate only when quality risk is high.

## Motivation

IG-653 moved gap/assess to `fast` and kept generate on `think`. Remaining cost:

1. Mid-loop iterations still run gap+assess even when assess will say `continue`
   and generate short-circuits to `plan_action=keep`.
2. Generate always uses `think`, including `simple` lightweight and near-gap
   replans.
3. Generate ledger projection often has unlimited char budgets (`0`), so think
   prefill stays large.
4. Multi-step DAGs pay plan-phase tax every hop even when only the next ready
   step should run.

## Design

### D1 — Assess `skip_generate` on keep

When assess returns non-terminal `continue` and `has_remaining_steps()`, build a
`plan_action=keep` `PlanResult` in `node_plan_assess` and route
`assess_route=skip_generate` (do not enter `generate_plan`).

### D2 — Structural keep before gap/assess

Config-gated pre-gate in `gather_evidence` (structural rules only):

- enabled via `plan_structural_keep_enabled` (default true)
- requires remaining steps, last wave succeeded, not stuck, no tool/subagent cap
  hits
- streak cap `plan_structural_keep_max_streak` forces a full gap/assess path
  periodically
- on match: emit keep `PlanResult`, route `evidence_gather_route=keep_plan` →
  `commit_plan`

### A — Adaptive generate model role

- `plan_generate_model_role` remains the complex/default (`think`)
- `plan_generate_model_role_simple` (default `fast`) for simple/lightweight and
  approved-plan implement handoff
- `plan_generate_model_role_near_gap` (default `fast`) when gap distance is
  `near`/`at_goal` and the last wave succeeded

### B — Conditional gap skip

Skip gap analysis for mid-loop `simple` intake (assess-only). Fresh-loop and
complex mid-loop gap behavior unchanged.

### C — Generate ledger char caps

Tighten `plan_prompt_ledger` defaults:

- `plan_ledger_max_total_chars: 24000`
- `plan_ledger_max_message_chars: 3000`

Message-count cap (`40`) unchanged. Assess/gap keep their tighter
`plan_evaluate_prompt` knobs.

## Config

```yaml
agent:
  loop:
    plan_structural_keep_enabled: true
    plan_structural_keep_max_streak: 3
    plan_gap_skip_simple_mid_loop: true
    plan_generate_model_role: think
    plan_generate_model_role_simple: fast
    plan_generate_model_role_near_gap: fast
    plan_prompt_ledger:
      plan_ledger_max_messages: 40
      plan_ledger_max_total_chars: 24000
      plan_ledger_max_message_chars: 3000
```

## Files

- `docs/impl/IG-671-plan-phase-adaptive-cost.md`
- `config/soothe.template.yml` + packaged `soothe.yml`
- `soothe/config/models.py`
- `soothe/sloop/cognition/structural_keep.py` (new)
- `soothe/sloop/stages/plan/gather_evidence.py`
- `soothe/sloop/stages/plan/assess.py`
- `soothe/sloop/orchestrator/routing.py`, `state.py`, `builder.py`
- `soothe/sloop/cognition/planner.py`
- `soothe/runner/resolver/__init__.py`
- `soothe/sloop/state/schemas.py` (`structural_keep_streak`)
- Unit tests for keep gate, assess skip, role selection, config defaults

## Acceptance

- Healthy multi-step continue: structural keep skips gap+assess+generate
- Assess `continue`+remaining → `skip_generate` without generate node
- Simple generate uses simple-role model; complex far-gap keeps think
- Default plan ledger char caps are non-zero
- Stuck / failed last wave / streak overflow still run full assess path

## Cleanse

- Unified keep `PlanResult` construction via `build_keep_plan_result` (assess,
  structural keep, generate short-circuit).
- Moved stuck detection into `structural_keep.py` (single owner).
- Dropped unused `AssessRoute` literals `continue_assess` / `fresh_loop_skip_assess`.
- Updated wiki plan-phase description for adaptive keep / model roles.

## Validation

- `./scripts/verify_finally.sh`
- Post-deploy: `rg '\[Plan\] (structural keep|phase=)' ~/.soothe/logs/soothe.log*`

# IG-653: Plan-Phase Wall-Clock Efficiency

## Goal

Reduce StrangeLoop mid-loop plan-phase wall-clock latency while keeping
plan-generate quality on the `think` model role.

## Motivation

Production uses the RFC-220 split path (`plan_gap_analysis` → `plan_assess` →
`plan_generate`). Gap and assess historically shared the assess/`think` model,
so mid-loop iterations paid two expensive structured calls before generate.

Local log baseline (loop `f40f`, think-role gap/assess/generate):

| Iter | Gap (approx) | Assess (approx) | Generate (approx) |
|------|--------------|-----------------|-------------------|
| 1    | ~102s        | ~55s            | ~50s              |
| 2    | ~63s         | ~64s            | ~64s              |
| 3    | ~71s         | ~11s            | (skipped; done)   |

Gap+assess often dominate or match generate. Fresh iter=0 already skips both
(IG-476 / IG-557).

## Design

1. **Instrument** split-path methods with stable INFO lines:
   `[Plan] phase=gap|assess|generate elapsed_ms=N prompt_chars=N iter=N`
2. **Defaults**: `plan_gap_model_role=fast`, `plan_assess_model_role=fast`,
   `plan_generate_model_role=think` (unchanged for plan quality).
3. Wire a dedicated gap model through `resolve_planner` → `LLMPlanner`.

Existing assess/generate guardrails (fresh-loop skip, terminal gates, undersized
replan, stuck detection) still protect continue/done decisions.

## Files

- `sloop/cognition/planner.py` — timings + `_plan_gap_model`
- `config/models.py`, `soothe.template.yml`, packaged `soothe.yml`
- `runner/resolver/__init__.py`
- Unit tests: config defaults, resolver roles, timing log format

## Cleanse (related dead code)

- Removed legacy one-shot `[LLMPlanner] timings assess_ms=… plan_gen_ms=…`
  log; `plan()` now emits the same `[Plan] phase=assess|generate` lines as the
  split graph path.
- Dropped unused `llm_calls` counter that only fed the old combined timing line.
- Diagnose skill: grep `[Plan] phase=` instead of stale `[LLMPlanner]`.

## Validation

- `./scripts/verify_finally.sh`
- Post-deploy: `rg '\[Plan\] phase=' ~/.soothe/logs/soothe.log*` — gap/assess
  `elapsed_ms` should drop vs prior think-role runs; generate stays think.

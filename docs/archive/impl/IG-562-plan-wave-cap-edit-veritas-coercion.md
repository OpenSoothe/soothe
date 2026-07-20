# IG-562: Plan Wave Cap, edit_file Fail Signals, Veritas Coercion

**IG**: 562
**Title**: Plan Wave Cap, edit_file Fail Signals, Veritas Coercion
**Status**: Implemented
**Created**: 2026-07-07

---

## Summary

Three robustness fixes from loop analysis (7ded / 65d8):

1. **Plan step cap** — `agent.loop.max_plan_steps_per_wave` (default 10) applies to all plan-generate calls, preventing 89-step plan explosions on complex iter>0 goals.
2. **Hybrid edit_file routing** — single `edit_file` pass-through to direct handler; batch only when 2+ parallel edits target the same file; batch path emits `EDIT_OLD_STRING_NOT_FOUND` / `EDIT_MULTIPLE_MATCHES` per tool call.
3. **Structured-output coercion** — `coerce_veritas_response` and `coerce_plan_generation_dict` salvage common glm-5 JSON malformations before jsonschema validation.

---

## Files

| File | Change |
|------|--------|
| `config/models.py`, `config.template.yml`, `develop/config.yml` | `max_plan_steps_per_wave` |
| `foundation/sloop/state/schemas.py` | Cap model (`capped_plan_generation_model`), `coerce_plan_generation_dict` |
| `foundation/sloop/cognition/plan_step_safety.py` | Removed iteration-gated cap helper |
| `foundation/sloop/cognition/planner.py` | Config-driven cap + retry hint |
| `middleware/edit_coalescing.py` | Hybrid routing + batch error signals |
| `foundation/sloop/engine/metadata_generator.py` | False-success detection |
| `subagents/veritas/schemas.py` | `coerce_veritas_response` |
| `subagents/veritas/implementation.py` | `normalize` hook |
| `utils/llm/structured.py` | Optional `normalize` callback |

---

## Verification

- [x] `./scripts/verify_finally.sh`
- [ ] Manual: complex goal replan iter>0 capped at 10 steps in logs
- [ ] Manual: post-goal veritas auto-answers without TUI fallback
- [ ] Manual: wrong `old_string` → `EDIT_OLD_STRING_NOT_FOUND`

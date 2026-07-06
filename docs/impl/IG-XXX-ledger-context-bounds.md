# IG-XXX: Ledger context bounds for multi-goal loops

## Scope

- Enable `plan_ledger_max_messages` cap (default 40)
- Compact `execute_step` AI at CE write time via langchain `trim_messages`
- Planner `mid_goal` projection: Slice A (cross-goal completion tail) + current-goal segment only
- Skip stale-goal summarization (explicitly out of scope)

## Files

- `config/config.template.yml`, `config/develop/config.yml`
- `packages/soothe/src/soothe/config/models.py`
- `packages/soothe/src/soothe/foundation/sloop/utils/messages.py`
- `packages/soothe/src/soothe/foundation/sloop/prompts/plan_ledger_projection.py`
- `packages/soothe/src/soothe/foundation/sloop/prompts/builder.py`
- `packages/soothe/src/soothe/foundation/context/engine.py`
- `packages/soothe/src/soothe/foundation/sloop/engine/strange_loop.py`

## Verification

`./scripts/verify_finally.sh`

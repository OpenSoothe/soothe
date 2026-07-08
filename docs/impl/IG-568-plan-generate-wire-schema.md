# IG-568: Plan-Generate Wire Schema Simplification

**IG**: 568  
**Title**: Plan-Generate Wire Schema Simplification  
**Status**: Implemented  
**Created**: 2026-07-08  
**Related**: [RFC-604](../specs/RFC-604-plan-assess-generate-split.md), [IG-562](IG-562-plan-wave-cap-edit-veritas-coercion.md)

---

## Summary

Replace the fat `PlanGeneration` JSON schema sent to plan-generate LLMs with a minimal **wire** schema. Runtime `PlanGeneration` / `AgentDecision` shapes are unchanged — an adapter derives missing fields server-side.

Motivation: thinking models (e.g. glm-5) emit malformed JSON such as `"execution_mode"` and `"reasoning"` as bare strings inside `steps[]`, failing jsonschema before Pydantic coercion runs.

---

## Wire schema (LLM output)

Top-level:

| Field | Required | Notes |
|-------|----------|-------|
| `reasoning` | yes | TUI cognition (≤500 chars) |
| `steps` | yes* | Action steps; `[]` when using `clarify` |
| `clarify` | optional | `{ "questions": ["...?"] }` — mutually exclusive with non-empty `steps` |

Per-step (`steps[]`):

| Field | Required | Notes |
|-------|----------|-------|
| `description` | yes | Milestone (&lt;20 words) |
| `dependencies` | yes | Use `[]` when none — **simple and complex** |
| `expected_output` | optional | Default server-side |
| `id` | optional | Default `01`, `02`, … |
| `delegate` | optional | Maps to subagent routing when valid |

**Not in wire** (derived):

- `type` → always `execute_steps` at plan-generate
- `execution_mode` → `dependency` if any step has deps, else `parallel`
- `full_description` → `populate_plan_generate_full_descriptions`
- `kind` / `questions` → `clarify` object or legacy ask_user step coercion
- `continues_from`, `adaptive_granularity`, `execution_hint` / `subagent` (unless `delegate` set)

---

## Files

| File | Change |
|------|--------|
| `foundation/sloop/cognition/plan_generation_wire.py` | Wire models, coerce, adapter |
| `foundation/sloop/cognition/planner.py` | Wire invoke + `normalize` + adapter |
| `utils/llm/structured.py` | `normalize` on `invoke_structured_chat_typed` |
| `prompts/fragments/instructions/plan_generate_instructions.xml` | Wire contract |
| `foundation/sloop/state/schemas.py` | Runtime `PlanGeneration` only; removed LLM cap/coerce helpers |
| `tests/unit/core/loop/cognition/test_plan_generation_wire.py` | Wire coerce, adapter, cap tests |

Removed legacy from `schemas.py`: `capped_plan_generation_model`, `coerce_plan_generation_dict` (superseded by wire module).

---

## Verification

- `./scripts/verify_finally.sh`
- Manual: simple intake goal (e.g. Shanghai weather) with glm-5 plan-generate model

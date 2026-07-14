# IG-329: Plan-generate prompt and JSON schema trim

**Status**: Completed  
**Scope**: Align the plan-generate (`plan_phase="generate"`) system prompt with the actual `PlanGeneration` structured output; remove `brief_reasoning` from that schema.

## Motivation

- The former combined-loop instruction fragment (`plan_execute_instructions.xml`, removed) described a full assess+plan JSON shape while the second LLM call only outputs `PlanGeneration` fields.
- `brief_reasoning` added tokens and was only copied into `PlanResult.plan_reasoning`; `next_action` remains the primary user-facing summary.

## Changes

| Area | Change |
|------|--------|
| Prompts | New `plan_generate_instructions.xml`; builder uses it + `EXECUTION_POLICIES` for generate phase; removed obsolete `plan_execute_instructions.xml` and `PLAN_EXECUTE_INSTRUCTIONS_FRAGMENT` |
| Schema | `PlanGeneration`: drop `brief_reasoning`; doc `PlanResult.plan_reasoning` as unused from phase-2 LLM |
| Planner | Fallback `_combine_results`: `plan_reasoning=""` |
| Tests | IG-372 prompt split, plan phase truncation tests |

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- RFC-000, RFC-001, RFC-206, RFC-213, RFC-404, RFC-603, RFC-604, `docs/specs/rfc-namings.md` (updated for IG-329 prompt/schema alignment)
- IG-372 (plan-assess vs plan-generate split)
- IG-264 (planner schema simplification notes)

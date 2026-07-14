# IG-378: Plan-generate GOAL_PROGRESS in system message

**Status:** Completed  
**Scope:** `PromptBuilder` plan phase messages (RFC-214, align with IG-376 / plan-assess)

## Motivation

Plan-assess already places `Goal:` and `Execute iteration:` inside `<GOAL_PROGRESS>` at the end of the system prompt. Plan-generate duplicated those lines on the optional plan-context human instead, which splits static context across message roles and is worse for prompt caching consistency.

## Changes

| Area | Change |
|------|--------|
| `builder.py` | Append the same `<GOAL_PROGRESS>` footer to the system prompt for `plan_phase="generate"` as for assess; stop emitting goal/iteration lines on the plan-context human (use `include_goal_lines=False` for both phases). |
| `plan_generate_instructions.xml` | Reference `<GOAL_PROGRESS>` for goal scope (mirror plan-assess wording). |
| Tests | Update IG-372 generate test to assert system footer, not human prefix. |

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- IG-376, IG-372, IG-329, RFC-214

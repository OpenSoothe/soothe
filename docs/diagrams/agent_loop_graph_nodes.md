# AgentLoop LangGraph Node Summary

## Nodes

- `__start__`
- `init_or_resume`
- `iteration_gate`
- `iteration_start`
- `bounded_evidence_gather`
- `plan_assess`
- `plan_generate`
- `goal_completion`
- `resolve_decision`
- `validate_evidence_bindings`
- `execute`
- `record_iteration`
- `__end__`

## Edges

- `__start__` → `init_or_resume`
- `bounded_evidence_gather` → `plan_assess`
- `execute` → `__end__`
- `execute` → `record_iteration`
- `init_or_resume` → `__end__`
- `init_or_resume` → `iteration_gate`
- `iteration_gate` → `__end__`
- `iteration_gate` → `iteration_start`
- `iteration_start` → `bounded_evidence_gather`
- `plan_assess` → `goal_completion`
- `plan_assess` → `plan_generate`
- `plan_assess` → `resolve_decision`
- `plan_generate` → `goal_completion`
- `plan_generate` → `resolve_decision`
- `record_iteration` → `__end__`
- `record_iteration` → `iteration_gate`
- `resolve_decision` → `__end__`
- `resolve_decision` → `validate_evidence_bindings`
- `validate_evidence_bindings` → `__end__`
- `validate_evidence_bindings` → `execute`
- `goal_completion` → `__end__`

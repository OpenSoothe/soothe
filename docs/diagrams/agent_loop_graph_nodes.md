# AgentLoop LangGraph Node Summary

> Reflects RFC-220 base topology, RFC-225 (status `idle`, structural `continue_loop_mode`),
> and RFC-226 (continuation-aware `plan_assess` + terminal fast-exit edge).

## Nodes

- `__start__`
- `init_or_resume`
- `iteration_gate`
- `iteration_start`
- `bounded_evidence_gather`
- `plan_assess` — on iter=0 of a continuation, calls
  `LLMPlanner.assess_continuation` (RFC-226) and routes to bootstrap or
  `plan_generate`; otherwise runs the existing status-check assess.
- `plan_generate`
- `goal_completion` — marks the returned `PlanResult.status = "done"` so
  the runner emits the final answer to the wire (loop_assistant_messages_chunk).
- `resolve_decision`
- `validate_evidence_bindings`
- `execute`
- `record_iteration` — emits `after_record_route="goal_completion"` when
  `PlanResult.terminal_after_execute` is True (RFC-226 bootstrap path).
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
- `record_iteration` → `goal_completion`  *(RFC-226: terminal fast-exit when `PlanResult.terminal_after_execute` is True)*
- `resolve_decision` → `__end__`
- `resolve_decision` → `validate_evidence_bindings`
- `validate_evidence_bindings` → `__end__`
- `validate_evidence_bindings` → `execute`
- `goal_completion` → `__end__`

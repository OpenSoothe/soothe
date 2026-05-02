# IG-352: Subagent delegation as goal-loop evidence

## Status: In progress

## Intent

Wire-level ``preferred_subagent`` (slash routes such as ``/claude``) is a **hint** merged into ``LoopState.unified_classification`` (IG-349). Execution should treat delegated work like any other **bounded tool interaction**: the deepagents ``task`` tool runs the chosen subgraph; its **ToolMessage** result is classified as ``outcome_type=subagent`` (``soothe_sdk.tools.metadata`` → ``generate_outcome_metadata``) and becomes **step evidence** via ``StepResult`` / ``to_evidence_string()``. The **Plan phase** (``PlanPhase.plan``) already consumes ``state.step_results`` when calling the loop planner—same path as non-subagent steps—so the model can mark the goal done, continue, or replan.

## Current architecture (as implemented)

1. **Routing merge** (`soothe.core.runner.routing_merge`): CLI ``preferred_subagent`` is merged into classification for AgentLoop.
2. **Planner**: ``LLMPlanner._apply_preferred_subagent_to_decision`` sets ``StepAction.subagent`` on action steps; ``_apply_preferred_subagent`` (legacy ``Plan`` / ``PlanStep``) now sets ``PlanStep.subagent`` in parity (this IG).
3. **Executor** (`soothe.cognition.agent_loop.core.executor`): Each step injects ``soothe_step_subagent`` into LangGraph ``configurable``; streams ``core_agent.astream`` with ``subgraphs=True``. Subagent **task** completions increment ``subagent_task_completions`` and participate in RFC-211 outcome aggregation.
4. **Evidence**: ``PlanPhase`` builds ``state.evidence_summary`` from ``StepResult.to_evidence_string()`` (includes ``outcome_type=subagent`` branch in ``protocols.planner.StepResult``).

## Gap addressed here

**Plan** objects from ``LLMPlanner.create_plan`` had ``execution_hint=subagent`` after a preferred wire but did **not** record **which** subagent on ``PlanStep``. ``AgentDecision`` already carried ``StepAction.subagent``. Adding optional ``PlanStep.subagent`` and setting it in ``_apply_preferred_subagent`` aligns the two surfaces so UI/reflection and future Plan→execution bridges see the same delegate name.

## Verification

- `./scripts/verify_finally.sh`

## References

- IG-349 (unified subagent routing), RFC-211 (outcome metadata), RFC-201 (AgentLoop), deepagents ``task`` tool meta (`outcome_type=subagent`).
- **IG-355**: User-visible completion for delegate-heavy runs—promote ordered **`task`** return text into goal completion / RFC-614 replay so headless CLI receives loop-tagged output without piping subgraph AIMessage streams into main context.

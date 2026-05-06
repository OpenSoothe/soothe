# Implementation Guide: Plan Generation Optimization

**Guide**: IG-401
**Title**: Plan Generation Optimization — First-Wave Constraint, DAG-Aware Planning, Step Consolidation
**Created**: 2026-05-06
**Related RFCs**: RFC-604, RFC-220

## Overview

This implementation guide documents optimizations to the plan-generate system (RFC-604 two-call architecture) that improve iteration efficiency by:

1. **First-wave constraint**: Limit initial plan to max 2 steps, validated by prompt + programmatic enforcement
2. **Progressive DAG-aware planning**: Inject PlanManager/PlanDAG state into the generate-phase prompt so the LLM knows what's been tried, what failed, and what remains
3. **Step consolidation**: Prompt the LLM to merge related steps, minimizing total steps per goal
4. **Failure-aware replanning**: When prior steps failed, instruct the LLM to propose a *different approach* rather than retrying the same failed step
5. **PlanManager interleaving**: Expose DAG state for read during planning (previously write-only)

## Prerequisites

- [x] IG-400 (PlanManager/PlanDAG Architecture) accepted and merged
- [x] RFC-604 (Plan-phase two-call architecture)
- [x] RFC-220 (LangGraph Agent Loop Orchestrator)

## Implementation Plan

### Phase 1: Prompt Constraints (LLM-side)

**Goal**: Add first-wave and consolidation rules to execution policies.

**Tasks**:
- [x] Add `<FIRST_WAVE_CONSTRAINT>` to `execution_policies.xml` (max 2 steps at iteration 0)
- [x] Add `<STEP_CONSOLIDATION>` to `execution_policies.xml` (merge related steps)
- [x] Add iteration-aware hint to `plan_generate_instructions.xml` (1-2 steps at iter 0)
- [x] Add failure-aware replanning hint to `plan_generate_instructions.xml`

### Phase 2: DAG Properties (data layer)

**Goal**: Expose pending, failed, and ready step IDs from PlanDAG.

**Tasks**:
- [x] Add `pending_step_ids` property to `PlanDAG`
- [x] Add `failed_step_ids` property to `PlanDAG`
- [x] Add `ready_step_ids` property to `PlanDAG` (pending steps with all deps satisfied)

### Phase 3: PlanManager Interleaving

**Goal**: Make PlanManager readable during planning, not just writable.

**Tasks**:
- [x] Create `DagPlanningContext` dataclass (structured DAG summary for LLM)
- [x] Add `get_planning_context()` method to `PlanManager`
- [x] Export `DagPlanningContext` from `planning/__init__.py`

### Phase 4: DAG Context Injection (prompt layer)

**Goal**: Inject structured DAG context into the generate-phase prompt.

**Tasks**:
- [x] Add `_format_dag_context()` helper to `builder.py` (formats as XML block)
- [x] Add `dag_context` parameter to `build_plan_messages()`
- [x] Add `dag_context` parameter to `_build_plan_context_human_text()`
- [x] Inject `<PLAN_DAG_CONTEXT>` XML block into generate-phase human message

### Phase 5: Wiring + Enforcement (planner layer)

**Goal**: Thread PlanManager through the planning call chain and enforce first-wave constraint.

**Tasks**:
- [x] Add `plan_manager` parameter to `LLMPlanner.plan()`
- [x] Add `plan_manager` parameter to `LLMPrunner.generate_from_assessment()`
- [x] Fetch DAG context and inject into `build_plan_messages()` calls
- [x] Add first-wave truncation safety net in `_finalize_generated_plan_result()`
- [x] Forward `plan_manager` through `PlanPhase.plan()` and `PlanPhase.generate_from_assessment()`
- [x] Update `LoopPlannerProtocol` signatures
- [x] Pass `plan_manager` from `node_plan_generate`

## File Structure

```
packages/soothe/src/soothe/
├── core/agent_loop/
│   ├── planning/
│   │   ├── dag.py              # MODIFIED: Add pending/failed/ready_step_ids properties
│   │   ├── manager.py          # MODIFIED: Add DagPlanningContext, get_planning_context()
│   │   ├── planner.py          # MODIFIED: Add plan_manager param, DAG injection, first-wave truncation
│   │   ├── phase.py            # MODIFIED: Forward plan_manager parameter
│   │   └── __init__.py         # MODIFIED: Export DagPlanningContext
│   └── orchestrator/nodes/
│       └── plan_generate.py    # MODIFIED: Pass plan_manager to generate_from_assessment()
├── prompts/
│   ├── builder.py              # MODIFIED: Add _format_dag_context(), dag_context param
│   └── fragments/
│       ├── system/policies/
│       │   └── execution_policies.xml  # MODIFIED: Add first-wave + consolidation rules
│       └── instructions/
│           └── plan_generate_instructions.xml  # MODIFIED: Add iteration/failure hints
└── protocols/
    └── loop_planner.py         # MODIFIED: Add plan_manager to protocol signatures
```

## Implementation Details

### Module 1: PlanDAG Properties

**File**: `packages/soothe/src/soothe/core/agent_loop/planning/dag.py`

```python
@property
def pending_step_ids(self) -> set[str]:
    """Step IDs that are still pending (not yet executed)."""
    return {cid for cid, n in self.nodes.items() if n.status == "pending"}

@property
def failed_step_ids(self) -> set[str]:
    """Step IDs that have failed execution."""
    return {cid for cid, n in self.nodes.items() if n.status == "failed"}

@property
def ready_step_ids(self) -> set[str]:
    """Pending steps whose dependencies are all satisfied (ready to execute)."""
    completed = self.get_completed_step_ids()
    return {
        cid for cid, node in self.nodes.items()
        if node.status == "pending" and all(dep in completed for dep in node.dependencies)
    }
```

### Module 2: DagPlanningContext + PlanManager

**File**: `packages/soothe/src/soothe/core/agent_loop/planning/manager.py`

```python
@dataclass
class DagPlanningContext:
    """Structured DAG summary for LLM planning."""
    pending_step_ids: set[str] = field(default_factory=set)
    failed_step_ids: set[str] = field(default_factory=set)
    ready_step_ids: set[str] = field(default_factory=set)
    chain_depth: int = 0
    success_rate: float = 1.0
    replan_count: int = 0
    total_steps: int = 0
    completed_steps: int = 0

    @property
    def has_prior_state(self) -> bool:
        return self.total_steps > 0
```

`PlanManager.get_planning_context()` returns this dataclass populated from the DAG.

### Module 3: DAG Context Formatting

**File**: `packages/soothe/src/soothe/core/prompts/builder.py`

```python
def _format_dag_context(dag_ctx: DagPlanningContext) -> str:
    """Format as XML block for prompt injection."""
    if not dag_ctx or not dag_ctx.has_prior_state:
        return ""
    lines = ["<PLAN_DAG_CONTEXT>"]
    lines.append(f"- Total steps planned: {dag_ctx.total_steps}")
    lines.append(f"- Completed: {dag_ctx.completed_steps}")
    if dag_ctx.failed_step_ids:
        lines.append(f"- Failed: {len(dag_ctx.failed_step_ids)} (IDs: ...)")
    if dag_ctx.ready_step_ids:
        lines.append(f"- Ready to execute: {', '.join(sorted(dag_ctx.ready_step_ids))}")
    lines.append(f"- Dependency chain depth: {dag_ctx.chain_depth}")
    lines.append(f"- Success rate: {dag_ctx.success_rate:.0%}")
    if dag_ctx.replan_count > 0:
        lines.append(f"- Replans: {dag_ctx.replan_count}")
    if dag_ctx.failed_step_ids:
        lines.append("- NOTE: Prior steps failed — propose a DIFFERENT approach.")
    lines.append("</PLAN_DAG_CONTEXT>")
    return "\n".join(lines)
```

### Module 4: First-Wave Truncation

**File**: `packages/soothe/src/soothe/core/agent_loop/planning/planner.py`

```python
def _finalize_generated_plan_result(self, *, result, state, context, goal):
    if result and result.plan_action == "new" and result.decision and result.decision.steps:
        # Enforce max 2 steps on first wave (safety net if LLM ignores prompt)
        if state.iteration == 0 and len(result.decision.steps) > 2:
            logger.warning(
                "[PlanGen] Truncated first-wave steps from %d to 2",
                len(result.decision.steps),
            )
            truncated = result.decision.steps[:2]
            result = result.model_copy(
                update={"decision": result.decision.model_copy(update={"steps": truncated})}
            )
        # ... rest of postprocessing
```

### Module 5: Prompt Fragments

**File**: `execution_policies.xml`

```xml
<FIRST_WAVE_CONSTRAINT>
- Iteration 0 (first plan-generate call): produce AT MOST 2 steps.
- Subsequent iterations: 1-3 steps per decision as normal.
- Rationale: reduces wasted work from incorrect assumptions.
</FIRST_WAVE_CONSTRAINT>

<STEP_CONSOLIDATION>
- Before emitting steps, ask: "Can any two steps be merged into one?"
- Merge sequential reads of related files into one step.
- Only split when steps are truly independent parallel work.
</STEP_CONSOLIDATION>
```

**File**: `plan_generate_instructions.xml`

```
- When iteration is 0: produce 1-2 steps maximum. Validate approach before expanding.
- When prior steps have failed: propose a *different approach*, do not re-describe the same failed step.
```

## Testing Strategy

### Unit Tests (manual verification)

All verified via inline test scripts:

1. **DagPlanningContext**: Creation, `has_prior_state` property, empty context returns falsy
2. **PlanDAG properties**: `pending_step_ids`, `failed_step_ids`, `ready_step_ids` correct for mixed-status nodes
3. **PlanManager.get_planning_context**: Returns populated DagPlanningContext
4. **First-wave truncation**: 4 steps at iteration 0 truncated to 2; 3 steps at iteration 1 kept as-is
5. **DAG context formatting**: XML output includes all fields, failure warning, empty context returns ""
6. **Module imports**: All modified modules import cleanly without circular dependencies

### Integration Points

- `node_plan_generate` passes `plan_manager` to `generate_from_assessment()`
- `LLMPlanner` fetches DAG context only when `has_prior_state` is true (no prompt bloat on first iteration)
- `_format_dag_context` imported lazily inside planner methods to avoid circular imports

## Key Design Decisions

1. **Prompt-first + enforcement-backup**: The LLM is constrained via prompt instructions, with programmatic truncation as a safety net. This avoids silent behavior changes while catching LLM non-compliance.
2. **Lazy import of `_format_dag_context`**: Imported inside function bodies in `planner.py` to avoid circular import between `soothe.core.prompts` and `soothe.core.agent_loop`.
3. **DAG context only when `has_prior_state`**: On the first planning cycle (no prior steps), no DAG context is injected, keeping the prompt lean.
4. **`plan_manager` as optional kwarg**: Backwards-compatible; existing callers that don't pass it still work (just without DAG-aware planning).

## Verification

- [x] All modified modules import cleanly
- [x] DagPlanningContext creation and serialization
- [x] PlanDAG pending/failed/ready properties
- [x] First-wave truncation at iteration 0
- [x] No truncation at iteration > 0
- [x] DAG context XML formatting
- [x] No circular import issues at runtime

## Related Documents

- [IG-400](./IG-400-planmanager-plandag-architecture.md) - PlanManager/PlanDAG Architecture
- [RFC-604](../specs/RFC-604-plan-phase-two-call.md) - Plan-Phase Two-Call Architecture
- [RFC-220](../specs/RFC-220-langgraph-agent-loop-orchestrator.md) - LangGraph Agent Loop Orchestrator
- [IG-381](./IG-381-plan-generate-progressive-evidence-explore-bundle.md) - Plan Generate Progressive Evidence

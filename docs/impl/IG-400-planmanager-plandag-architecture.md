# Implementation Guide: PlanManager/PlanDAG Architecture

**Guide**: IG-400
**Title**: PlanManager/PlanDAG Goal Completion Architecture
**Created**: 2026-04-28
**Related RFCs**: RFC-219

## Overview

This implementation guide documents the PlanManager/PlanDAG architecture that replaces the monolithic `goal_completion_policy.py` with a DAG-based plan tracking system and enum-driven completion strategy. The change provides:

- **Unified plan tracking**: All steps from every plan (including replans) merged into a single DAG
- **Replan detection**: `plan_count` property detects when multiple plans were issued
- **DAG complexity analysis**: `max_chain_depth`, `has_dag_dependencies`, `success_rate`
- **Enum-based completion strategy**: `LEDGER_DIRECT`, `SYNTHESIZE`, `SUMMARY` instead of protocol classes
- **Heuristic fallback**: Execution-heuristic checks when LLM says no synthesis needed

## Prerequisites

- [x] RFC-219 accepted
- [x] Development environment setup
- [x] Dependencies installed (Python 3.12+, dataclasses)

## Implementation Plan

### Phase 1: PlanDAG Data Structure

**Goal**: Create the unified DAG data structure for tracking all planned steps.

**Tasks**:
- [x] Create `plan_dag.py` with `PlanNode` and `PlanDAG` dataclasses
- [x] Implement `ingest_plan()` to merge steps from PlanResult
- [x] Implement `mark_completed()` and `mark_failed()` for outcome tracking
- [x] Implement read-only properties: `total_steps`, `completed_steps`, `failed_steps`, `remaining_steps`
- [x] Implement `has_dag_dependencies` property
- [x] Implement `max_chain_depth` (BFS-based longest dependency chain)
- [x] Implement `plan_count`, `success_rate`, `used_subagents` properties

### Phase 2: PlanManager + Completion Strategy

**Goal**: Create PlanManager wrapping PlanDAG with completion strategy logic.

**Tasks**:
- [x] Create `plan_manager.py` with `CompletionStrategy` enum
- [x] Create `PlanManager` dataclass wrapping PlanDAG
- [x] Implement `ingest_plan()` and `record_step_outcomes()` delegation
- [x] Move `determine_goal_completion_needs()` from `goal_completion_policy.py`
- [x] Migrate `_heuristic_requires_goal_completion()` into PlanManager
- [x] Implement `determine_completion_strategy()` with adaptive logic
- [x] Implement `_is_simple_execution()` and `_dag_requires_synthesis()`
- [x] Migrate ledger overlap helpers (`_can_return_directly_from_ledger`, `_is_rich_enough`, `_overlaps_with_plan_output`)

### Phase 3: Integration + Cleanup

**Goal**: Wire PlanManager into AgentLoop graph nodes and delete old code.

**Tasks**:
- [x] Add PlanManager to `LoopRuntimeContext`
- [x] Create PlanManager in `agent_loop.py`
- [x] Call `ingest_plan()` in `node_plan_assess.py` and `node_plan_generate.py`
- [x] Call `record_step_outcomes()` in `node_record_iteration.py`
- [x] Use PlanManager strategy in `node_goal_completion.py`
- [x] Update `policies/__init__.py` exports
- [x] Delete `goal_completion_policy.py`
- [x] Update tests for step.id-based keys

## File Structure

```
packages/soothe/src/soothe/core/agent_loop/
├── core/
│   ├── plan_dag.py              # NEW: PlanNode + PlanDAG dataclasses
│   ├── plan_manager.py          # NEW: PlanManager + CompletionStrategy
│   ├── agent_loop.py            # MODIFIED: Creates PlanManager
│   └── planner.py               # MODIFIED: Uses determine_goal_completion_needs
├── graph/nodes/
│   ├── plan_assess.py           # MODIFIED: ingest_plan()
│   ├── plan_generate.py         # MODIFIED: ingest_plan()
│   ├── record_iteration.py      # MODIFIED: record_step_outcomes()
│   └── goal_completion.py       # MODIFIED: Use PlanManager strategy
├── policies/
│   ├── __init__.py              # MODIFIED: Updated exports
│   └── goal_completion_policy.py  # DELETED
└── state/
    └── graph/runtime_context.py   # MODIFIED: Add plan_manager field

packages/soothe/tests/unit/core/agent_loop/
├── policies/
│   └── test_goal_completion_policy.py  # MODIFIED: Aligned with PlanDAG
└── core/agent_loop/core/
    └── test_agent_loop_adaptive_final.py  # MODIFIED: CompletionStrategy refs
```

## Implementation Details

### Module 1: PlanDAG

**File**: `packages/soothe/src/soothe/core/agent_loop/core/plan_dag.py`

```python
@dataclass
class PlanNode:
    """A single step node in the goal-level DAG."""
    composite_id: str
    description: str
    plan_id: str
    plan_iteration: int
    status: Literal["pending", "completed", "failed"] = "pending"
    dependencies: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    subagent: str | None = None
    outcome: StepResult | None = None


@dataclass
class PlanDAG:
    """Unified DAG representation for all planned steps across iterations."""

    nodes: dict[str, PlanNode] = field(default_factory=dict)
    _plan_ids: set[str] = field(default_factory=set)

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None:
        """Add all steps from a PlanResult into the DAG.
        Nodes keyed by step.id directly (not composite IDs)."""
        decision = plan_result.decision
        if decision is None:
            return
        if plan_id is not None:
            self._plan_ids.add(plan_id)
        for step in decision.steps:
            cid = step.id
            if cid in self.nodes:
                continue  # Node already exists
            self.nodes[cid] = PlanNode(
                composite_id=cid,
                description=step.description,
                plan_id=plan_id or "unknown",
                plan_iteration=iteration,
                dependencies=list(step.dependencies) if step.dependencies else [],
                evidence_refs=list(step.evidence_refs) if step.evidence_refs else [],
                subagent=step.subagent,
            )
```

**Key design decisions**:
- Nodes keyed by `step.id` directly (e.g., "01", "02"), NOT composite IDs like "KFA-01"
- Composite IDs in replans (e.g., "KFA-02" in a second plan) are preserved as-is
- `_plan_ids` tracks distinct plan IDs for replan detection

### Module 2: PlanManager

**File**: `packages/soothe/src/soothe/core/agent_loop/core/plan_manager.py`

```python
class CompletionStrategy(str, Enum):
    LEDGER_DIRECT = "ledger_direct"
    SYNTHESIZE = "synthesize"
    SUMMARY = "summary"


@dataclass
class PlanManager:
    goal: str
    dag: PlanDAG = field(default_factory=PlanDAG)
    plan_history: list[PlanResult] = field(default_factory=list)

    def determine_completion_strategy(
        self, state: LoopState, plan_result: PlanResult,
        mode: FinalResponseMode = "adaptive",
    ) -> CompletionStrategy:
        # 1. Mode override
        if mode == "always_synthesize":
            return CompletionStrategy.SYNTHESIZE

        # 2. Planner says no synthesis needed
        if not plan_result.require_goal_completion:
            if self._is_simple_execution():
                return CompletionStrategy.LEDGER_DIRECT
            return CompletionStrategy.SYNTHESIZE

        # 3. DAG complexity vetoes
        if self._dag_requires_synthesis(state):
            return CompletionStrategy.SYNTHESIZE

        # 4. Ledger richness check
        ledger_text = last_ledger_ai_content(state)
        if not ledger_text:
            return CompletionStrategy.SYNTHESIZE
        if _can_return_directly_from_ledger(ledger_text, plan_result):
            return CompletionStrategy.LEDGER_DIRECT

        # 5. Default
        return CompletionStrategy.SYNTHESIZE
```

**Thresholds**:
- `_DAG_DEPENDENCY_THRESHOLD = 3` (dependencies trigger synthesis)
- `_LOW_SUCCESS_RATE_THRESHOLD = 0.6` (60% success rate minimum)
- `_SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS = 2` (simple DAG limit)
- `_STRUCTURED_PAYLOAD_MIN_LINES = 6` (ledger richness check)

### Module 3: Heuristic Checks

**File**: `packages/soothe/src/soothe/core/agent_loop/core/plan_manager.py`

```python
def _heuristic_requires_goal_completion(self, state: Any) -> bool:
    # Wave execution complexity
    if getattr(state, "last_execute_wave_parallel_multi_step", False):
        return True
    if getattr(state, "last_wave_hit_subagent_cap", False):
        return True

    # Completion quality: failed steps need explanation
    failed_count = self.dag.failed_steps
    if failed_count > 0:
        total = self.dag.completed_steps + failed_count
        success_rate = self.dag.completed_steps / total if total > 0 else 0.0
        if success_rate < _LOW_SUCCESS_RATE_THRESHOLD:
            return True

    # DAG dependencies on the current plan
    if state.current_decision:
        has_deps = any(
            step.dependencies and len(step.dependencies) >= _DAG_DEPENDENCY_THRESHOLD
            for step in state.current_decision.steps
        )
        if has_deps:
            return True

    return False
```

**Standalone version** (used by `planner.py` without PlanManager):
```python
def _heuristic_requires_goal_completion_standalone(state: Any) -> bool:
    # Same logic but reads failed_steps from state.step_results directly
```

## Testing Strategy

### Unit Tests

**File**: `packages/soothe/tests/unit/core/agent_loop/policies/test_goal_completion_policy.py`

Tests cover:
- `determine_goal_completion_needs` modes (llm_only, heuristic_only, hybrid)
- Heuristic checks (parallel_multi_step, subagent_cap, failed steps, DAG dependencies)
- PlanDAG operations (ingest, mark completed/failed, dependencies, multiple plans)
- PlanManager completion strategy (always_synthesize, ledger_direct, synthesize paths)

**Key test patterns**:
```python
def test_plandag_ingest_plan_new():
    dag = PlanDAG()
    decision = AgentDecision(type="execute_steps", steps=[
        StepAction(id="01", description="Step 1"),
        StepAction(id="02", description="Step 2"),
    ], execution_mode="sequential")
    plan_result = PlanResult(status="continue", goal_progress="low",
                             plan_action="new", decision=decision)
    dag.ingest_plan(plan_result, "KFA", 0)
    assert dag.total_steps == 2
    assert "01" in dag.nodes  # Keys are step.id, not "KFA-01"

def test_strategy_ledger_direct_simple():
    pm = PlanManager(goal="test")
    d = AgentDecision(type="execute_steps", steps=[
        StepAction(id="01", description="Step 1"),
    ], execution_mode="sequential")
    pr = PlanResult(status="done", goal_progress="complete",
                    plan_action="new", decision=d, require_goal_completion=False)
    pm.ingest_plan(pr, "KFA", 0)
    pm.record_step_outcomes([
        StepResult(step_id="01", success=True, outcome={}, duration_ms=10, thread_id="t"),
    ])
    state = mock_loop_state()
    assert pm.determine_completion_strategy(state, pr, "adaptive") == CompletionStrategy.LEDGER_DIRECT
```

### Integration Tests

**File**: `packages/soothe/tests/unit/core/agent_loop/core/test_agent_loop_adaptive_final.py`

Tests cover:
- Done status skips second core astream when policy reuses execute
- Ledger-direct goal completion bypasses synthesis
- Summary path emits runner goal_completion chunk

## Migration Notes

**Deleted**: `packages/soothe/src/soothe/core/agent_loop/policies/goal_completion_policy.py`

**Replacement imports**:
```python
# Old:
from soothe.core.agent_loop.policies.goal_completion_policy import (
    determine_goal_completion_needs,
    determine_completion_action,
)

# New:
from soothe.core.agent_loop.core.plan_manager import (
    PlanManager,
    CompletionStrategy,
    determine_goal_completion_needs,
)
from soothe.core.agent_loop.graph.nodes.goal_completion import determine_completion_action
```

**Step ID change**: Tests that previously used composite step IDs like `"KFA-01"` must now use plain `step.id` values like `"01"`. PlanDAG keys nodes by `step.id` directly.

## Verification

- [x] All 300+ tests pass (`pytest packages/soothe/tests/`)
- [x] Code review completed
- [x] RFC-219 updated with PlanManager architecture
- [x] No behavior changes (pure refactoring)

## Related Documents

- [RFC-219](../specs/RFC-219-goal-completion-module.md) - Goal Completion Module Architecture
- [RFC-220](../specs/RFC-220-langgraph-agent-loop-orchestrator.md) - LangGraph Agent Loop Orchestrator
- [IG-199](../impl/IG-199-adaptive-final-response.md) - Adaptive Final Response Policy
- [IG-297](../impl/IG-297-goal-completion-module.md) - Goal Completion Module Extraction

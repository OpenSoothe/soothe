# RFC-0011: Dynamic Goal Management During Reflection

**RFC**: 0011
**Title**: Dynamic Goal Management During Reflection
**Status**: Draft
**Created**: 2026-03-18
**Updated**: 2026-03-18
**Related**: RFC-0007, RFC-0009, RFC-0010

## Abstract

This RFC extends the autonomous iteration loop (RFC-0007) with dynamic goal management capabilities during reflection. The PlannerProtocol can now spawn new goals, adjust priorities, add dependencies, and restructure the goal DAG based on what it learns during execution.

## Motivation

RFC-0007 introduced autonomous iteration with goal-driven execution, but reflection was limited to plan revision. When execution discovers missing prerequisites, conflicting requirements, or opportunities for parallel work, the planner should be able to dynamically restructure the goal graph.

### Example Scenario

**Current limitation**: During execution of goal "Implement user authentication", step 2 fails because "database connection library not installed". Reflection can only recommend revising the plan to add a "install library" step.

**Desired behavior**: Reflection should be able to spawn a new high-priority prerequisite goal "Install database library" and make the current goal depend on it, so the prerequisite gets resolved first before retrying.

## Design

### Key Components

1. **GoalDirective Model**: Structured representation of goal management actions (create, adjust_priority, add_dependency, decompose, fail, complete)

2. **GoalContext Model**: Provides reflection with awareness of all goals (active, completed, failed) and their relationships

3. **Enhanced Reflection**: `PlannerProtocol.reflect()` now accepts `goal_context` and returns `goal_directives` alongside plan revision recommendations

4. **Runner Integration**: Autonomous loop processes directives after reflection and handles DAG consistency when goals acquire new dependencies mid-execution

5. **Safety Mechanisms**: Cycle detection, depth validation, and configurable limits to prevent runaway goal creation

### DAG Consistency Handling

**Critical scenario**: When reflection adds a dependency to an active goal, the goal may no longer be executable because its newly added dependencies aren't satisfied yet.

**Solution**: After processing directives, check if the current goal's dependencies are still met. If not:
1. Reset the current goal to "pending" status
2. Abort the current iteration early
3. Let the scheduler pick up the higher-priority prerequisite goals on the next loop iteration
4. The original goal will wait until its dependencies complete

### Data Flow

```
Autonomous Loop (RFC-0007)
  ↓
Execute Plan Steps
  ↓
Reflect(goal_context) → Reflection
  ↓                       ↓
Plan Revision      Goal Directives
  ↓                       ↓
Revise Plan        Process Directives
                          ↓
                    DAG Consistency Check
                          ↓
                    Checkpoint & Continue/Abort
```

## Implementation

### Phase 1: Core Model Enhancements

**File**: `src/soothe/protocols/planner.py`

- Add `GoalDirective` model with action types: create, decompose, adjust_priority, add_dependency, fail, complete
- Add `GoalContext` model with goal state snapshots
- Enhance `Reflection` model with `goal_directives` field
- Update `PlannerProtocol.reflect()` signature to accept `goal_context`

### Phase 2: GoalEngine Safety

**File**: `src/soothe/core/goal_engine.py`

- Add `_calculate_goal_depth()` for hierarchy depth validation
- Add `_would_create_cycle()` for DFS-based cycle detection
- Add `validate_dependency()` for pre-validation of dependency additions
- Add `add_dependencies()` for safe dependency addition with cycle checking
- Enhance `create_goal()` with depth validation

### Phase 3: Autonomous Loop Integration

**File**: `src/soothe/core/_runner_autonomous.py`

- Build `GoalContext` before reflection call
- Process goal directives after reflection
- Apply directives with validation and safety checks
- Handle DAG consistency after mutations
- Emit stream events for goal mutations and deferrals

### Phase 4: Planner Implementation

**File**: `src/soothe/backends/planning/direct.py`

- Update `reflect()` to accept `goal_context` parameter
- Add heuristic directive generation for missing prerequisites
- Generate appropriate directives based on failure analysis

### Phase 5: Configuration

**File**: `src/soothe/config.py`

Add to `AutonomousConfig`:
- `max_total_goals`: Maximum goals allowed (default: 50)
- `max_goal_depth`: Maximum hierarchy depth (default: 5)
- `enable_dynamic_goals`: Master switch for dynamic creation (default: True)

## Safety Considerations

1. **Cycle Detection**: Prevents infinite loops in dependency graphs via DFS
2. **Depth Limits**: Prevents unbounded hierarchy nesting (default: 5 levels)
3. **Total Goals Limit**: Prevents runaway creation (default: 50 goals)
4. **Active Goals Limit**: Prevents resource exhaustion from parallel execution
5. **Validation Before Application**: All directives validated before modifying state
6. **Atomic Checkpoints**: Goal mutations checkpointed immediately after application
7. **Rejection Logging**: All rejected directives logged with reasons

## Testing

### Unit Tests

- Cycle detection with various DAG topologies
- Depth validation with nested hierarchies
- Directive application for each action type
- Dependency validation edge cases

### Integration Tests

- Missing prerequisite scenario (spawns new goal)
- DAG consistency when dependencies added mid-execution
- Checkpoint recovery with mutated goal DAG

## Non-Goals

- LLM-based sophisticated directive generation (ClaudePlanner future work)
- Goal estimation or deadline management
- Resource-aware scheduling

## Success Criteria

1. Reflection can spawn prerequisite goals when detecting missing dependencies
2. Goal DAG remains consistent during dynamic mutations
3. Goals are properly deferred when new dependencies are added
4. All safety mechanisms prevent runaway goal creation
5. Checkpoint persistence includes goal DAG mutations

# IG-028: Dynamic Goal Management During Reflection

**Status**: ✅ Completed - RFC-200 (merged) merged into RFC-200 (2026-03-29)

## Objective

Implement dynamic goal management during autonomous reflection (RFC-200 §5.4),
enabling the planner to create new goals, adjust priorities, and restructure
the goal DAG based on execution insights.

## Scope

1. **Data Models**: GoalDirective, GoalContext, enhanced Reflection
2. **GoalEngine Safety**: Cycle detection, depth validation, dependency validation
3. **Runner Integration**: Directive processing, DAG consistency checks
4. **Planner Enhancements**: Goal-aware reflection with directive generation
5. **Configuration**: Safety limits for dynamic goal creation
6. **Events**: Stream events for goal mutations and deferrals

## Changes

### 1. Planner Protocol Models (`protocols/planner.py` -- EDIT)

| Component | Description |
|-----------|-------------|
| `GoalDirective` | Structured goal management action (create, adjust_priority, add_dependency, etc.) |
| `GoalContext` | Goal state snapshot for reflection context |
| `Reflection.goal_directives` | List of directives from reflection |
| `PlannerProtocol.reflect()` | New `goal_context` parameter |

### 2. GoalEngine Safety (`core/goal_engine.py` -- EDIT)

| Component | Description |
|-----------|-------------|
| `_calculate_goal_depth()` | Depth validation for hierarchical goals |
| `_would_create_cycle()` | DFS-based cycle detection |
| `validate_dependency()` | Pre-validate dependency additions |
| `add_dependencies()` | Safe dependency addition with cycle check |
| `create_goal()` | Enhanced with depth validation |

### 3. Runner Integration (`core/_runner_autonomous.py` -- EDIT)

| Component | Description |
|-----------|-------------|
| Goal context building | Build GoalContext before reflection call |
| `_process_goal_directives()` | Process directives from reflection |
| `_apply_goal_directive()` | Apply individual directive with validation |
| `_check_goal_dag_consistency()` | Handle DAG mutations mid-execution |
| DAG consistency handling | Reset goals to pending when dependencies added |

### 4. Planner Implementation (`cognition/planning/direct.py` -- EDIT)

| Component | Description |
|-----------|-------------|
| `reflect()` enhancement | Accept goal_context, generate directives |
| Heuristic directive generation | Spawn prerequisite goals for missing dependencies |

### 5. Configuration (`config.py` -- EDIT)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_total_goals` | `int` | `50` | Maximum goals allowed |
| `max_goal_depth` | `int` | `5` | Maximum hierarchy depth |
| `enable_dynamic_goals` | `bool` | `True` | Enable/disable dynamic creation |

### 6. Events

| Event Type | Description |
|------------|-------------|
| `soothe.goal.directives_applied` | Goal directives processed |
| `soothe.goal.deferred` | Goal deferred due to new dependencies |

## DAG Consistency Scenario

When reflection adds a dependency to an active goal:
1. Directive processor validates and applies the dependency
2. Consistency checker detects the goal now has unmet dependencies
3. Goal is reset to "pending" status
4. Current iteration aborts early
5. Scheduler picks up prerequisite goals (higher priority) on next loop
6. Original goal waits until dependencies complete

This ensures the goal DAG remains consistent during dynamic mutations.

## Testing

### Unit Tests (`tests/unit_tests/test_dynamic_goals.py` -- NEW)

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

## Implementation Steps

### Step 1: Add Planner Protocol Models

Add `GoalDirective` and `GoalContext` models to `protocols/planner.py` before the `Reflection` class. Enhance `Reflection` with `goal_directives` field. Update `PlannerProtocol.reflect()` signature.

### Step 2: Add GoalEngine Safety Methods

Add cycle detection, depth calculation, and dependency validation methods to `core/goal_engine.py`. Enhance `create_goal()` with depth validation.

### Step 3: Integrate with Autonomous Loop

Modify `core/_runner_autonomous.py` to build goal context, process directives, and handle DAG consistency. Add helper methods for directive processing.

### Step 4: Enhance DirectPlanner

Update `cognition/planning/direct.py` to accept goal context and generate directives heuristically.

### Step 5: Add Configuration

Add safety limit fields to `AutonomousConfig` in `config.py`.

### Step 6: Write Tests

Create comprehensive unit and integration tests for all new functionality.

## Verification

After implementation:

1. Run unit tests: `pytest tests/unit_tests/test_dynamic_goals.py -v`
2. Test integration scenario with missing prerequisite
3. Verify DAG consistency handling
4. Check checkpoint persistence includes goal mutations

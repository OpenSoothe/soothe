# Context Engine GoalStepDAG Status Recording

**Date:** 2026-06-12
**RFC:** RFC-624 Phase 3
**Scope:** When CE path is enabled, record the full hierarchical GoalStepDAG at goal completion instead of the flat PlanDAG format.

## Problem

The current `ContextEnginePlanAdapter.format_completion_dag_report()` renders only the active goal's flat step DAG — the same format as PlanManager. This loses the hierarchical structure that ContextEngine tracks: multiple goals with parent/child relationships, lineage, and per-goal step DAGs with execution metadata.

## Current Behavior

At goal completion, `goal_completion.py` calls `plan_manager.format_completion_dag_report()` and logs the result. When CE is enabled, the adapter produces output identical to PlanManager:

```
### Plan DAG (at goal completion)

**Execution statistics**
- Planned steps (nodes): 1
- Completed: 1
- Failed: 0
...

**Steps**
- **MNC-01** — COMPLETED
  - Depends on: —
  - list all folder of current workspace
```

This only shows the active goal's StepDAG. The full GoalStepDAG with multiple goals, sub-goals, lineage, and execution metadata is not surfaced.

## Proposed Change

### 1. Hierarchical DAG Report Format

When CE is enabled, `ContextEnginePlanAdapter.format_completion_dag_report()` renders the full `GoalStepDAG`:

```
### Context Engine Goal DAG (at goal completion)

**Goal statistics**
- Total goals: 3
- Completed: 2, Failed: 1, Pending: 0, Active: 0

**Goal f4d91ad4** — COMPLETED
- Description: list all folder of current workspace
- Source: user, Priority: 50
- Parent: —
- Thread: 019ebb4d..., Loop: 019ebb4d...
- Tokens used: 1234

  **Step DAG** (1 step, completed=1, failed=0, depth=1, success=100%)
  - **MNC-01** — COMPLETED
    - Depends on: —
    - list all folder of current workspace

**Goal a1b2c3d4** — FAILED
- Description: analyze error patterns
- Source: decomposition, Priority: 40
- Parent: f4d91ad4
- Lineage: list all folders > analyze error patterns
- Tokens used: 567

  **Step DAG** (2 steps, completed=0, failed=2, depth=1, success=0%)
  - **KFA-01** — FAILED
    - Depends on: —
    - search for error logs
  - **KFA-02** — FAILED
    - Depends on: KFA-01
    - parse error patterns
```

Key fields per goal:
- Status, description, source, priority
- Parent ID (if sub-goal) and lineage chain
- Thread and loop IDs
- Total tokens used
- Nested Step DAG with per-step status, dependencies, and description

### 2. Persist CE State at Goal Completion

Call `ce_instance.save()` in `goal_completion.py` when CE is enabled, after the DAG report is generated. This ensures the full GoalStepDAG state is persisted to the file backend for post-run inspection.

Currently, `save()` is only called during crash recovery. Adding it at goal completion guarantees the final state is durable.

### 3. Labeled Header

The report header changes from `"### Plan DAG (at goal completion)"` to `"### Context Engine Goal DAG (at goal completion)"` when the CE adapter produces it. This makes the data source explicit in logs.

### 4. Compatibility

- `PlanManager.format_completion_dag_report()` remains unchanged
- The adapter's method supersedes PlanManager when CE is enabled
- `goal_completion.py` calls `plan_manager.format_completion_dag_report()` regardless — the adapter determines the format
- Non-CE path produces identical output to current behavior

## Files Changed

| File | Change |
|------|--------|
| `context_adapters.py` | Rewrite `format_completion_dag_report()` to render full GoalStepDAG |
| `goal_completion.py` | Add `ce_instance.save()` call when CE is enabled |
| `test_context_adapters.py` | Update tests for new report format |

## Implementation Notes

- The `format_completion_dag_report()` method has access to `self._ce._dag` (the full `GoalStepDAG`)
- Goal iteration order: sort by status (failed first, then completed, then others), then by `created_at`
- Lineage is rendered only when `parent_id` is not None
- Step descriptions are truncated at 280 chars (same as current)
- The `save()` call is async, so it needs `await` in the goal_completion node

# IG-514: Execute Namespace Tool Stamping Fix (Parallel Steps)

**Status**: Completed
**RFC**: [RFC-628](../specs/RFC-628-step-card-display-refactor.md) — step card tool activity display
**Depends on**: IG-512 (step card refactor)
**Created**: 2026-06-27
**Loop analysis**: `819e` (019f0808-050a-70a1-adfa-c7e957b6819e)

## Objective

Fix bug where tools streamed under parallel step namespaces `('execute:{run_id}', 'N')` were incorrectly stamped with `t0:` prefix (task-level) instead of `s:` prefix (step-level), causing tool activity to be absent from step card display.

## Problem

When the executor processes streaming AIMessage chunks for parallel steps, it assigns `task_idx` based on namespace:

```python
# In executor.py _act_stream_collector
if _ns_chunk:
    task_idx = subgraph_task_binder.task_idx_for_namespace(stream_ns)
```

The original `is_step_level_execute_namespace_key()` only handled single-element namespaces like `('execute:{run_id}',)`. It returned `False` for parallel branch namespaces like `('execute:{run_id}', '1')`, causing them to be treated as subgraph namespaces and assigned `task_idx=0`.

As a result:
- Parallel step tools stamped with `{step}:t0:{tool}` IDs (task-level)
- No parent `task` delegation row exists (since parallel steps don't use task delegation)
- TUI routing cannot find a SubAgent card for `t0:` prefix
- Tools never appear on step card activity panel

## Root Cause Analysis

From loop `819e` logs:

| Step | Namespace | Expected prefix | Actual prefix | Display |
|------|-----------|-----------------|---------------|---------|
| JBF-01 | `('execute:9ca81bee...',)` | `s:` | `s:` | ✓ Visible |
| JBF-02 | `('execute:9ca81bee...', '1')` | `s:` | `t0:` | ✗ Hidden |

The second parallel step used namespace with branch index `1`, which was incorrectly classified as a subgraph namespace.

## Solution

### 1. Added `is_parallel_branch_namespace()` helper

Explicitly detects parallel branch namespaces:

```python
def is_parallel_branch_namespace(ns_key: tuple[str, ...]) -> bool:
    """True for parallel step branch namespaces like ('execute:{run_id}', '1')."""
    if len(ns_key) != 2:
        return False
    first = str(ns_key[0] or "").strip()
    if not first.startswith("execute:"):
        return False
    second = str(ns_key[1] or "").strip()
    # Branch index is pure integer string (LangGraph parallel pattern)
    return second.isdigit()
```

### 2. Updated `is_step_level_execute_namespace_key()`

Now returns `True` for BOTH:
- Root execute namespaces: `('execute:{run_id}',)`
- Parallel branch namespaces: `('execute:{run_id}', 'N')`

```python
def is_step_level_execute_namespace_key(ns_key: tuple[str, ...]) -> bool:
    # Single-element execute namespace (root)
    if is_execute_namespace_key(ns_key):
        return True
    # Two-element parallel branch namespace (execute:* + integer)
    if is_parallel_branch_namespace(ns_key):
        return True
    return False
```

### 3. Namespace Classification Table

| Namespace pattern           | `is_execute_namespace_key` | `is_parallel_branch_namespace` | `is_step_level` | Tool prefix |
|-----------------------------|---------------------------|-------------------------------|-----------------|-------------|
| `('execute:run_id',)`       | True                      | False                         | True            | `s:`        |
| `('execute:run_id', '1')`   | False                     | True                          | True            | `s:`        |
| `('execute:run_id', 'tools:')` | False                | False                         | False           | `t{n}:`     |
| `('tools:...',)`            | False                     | False                         | False           | `t{n}:`     |

## File Map

```
packages/soothe-sdk/
├── src/soothe_sdk/ux/execute_namespace.py
│   ├── is_parallel_branch_namespace() [NEW]
│   └── is_step_level_execute_namespace_key() [UPDATED]
└── tests/unit/ux/test_execute_namespace.py
    └── test_is_parallel_branch_namespace() [NEW]
    └── test_is_step_level_execute_namespace_key() [UPDATED]
```

## Verification

- [x] Unit tests for `is_parallel_branch_namespace()` pass
- [x] Unit tests for `is_step_level_execute_namespace_key()` pass
- [x] `make lint` passes
- [x] Full verification suite passes

## Notes

- This fix ensures parallel step tools receive `s:` prefix and display on their respective step cards
- The executor's `is_step_level_execute_namespace_key()` check now correctly handles parallel branches
- Subgraph delegation namespaces (`tools:*`) remain unaffected and receive `t{n}:` prefix as expected
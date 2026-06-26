# IG-514: Execute Namespace Tool Stamping Fix

**Status**: Completed
**RFC**: [RFC-628](../specs/RFC-628-step-card-display-refactor.md) — step card tool activity display
**Loop analysis**: `loop-6f21` (019f04ba-85f5-72b2-ab12-a0446e736f21)

## Objective

Fix bug where tools streamed under `execute:{run_id}` namespace were incorrectly stamped with `t0:` prefix (task-level) instead of `s:` prefix (step-level), causing tool activity to be absent from step card display.

## Problem

When the executor processes streaming AIMessage chunks, it assigns `task_idx` based on namespace:

```python
if _ns_chunk:
    task_idx = subgraph_task_binder.task_idx_for_namespace(stream_ns)
```

This logic treats `execute:{run_id}` namespace as a subgraph namespace, returning `task_idx=0` and stamping tools with `t0:` prefix. But `execute:{run_id}` is actually step-level (root graph), not subgraph.

As a result:
- Tools appear with unified IDs like `YCR_01:t0:tool-...` (task-level)
- No parent `task` delegation row exists (since there's no `task` call)
- TUI routing cannot find a SubAgent card for `t0` prefix (no `task` row created)
- Tools never appear on step card activity panel

## Fix

Added check in `_act_stream_collector` to skip `task_idx` assignment for any
``execute:…`` namespace (root or nested ``/N`` from sole-child thread reuse):

```python
# IG-514: execute:* namespaces are step-level, not subgraph.
if _ns_chunk and not is_step_level_execute_namespace_key(_ns_chunk):
    task_idx = subgraph_task_binder.task_idx_for_namespace(stream_ns)
```

The same guard applies when rewriting namespaced ``ToolMessage`` ids (the path
that emits ``[ExecuteTool]`` / ``[SubagentTool]`` wire updates — execute
namespaces log as ``ExecuteTool`` and skip subgraph placeholder emission).

``is_execute_step_namespace()`` in the CLI matches **root** execute only
(``execute:{run_id}`` without ``/N``) for subgraph namespace registration.
``is_step_card_tool_scope()`` treats any ``execute:…`` segment (including ``/N``)
as main step-card scope so sole-child reuse still renders ``s:`` tools.

This ensures:
- `execute:{run_id}` and `execute:{run_id}/N` → `task_idx=None` → step-level `s:` prefix
- `tools:…` namespace → `task_idx=0/1/…` → task-level `t{n}:` prefix

## File map

```
packages/soothe/src/soothe/foundation/loop/engine/executor.py
└── _act_stream_collector: added execute namespace check before task_idx assignment
```

## Testing

- Existing unit tests pass (routing logic unchanged for true subgraph namespaces)
- Manual verification: tools now appear on step card with `s:` prefix

## Notes

- This fix aligns with `is_execute_step_namespace()` in CLI package (tool_call_resolution.py)
- The TUI routing already handles `s:` prefix correctly via `apply_tool_call_wire_update`
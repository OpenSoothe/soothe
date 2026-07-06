---
title: "Loop-Level Protocols"
parent: Protocols
grand_parent: Wiki
nav_order: 7
description: >-
  Loop working memory, StrangeLoop, LoopPlanner, and OperationSecurity protocols for loop-level execution control.
---

# Loop-Level Protocols

**RFCs**: 203 (LoopWorkingMemory), 220 (StrangeLoop), 604 (LoopPlanner), 617 (OperationSecurity)
**Locations**:
- `packages/soothe/src/soothe/protocols/loop_working_memory.py`
- `packages/soothe/src/soothe/protocols/loop_planner.py` (covered in [planner.md](planner.md))
- `packages/soothe/src/soothe/protocols/operation_security.py`
**Status**: Implemented

## What Loop-Level Protocols Are

These protocols serve StrangeLoop's Plan → Execute cycle specifically. They are *not* general-purpose infrastructure — they exist because the agentic loop has unique needs: a bounded scratchpad for planning prompts, and operation-level security checks during execution.

Two protocols live here:

1. **`LoopWorkingMemoryProtocol`** — a bounded scratchpad that records Act-step outcomes and renders them into Plan-phase prompts.
2. **`OperationSecurityProtocol`** — operation-level security evaluation for individual tool calls and spawns.

(`LoopPlannerProtocol` is documented in [planner.md](planner.md) since it shares the planner domain.)

## LoopWorkingMemoryProtocol

### Role

During a StrangeLoop, each Execute phase produces step results. The Plan phase (next iteration) needs to see what happened — but not the full raw history, which would blow the LLM context window. `LoopWorkingMemoryProtocol` is the bounded intermediary: it records step outcomes, then renders a *truncated* view for the planner.

### Key Operations

- **`clear()`** — reset for a new goal. Called at loop start.
- **`record_step_result(step_id, description, output, error, success, workspace, thread_id)`** — record one Act-step outcome. Outputs are truncated to bounded previews (e.g., 200 chars) to control size.
- **`render_for_reason(max_chars?)`** — return formatted text for Plan-phase prompt injection. When `max_chars` is set, the rendered text is hard-truncated.

### Design Principle: Bounded Memory

Working memory is deliberately bounded — the default implementation caps at ~20 entries with truncated previews. The philosophy: the planner needs *recent* outcomes and *patterns*, not exhaustive history. When memory exceeds the bound, oldest entries are evicted (FIFO).

```
Execute phase: record_step_result(...) → memory grows (bounded)
Plan phase:    render_for_reason(max_chars=2000) → bounded slice injected into prompt
```

This bounded approach contrasts with `ContextProtocol` (future), which would provide *unbounded* accumulation with relevance-based projection. Working memory is the pragmatic, always-available scratchpad; Context would be the richer, persistent ledger.

### Workspace Spill

When bounded memory exceeds limits, implementations *may* spill overflow to a workspace file (e.g., `.soothe/working_memory_spill.json`) before evicting from the in-memory list. This is optional — the protocol doesn't mandate it — but it preserves detail that bounded eviction would lose. Recent entries stay in memory; older ones spill to disk.

### Implementation

The default implementation (`DefaultWorkingMemory`) is an in-memory bounded list with truncated output previews, error tracking, and optional workspace spill. Configurable via `agent.loop.working_memory` settings (`max_entries`, `max_chars_per_entry`, `spill_to_workspace`).

## OperationSecurityProtocol

### Role

`OperationSecurityProtocol` provides **operation-level security checks** — evaluating whether a specific operation (tool call, shell command, file write) should proceed. It's a normalized, operation-focused layer distinct from the broader `PolicyProtocol`.

### Key Operation

- **`evaluate(request, context) → OperationSecurityDecision`** — evaluate whether an operation should be allowed, returning a verdict (`allow` / `deny` / `need_approval`) with a reason.

### Operation Kinds

The protocol normalizes operations into typed kinds:

- `filesystem_read`, `filesystem_write` — file operations
- `shell_execute`, `python_execute` — code execution
- `process_control` — process management
- `generic` — fallback

This typing lets security rules target specific operation categories (e.g., audit all `shell_execute` calls) without parsing tool arguments generically.

### Request and Context

- **`OperationSecurityRequest`** — carries `action_type`, `tool_name`, `tool_args`, `operation_kind`, `target_path`, and `command` (for shell operations). This is richer than `PolicyProtocol`'s `ActionRequest` because it includes operation-specific extraction (path, command).
- **`OperationSecurityContext`** — thread ID, workspace path, and security config. Workspace is used for stream-scoped filesystem policy.
- **`OperationSecurityDecision`** — verdict, reason, optional `rule_id` for audit traceability.

### Relationship to PolicyProtocol

`OperationSecurityProtocol` and `PolicyProtocol` are complementary, not redundant:

- **`PolicyProtocol`** (see [policy.md](policy.md)) operates on structured `Permission` grants (category/action/scope) and computes narrowed permission sets for subagent delegation. It's the *policy decision* layer.
- **`OperationSecurityProtocol`** is the *operation evaluation* layer — it normalizes concrete operations (a shell command, a file path) into security requests and applies rules, potentially delegating to `PolicyProtocol` for permission matching.

In practice, operation security can wrap policy: convert an `OperationSecurityRequest` into an `ActionRequest`, call `PolicyProtocol.check()`, then augment the result with operation-specific concerns (audit logging, path validation).

## Integration with StrangeLoop

These protocols plug into the Plan → Execute cycle at specific points:

```
StrangeLoop iteration:
  Plan phase:
    → LoopWorkingMemory.render_for_reason() injected into planner prompt
    → LoopPlanner.plan() produces PlanResult
  Execute phase:
    → OperationSecurity.evaluate() checks each tool call before execution
    → LoopWorkingMemory.record_step_result() captures outcome
  → next iteration
```

Working memory flows *into* the Plan phase (rendering); operation security gates the Execute phase (checking). Both are per-loop, in-memory, and reset between goals.

## Gotchas

- **Working memory is per-loop, not per-thread** — `clear()` is called at the start of each goal/loop. Cross-thread continuity requires `MemoryProtocol`, not working memory.
- **Truncation is lossy** — `record_step_result` truncates outputs to bounded previews. If you need full output, capture it separately; working memory is for the planner's summary view.
- **Operation security may run synchronously** — unlike persistence protocols, `evaluate()` is not async in the source. Don't block on external calls inside it.
- **`operation_kind` affects audit** — security config can specify which operation kinds require audit logging (`audit_operations` list). Generic kind misses targeted audit rules.

## Configuration

```yaml
agent:
  loop:
    working_memory:
      max_entries: 20
      max_chars_per_entry: 200
      spill_to_workspace: false
  security:
    audit_operations: [shell_execute, subagent_spawn]
    audit_log_path: ~/.soothe/logs/operations.log
```

## Related Documentation

- [Planner Protocol](planner.md) — `LoopPlannerProtocol` consumes working memory
- [Policy Protocol](policy.md) — `PolicyProtocol` backs operation security decisions
- [Execution Protocols](execution-protocols.md) — `LoopRunnerProtocol` orchestrates the loop
- [Context Protocol](context.md) — future unbounded ledger

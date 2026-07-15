# IG-653 Tool Optimization Middleware Architecture

## Goal

Summarize the current tool optimization landscape and formalize a middleware-centric architecture where deterministic tool-call optimization remains in middleware, while step lifecycle control remains in executor.

## Background

Loop diagnostics (including `146e`) showed repeated lookup calls, redundant shell fallback searches, and costly no-progress stretches in execution steps.

Before this guide, optimization logic lived in `ToolCallArgsMiddleware` together with invocation arg recording. That mixed two concerns:

- `ToolCallArgsMiddleware`: display-oriented invocation arg capture
- Tool optimization policy: deterministic reuse/dedup/search controls

This guide separates them into dedicated middleware roles.

## Optimization Landscape (Current)

### Middleware controls

- Lookup reuse cache for deterministic signatures (`read_file`, `glob`, `grep`)
- Duplicate empty-result replay blocking
- Search consolidation (native search before shell grep fallback)
- Cache invalidation on mutating tools
- Per-scope optimization counters

### Executor controls

- Per-step tool budget cap
- Subagent task cap per wave
- Stream no-progress watchdog / timeout
- Step outcome assembly and telemetry emission

## Target Architecture

### Responsibility split

1. **`ToolCallArgsMiddleware`** (single responsibility)
   - Capture and record tool-call args for downstream wire display
   - No optimization policy logic

2. **`ToolOptimizationMiddleware`** (single responsibility)
   - Deterministic optimization and policy:
     - same-signature lookup reuse
     - duplicate empty-result blocking
     - native-search-first shell fallback suppression
     - mutation invalidation
   - Export scope metrics for executor telemetry

3. **`Executor`**
   - Remains owner of step lifecycle semantics:
     - budgets, retries, watchdog, step success/failure
   - Consumes middleware metrics and emits step outcome telemetry

### Middleware stack order

Required relative order:

- `ToolCallArgsMiddleware`
- `ToolOptimizationMiddleware`
- `EditCoalescingMiddleware`

Rationale:

- Args are captured before any interception.
- Optimization policy runs before coalescing/interception effects.
- Edit coalescing remains focused on edit batching behavior.

## Implementation Scope

- Introduce `soothe.middleware.tool_optimization_middleware`.
- Move optimization logic out of `tool_call_args_middleware`.
- Rewire imports and telemetry consumer in executor.
- Mount optimization middleware in main stack and explore subagent stack.
- Split tests by responsibility:
  - args-recording tests stay in `test_tool_call_args_registry.py`
  - optimization behavior tests move to `test_tool_optimization_middleware.py`

## Cleanse Plan

- Remove superseded optimization state and helper functions from `ToolCallArgsMiddleware`.
- Remove mixed-responsibility tests from args middleware suite.
- Keep behavior equivalent by preserving optimization test coverage under the new middleware.

## Verification Plan

1. Unit: args recording middleware tests
2. Unit: tool optimization middleware tests (reuse/dedup/consolidation/invalidation)
3. Unit: executor metrics/watchdog tests
4. Full gate: `./scripts/verify_finally.sh`

## Acceptance Criteria

- Tool optimization behavior remains functionally equivalent after middleware split.
- Middleware responsibilities are cleanly separated by concern.
- Executor lifecycle behavior remains unchanged.
- Full repository verification passes.

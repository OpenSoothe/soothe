# IG-598: Loop Tool Execution Performance Optimization

## Goal

Reduce end-to-end loop execution latency and token overhead by eliminating repetitive low-value tool calls, improving no-result handling, and right-sizing verification work for simple code edits.

## Scope

- Add execution-level safeguards that stop redundant same-argument tool retries when prior calls produced no actionable output.
- Reduce repeated `read_file` and search scans within a step by introducing bounded, step-local lookup reuse.
- Improve plan/execute prompting and tool policy so simple edit tasks avoid search-heavy drift.
- Split verification strategy into fast scoped checks first, with full verification reserved for final gate.
- Add observability fields to quantify repetitive calls, empty-result retries, and verification wall-time share.

## Non-goals

- No changes to core correctness semantics of file tools (`read_file`, `glob`, `grep`, `run_command`).
- No changes to user-facing protocol contracts for step/goal events.
- No disabling of full repository verification before merge/commit requirements.
- No heuristic keyword rules for content judgment; structural/deterministic policy only.

## Problem Statement

Loop `81f0` showed high tool-call overhead and avoidable delay:

1. Repeated same-query lookups with no result (for example repeated `grep` on the same path/pattern).
2. Excessive lookup volume for a simple UI symbol replacement, including repeated scans of already known files.
3. Long-running full verification command executed inside the step, dominating wall-clock time.
4. Miss-first path probing followed by broader discovery, increasing round trips and tokenized tool traces.

This creates slower loops, larger prompt ledgers, and higher chance of cancellation/retry during long steps.

## Proposed Design

### 1) Deterministic no-result retry guard

At execute runtime, add a structural guard for identical tool call signatures:

- Signature key: `(step_id, tool_name, normalized_args)`.
- If a call result is empty/no-match and an identical signature is retried immediately without new evidence, block and return a structured guidance message (reuse prior result or broaden query).
- Allow override only when arguments materially change.

This is deterministic control logic, not keyword intent classification.

### 2) Step-local lookup reuse cache

Introduce a bounded per-step cache for read/search outputs:

- Cache same `read_file` slices and same search calls (`glob`/`grep`) by normalized args.
- Reuse cached results for repeated identical lookups in the same step.
- TTL/lifecycle is step-scoped and cleared at step end.
- Include cache-hit metrics in step telemetry.

### 3) Simple-edit lookup budget policy

For simple edit execution profiles:

- Tighten guidance to prefer direct-file edit path once target file is identified.
- Cap repeated search tool usage before requiring a strategy shift (for example, read known file, then edit).
- Favor one broad discovery call followed by direct operations, not many narrow retries.

### 4) Two-phase verification strategy

Codify verification flow for edit steps:

- Phase A (in-step): fast scoped checks tied to touched files/tests.
- Phase B (final gate): full `./scripts/verify_finally.sh` before completion handoff/commit workflow.

This preserves quality gates while preventing long blocking verification from dominating edit steps.

### 5) Observability additions

Add execution counters and timings:

- `repeated_signature_calls`
- `repeated_empty_result_calls_blocked`
- `step_cache_hits` / `step_cache_misses`
- `verification_time_ms_scoped`
- `verification_time_ms_full`

Expose these in step completion logs and aggregated loop diagnostics.

## Implementation Plan

1. Add normalized signature utility and repeated-empty guard in execution tool dispatch.
2. Add step-local lookup cache abstraction with bounded size.
3. Wire cache into `read_file`/`glob`/`grep` execution paths.
4. Update simple-edit execution guidance and structural budget thresholds in config-backed rules.
5. Refactor verification invocation flow to scoped-then-full phases.
6. Add unit tests and targeted integration tests for guard, cache, and verification routing.
7. Validate with loop replay/benchmark scenarios similar to `81f0`.

## Cleanse Plan

- Remove superseded duplicated tool-call handling branches once guard/cache path is authoritative.
- Remove any old ad-hoc retry logic replaced by normalized signature control.
- Remove redundant verification invocation paths that conflict with two-phase strategy.

## Testing Plan

- Unit tests:
  - identical empty-result call is blocked on retry without arg changes
  - changed args bypass guard
  - cache returns reused value for identical tool args inside one step
  - cache is cleared between steps
- Integration tests:
  - simple edit scenario completes with reduced search/read call count
  - scoped checks run in-step and full verify runs at final gate
- Performance checks:
  - compare baseline vs optimized on representative edit loops
  - assert reduced wall time and repeated-call counters

## Risks and Mitigations

- **Risk:** Guard blocks a legitimate retry after external file change.
  - **Mitigation:** allow retry when file mtime/context hash changed or args differ.
- **Risk:** Cache serves stale data within long step.
  - **Mitigation:** step-local scope plus invalidation on successful writes to same path.
- **Risk:** Scoped checks miss regressions.
  - **Mitigation:** keep full verify as mandatory final gate; scoped checks are latency optimization only.

## Acceptance Criteria

- Repeated identical empty-result tool calls are reduced by at least 80% in benchmark loops.
- Average tool calls per simple edit step decreases materially (target: 30%+ reduction).
- Long-step wall time improves on loop patterns similar to `81f0` (target: 25%+ reduction).
- Full verification remains enforced before final handoff/commit flow.
- Added tests pass and `./scripts/verify_finally.sh` remains green after implementation.

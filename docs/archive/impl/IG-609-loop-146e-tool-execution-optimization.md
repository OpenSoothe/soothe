# IG-609 Loop 146e Tool Execution Optimization

## Goal

Reduce loop wall time and token overhead by eliminating repetitive no-value tool calls and by recovering faster from stalled execution in steps like `FAM-01` and `FAM-03`.

## Incident Baseline

Observed in loop `146e`:

- `FAM-01`: 22 tool calls with overlapping search strategies (`grep` fan-out plus shell `run_command` grep sweep).
- `FAM-03`: 18 `read_file` calls for a targeted reference-update task, followed by long no-progress behavior.
- Prior delete crash is fixed in `soothe-deepagents==0.7.21`; this guide covers remaining execution efficiency issues.

## Scope

- Execution-time optimization in step tool dispatch (`grep`, `glob`, `read_file`, `run_command`).
- Deterministic controls for duplicate call patterns.
- Bounded evidence collection for reference-update style steps.
- No-progress watchdog and re-assess handoff.
- Telemetry additions for measurable improvements.

## Non-Goals

- No user-visible event schema changes.
- No behavior changes to tool semantics or output formats.
- No keyword/regex heuristics for intent judgment.

## Design

### 1) Duplicate Signature Guard (deterministic)

Use normalized key:

- `(step_id, tool_name, normalized_args)`

Rules:

- If same key repeats in the same step and prior result was empty/non-actionable, block replay and return structured guidance.
- Allow replay only when args differ materially or local context changed (for example, post-write invalidation).

Primary effect:

- Removes redundant same-query retries that add cost but no new evidence.

### 2) Retrieval Funnel for Reference Updates

For steps that update references:

1. One broad discovery call.
2. Candidate ranking/filtering.
3. Bounded targeted reads (top-N).
4. Move to edit/apply stage.

Policy intent:

- Prevent open-ended document sweeps when task scope is narrow.

### 3) Search Consolidation Rule

In-step search precedence:

1. Native tool search (`grep`/`glob`).
2. Shell search fallback (`run_command`) only when native tools cannot satisfy required scope/format.

Guardrail:

- Do not run equivalent shell search after already covering same scope with native tools.

### 4) Step No-Progress Watchdog

Detect active-step stalls:

- No tool completion and no step state transition within threshold.

Response:

- Emit diagnostic event.
- Trigger controlled `plan_assess`/replan path.
- Preserve dependency semantics; no forced step completion.

### 5) Observability

Add step-level metrics:

- `duplicate_signature_calls`
- `duplicate_signature_blocked`
- `search_calls_total`
- `search_calls_shell_fallback`
- `evidence_reads_total`
- `no_progress_watchdog_triggered`
- `step_wall_time_ms`

## Implementation Plan

1. Add normalized signature utility in executor tool-dispatch path.
2. Wire duplicate-signature blocking with explicit bypass conditions.
3. Add retrieval funnel budget controls for reference-update step type.
4. Add search consolidation enforcement between tool search and shell fallback.
5. Implement no-progress watchdog and handoff into plan reassessment.
6. Emit new telemetry fields in step completion and loop diagnostics.

## Cleanse Plan

- Remove superseded duplicate-call paths once guard is authoritative.
- Remove redundant shell-search fallback branches made unreachable by consolidation rule.
- Keep functional behavior unchanged while deleting dead or parallel code paths.

## Verification Plan

1. Unit tests:
   - duplicate empty-result replay blocked
   - changed args/context bypasses block
   - shell fallback suppressed after equivalent native search
2. Integration tests:
   - replay `FAM-01` style scenario with reduced search calls
   - replay `FAM-03` style scenario with bounded evidence reads
   - watchdog emits and reroutes on synthetic no-progress
3. Final gate:
   - `./scripts/verify_finally.sh`

## Acceptance Criteria

- >=30% reduction in tool-call count for `FAM-01`/`FAM-03`-like tasks.
- Zero duplicate same-signature empty-result replays without valid bypass reason.
- Watchdog triggers and re-assess route works for stall scenarios.
- No regressions in tool behavior; full verification remains green.

# IG-027: Final Report CLI Output and LLM Synthesis

**Implements**: RFC-0010 (Final Report Gap)
**Status**: Active
**Created**: 2026-03-18
**Related**: IG-023, IG-024, RFC-0009, RFC-0010

## Problem

After an autonomous run completes, the CLI shows no consolidated final report.
Individual step outputs stream to stdout during execution, but the cross-validated
synthesis (RFC-0010) is invisible to users for two reasons:

1. **LLM synthesis never fires**: `_synthesize_root_goal_report` checks
   `hasattr(self._planner, "_invoke")`, but `AutoPlanner` (the default planner
   router) has no `_invoke` method. This causes every run to fall back to a
   one-liner heuristic: `"Completed N/N steps. Results: desc1; desc2; ..."`.

2. **Report never reaches stdout**: The synthesized summary only appears in the
   `soothe.goal.report` custom event (truncated to 200 chars, rendered on stderr)
   and the artifact store file on disk.

Additionally, IG-024 gaps (checkpoint.saved event, thread deletion cleanup) are
already implemented but the guide still shows Draft status.

## Solution

### Phase 1: Enable LLM synthesis for all planner configurations

Add `_invoke(prompt) -> str` to `DirectPlanner` and `AutoPlanner` so the
synthesis method works regardless of which planner backend is active.

- `DirectPlanner._invoke`: wraps `self._model.ainvoke(prompt)`
- `AutoPlanner._invoke`: delegates to `_best_available()._invoke(prompt)`

### Phase 2: Rewrite synthesis prompt and heuristic fallback

Replace the 3-5 sentence prompt with one that produces a full structured report:
- Consolidated findings from all steps
- Cross-validation notes (contradictions, agreements)
- Key data extracted from step results
- Confidence assessment

Increase step result truncation from 400 to 2000 chars to give the LLM complete
information.

Improve the heuristic fallback to produce a multi-section summary that
concatenates key results from each completed step, rather than a one-liner.

### Phase 3: Emit final report as stdout text

Emit a `soothe.autonomous.final_report` custom event in `_run_autonomous` after
the goal loop completes. The CLI headless paths handle this event by printing
the full report to stdout with a visual separator.

## Files to Modify

| File | Changes |
|------|---------|
| `backends/planning/direct.py` | Add `_invoke` method |
| `backends/planning/router.py` | Add `_invoke` delegation |
| `core/runner.py` | Rewrite synthesis prompt, improve heuristic, emit final report event |
| `cli/main.py` | Handle `soothe.autonomous.final_report` in headless CLI |
| `core/artifact_store.py` | Improve goal report markdown when summary is substantial |
| `docs/impl/024-rfc0010-gap-fixes.md` | Update status to Completed |

## Verification

- `make lint` passes
- Unit tests pass
- Manual test: autonomous run produces structured report on stdout

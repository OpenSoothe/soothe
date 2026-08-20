# IG-757 — sloop engine/stages module layout cleanup

## Summary

Post-audit cleanup of `soothe/sloop/engine/` and `soothe/sloop/stages/`:
remove dead surface left behind by the RFC-904 DISPATCH cutover, fix the
engine→stages import inversion, delete the phantom `stages/plan/` package,
and deduplicate shared helpers.

## Changes

### 1. Dead-surface deletion (shipped in v0.10.23)

- `engine/__init__.py`: dropped the unused package-root re-export surface
  (all consumers import concrete submodules).
- `engine/graph_interrupt.py`: removed `await_next_graph_stream_chunk`
  (zero callers) and `_detect_tool_boundary` (test-only compat shim; tests
  now call `_classify_stream_chunk` directly).
- `engine/tool_call_id.py`: removed `_extract_tool_name_from_ai_chunk`
  (zero callers).
- `engine/anchor_manager.py`: removed `capture_iteration_start_anchor`
  (no production caller since CheckLimitsNode removal; only iteration-end
  anchors are captured).
- `engine/thread_selection.py`: collapsed the dead fork/linear branch in
  `_select_thread_for_step` (both arms returned the same value).
- `engine/context_window_manager.py`: corrected the misleading
  "aggressive compaction" comment on the identical-policy retry.
- `stages/decompose/__init__.py`, `stages/plan/__init__.py`: dropped unused
  re-export surface.

### 2. Composition-root relocation

`engine/strange_loop.py` → `sloop/strange_loop.py`. `StrangeLoop` is the
composition root: it lazily imported `stages.preprocess.intake` and
`stages.complete.finalize`, while stages import engine machinery — an
engine→stages (lazy) inversion. Moving the composition root to the package
root restores the one-way direction:

```
sloop/strange_loop.py → stages → engine
```

Updated import/patch sites: `sloop/__init__.py` (lazy root export),
`orchestrator/runtime_context.py`, `orchestrator/checkpoint.py`,
`runner/_runner_strange_loop.py`, `soothe-autopilot/runner.py`,
`soothe-daemon/runtime/loop_dispatcher.py` (docstring),
`scripts/visualize_strange_loop_graph.py`, and the StrangeLoop test-suite
patch targets.

### 3. Phantom `stages/plan/` removal

`stages/plan/phase_status.py` → `orchestrator/phase_status.py`. The
plan-spine stations were removed in IG-752; the directory survived only as
a home for the cross-station status-card helper. It is graph plumbing, so
it lives with the orchestrator now. Importers updated:
`stages/preprocess/intake.py`, `stages/sidecars/delegate.py`,
`stages/complete/finalize.py`.

### 4. Helper dedupe

- `_maybe_await` (triplicated in `dispatch.py`, `reconcile_node.py`,
  `root_eval.py`) → single definition in `orchestrator/node_base.py`.
- `_message_step_id` (duplicated in `predecessor_branch_context.py` and
  `step_predecessor_context.py`) → single definition in
  `predecessor_branch_context.py`.

## Intentionally not done

- **Executor satellite consolidation**: `executor.py` plus its ~14
  satellites are split between `engine/` and `stages/execute/` (~50 import
  sites). Deferred pending direction choice: (a) move machinery under
  `stages/execute/`, or (b) sub-package `engine/execute/` +
  `engine/completion/`.
- **`_build_loop_state_view` merge** (`stages/execute/execute.py` vs
  `stages/sidecars/delegate.py`): the two builders intentionally differ
  (plan-summary source, recent step outputs); merging would be a
  param-refactor, not a deletion. Skipped per the cleanse rule
  (consolidation must not rewrite behavior).

## Verification

`./scripts/verify_finally.sh` — format, lint, vulture, import boundaries,
unit tests all green.

# IG-479: AgentLoop Ledger and TUI Subgraph Tool Visibility Fixes

## Goal

Fix three coupled regressions observed in daemon runs for simple tool-driven goals (`list dir of current workspace`):

1. Execute-step ledger frequently captured placeholder/empty evidence.
2. Plan-assess repeatedly returned `continue/none` despite successful tool execution.
3. Step card in TUI showed `· N tools` but did not render subgraph tool activity rows.

Also improve local Docker build performance to avoid reinstalling unchanged dependencies.

---

## Symptom Summary

### A) Ledger evidence degraded to placeholder or empty summary

- Execute-step AI ledger content was often:
  - `"Step completed with no AI text captured"`, or
  - stringified empty summary dict: `"{'first': '', 'last': ''}"`.
- Plan-assess prompt evidence then inherited the same unusable content and failed to mark progress.

### B) Loop did not converge after successful `ls`

- Repeated `ls` steps executed successfully, but plan-assess still reported:
  - `status=continue`
  - `goal_progress=none`
- This caused unnecessary replan/execute iterations for simple one-step goals.

### C) TUI step card missed tool activity rows

- Header showed aggregate count (`· 1 tools`), but no concrete tool row under the step card.
- This was most visible for task-level/subgraph tool IDs (`{step}:t{idx}:...`).

---

## Root Cause Analysis

### 1) Execute output summary fallback was structurally wrong

- `create_output_summary()` returns a dict payload (`first/last`), not plain prose.
- Fallback path in execute ledger used `str(outcome["output_summary"])`, which produced raw dict text.
- When output summary had both fields empty, this stringified into non-actionable evidence.

### 2) Subgraph tool text was excluded from execute output aggregation

- `_stream_and_collect()` aggregated output primarily from root act messages.
- Namespaced tool messages (`iter_namespaced_tool_messages`) were logged and counted, but not consistently merged into aggregated execute output text.
- For tool-only steps (common in this scenario), output summary then became empty or weak.

### 3) TUI routing had a gap when task binding was unresolved

- Subgraph tool rows were routed through namespace/task-scope binding.
- If binding could not be resolved quickly (or parent delegation row was absent/delayed), row ingestion could be buffered and effectively invisible on step card.
- Renderer improvements alone were insufficient without ingestion fallback.

### 4) Docker image rebuilds repeated expensive dependency installs

- The original local daemon Dockerfile copied full package trees before dependency install.
- Any source change invalidated dependency layers, forcing repeated `uv pip install` of third-party deps.

---

## Fixes Implemented

## 1) Ledger: normalize `output_summary` and avoid empty dict artifacts

### File
- `packages/soothe/src/soothe/foundation/loop/engine/executor.py`

### Changes
- Added `_outcome_summary_text()` to normalize `output_summary` payloads:
  - handles dict (`first`/`last`) and string cases.
  - returns empty string when both parts are empty.
  - prevents raw dict-string leakage into ledger/progress evidence.
- Updated execute-step ledger fallback and prior-progress evidence extraction to use normalized summary text.

Result: plan-assess evidence no longer receives `"{'first': '', 'last': ''}"` artifacts.

## 2) Execute aggregation: include namespaced subgraph tool output

### File
- `packages/soothe/src/soothe/foundation/loop/engine/executor.py`

### Changes
- In namespaced tool-message iteration path, append non-task subgraph tool text into execute output chunks (with existing tool/code output caps).
- This ensures tool-only subgraph executions produce meaningful `output_summary` and ledger evidence.

Result: execute-step AI ledger rows capture actual evidence for subgraph tools (e.g. directory listing text), enabling plan-assess convergence.

## 3) TUI: render subgraph tool activity even when routing bind is late/missing

### Files
- `packages/soothe-cli/src/soothe_cli/tui/widgets/messages.py`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`

### Changes
- Step-card activity panel:
  - added orphan subgraph row preview support so rows can still be shown without a resolved parent delegation row.
- Adapter ingestion:
  - added fallback subgraph ingestion path in `apply_tool_call_wire_update()` and message-stream tool-chunk path.
  - if `try_route_subgraph_tool()` cannot resolve scope/parent, row is best-effort attached by parsed step ID.

Result: step card shows concrete tool rows for subgraph tools instead of only aggregate count.

## 4) Docker build optimization (dependency layer caching)

### Files
- `packages/soothe-daemon/Dockerfile.local`
- `scripts/build_runtime_requirements.py`

### Changes
- Split install into two phases:
  1. metadata-only copy (`pyproject.toml`/`README` + `VERSION`) then install third-party runtime requirements.
  2. copy local package sources and install local packages with `--no-deps`.
- Introduced runtime requirement generator script from package metadata/extras.

Result: unchanged dependencies reuse cached layers; local source edits no longer trigger full dependency reinstall.

---

## Validation Evidence

## Unit tests

### Soothe core
- `packages/soothe/tests/unit/core/loop/engine/test_executor_parallel_ledger_ig374.py`
- Passed after adding summary normalization coverage and fallback behavior checks.

### Soothe CLI
- `packages/soothe-cli/tests/unit/ux/tui/test_step_card_task_activity.py`
- `packages/soothe-cli/tests/unit/runtime/test_step_tool_stats_ingest.py`
- Passed with new coverage for orphan subgraph row rendering and fallback ingestion.

## Runtime replay (local daemon)

- Rebuilt `soothed:local-slim`.
- Restarted compose daemon with local image and corrected workspace mount root.
- Re-ran `list dir of current workspace`.
- Verified latest checkpoint ledger:
  - execute-step AI row contains real listing/evidence text.
  - plan-assess reached `status=done`, `goal_progress=complete`.
- Verified step-card ingestion patch deployed via rebuild/restart.

## Docker caching

- Repeated `--target deps` build showed dependency layer cache hits when dependency metadata unchanged.

---

## Operational Notes

- If workspace mount root is incorrect, subgraph tools (`ls`, `run_command`) can fail with directory-not-found errors and reintroduce poor progress behavior unrelated to ledger serialization.
- Compose profile/image env alignment must point `soothed` to the rebuilt local image to validate fixes in runtime.

---

## Status

Completed.

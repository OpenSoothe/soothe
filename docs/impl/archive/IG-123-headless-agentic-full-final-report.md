# IG-123: Headless agentic final report (full body + overflow file)

## Goal

When the agentic loop finishes in headless CLI, users should see the **full model answer** on stdout when it is reasonably short. Long answers should show a **truncated preview** on stdout and persist the **full text** under the thread run directory, with an explicit path on stdout.

## Behavior

- Normalize `full_output` (strip leading Python list repr prefixes from tool dumps) as today.
- If normalized body is non-empty:
  - If `len(body) <= 8000`: stdout final message is the full body (preferred over `user_summary`).
  - If `len(body) > 8000`: write UTF-8 file under the same run root as `RunArtifactStore` (workspace `.soothe/runs/{thread_id}/` when sandboxed, else `$SOOTHE_HOME/runs/{thread_id}/`), unique name `final_report_<UTC>_<uuid>.md`; stdout shows a preview (first 4800 chars) plus the saved path.
- If normalized body is empty: fall back to `user_summary` (existing cap), then evidence summary as today.

## Files

- `src/soothe/core/runner/_runner_agentic.py` — compose final stdout + optional file write
- `tests/unit/test_runner_agentic_final_stdout.py` — updated expectations + overflow test

## Status

Completed.

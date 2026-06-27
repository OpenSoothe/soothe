# IG-520: Grep Tool Robustness — Ungate ag, gate the fallback, honor .gitignore

**IG**: 520
**Title**: Grep/ag Robustness — Invert the FD-exhaustion gate, honor .gitignore in the Python fallback
**Status**: Completed
**Created**: 2026-06-28
**Dependencies**: IG-510 (incremental grep batching), IG-517 (async filesystem I/O)

---

## Summary

Fix the recurring grep-tool timeouts observed in production logs by inverting a
mis-calibrated safety gate and making the Python fallback respect `.gitignore`.

Four compounding bugs caused **36 of 632** grep calls to time out at 30s in a recent
loop, with **215** more proactively disabled:

1. The ag-skip gate (`_MAX_FD_SAFE_FILE_COUNT = 200`) is calibrated against a mythical
   `ulimit 256` that does not match this host (`ulimit -Sn = 1,048,576`). It fires on
   every workspace-root search and disables the one path that works.
2. The Python fallback walks files ag would skip: it ignores `.gitignore`, so it scans
   `.claude/` (41,687 files incl. a 1.9 GB worktree clone) and `thirdparty/`. A 0.04 s
   ag search becomes a 97,299-file Python `open()`+`re.finditer` loop that cannot finish
   in 30 s.
3. Tool timeout (30 s) is shorter than the fallback's own internal budget (60 s), so
   the incremental-batching logic from IG-510 is dead code in practice.
4. `asyncio.to_thread` cannot cancel a sync `os.walk`; timed-out greps keep burning CPU
   after the tool has already reported failure.

## Design

### Change 1 — Ungate ag (`grep_search.py`)

Remove `_should_skip_ag_due_to_fd_limit` and the pre-flight call in `grep_with_ag`. ag
runs whenever available. The existing EMFILE (errno 24) recovery in `_run_ag_subprocess`
remains as the real fallback if FD exhaustion ever occurs.

### Change 2 — Gate the Python fallback by gitignored file count (`local.py`)

When ag is unavailable and the (gitignore-aware) file estimate exceeds
`_GREP_FALLBACK_FILE_LIMIT` (50,000), return a fast structured
`GrepResult(error="grep scope too large: ~N files under {path} (ag unavailable). …")`
instead of hanging. Converts a 30 s hang into a sub-second actionable error.

### Change 3 — Honor `.gitignore` in the fallback walk (`local.py`)

Replace the hardcoded `_GREP_IGNORE_DIRS` membership check with a `pathspec`-aware walk.
`pathspec>=0.12.0` is already a dependency. `_load_gitignore` walks up to the workspace
root accumulating `.gitignore` patterns; the compiled spec is cached on the instance.
`_GREP_IGNORE_DIRS` stays as a defense-in-depth floor (`.venv`, `node_modules`,
`__pycache__` always skipped even if a repo forgets to gitignore them). Falls back to
the hardcoded set if `pathspec` is missing or no `.gitignore` exists.

### Change 4 — Reconcile timeouts + make the walk cancellable (`local.py`)

- `_GREP_TOTAL_TIMEOUT_S` 60 → 25, `_GREP_BATCH_TIMEOUT_S` 5.0 → 2.0 — the fallback
  returns partial results **before** the 30 s tool timeout kills it.
- `agrep` wraps the call in `asyncio.wait_for` and passes a `threading.Event` cancel
  flag checked between files; on timeout the event is set so the background `os.walk`
  thread stops promptly instead of lingering.

### Change 5 — Disambiguate early-abort from genuine no-match (`local.py`)

When the walk stops early in `files_with_matches`/`count` mode, return a
`GrepResult(is_partial=True, continuation_token=..., error="Search stopped: {reason}")`
instead of `[]`/`"0"`. The agent can now tell "nothing here" from "I gave up" and resume.

## Files

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/foundation/core/filesystem/grep_search.py` | Remove `_MAX_FD_SAFE_FILE_COUNT` + `_should_skip_ag_due_to_fd_limit`; drop pre-flight call. |
| `packages/soothe/src/soothe/foundation/core/filesystem/local.py` | gitignore-aware `_collect_grep_files` + `_load_gitignore` cache; fallback file-count gate; lower timeouts; cooperative cancel in `agrep`; partial-result signal in simplified modes. |
| `packages/soothe/tests/core/filesystem/test_grep_search.py` | Rewrite large-directory test for gitignore path; add `.claude`/`thirdparty` skip, scope-too-large fast-fail, partial disambiguation, cooperative-cancel, ag-ungated tests. |
| `docs/impl/IG-520-grep-robustness.md` | This doc. |

## Verification

1. `make lint` — zero ruff errors.
2. `pytest packages/soothe/tests/core/filesystem/test_grep_search.py -q` — green.
3. `./scripts/verify_finally.sh` — passes before commit (CLAUDE.md rule 5).
4. Manual repro: workspace-root grep returns in <1 s via ag (was 30 s timeout); with ag
   forced off, root grep returns a structured scope-too-large error in <1 s (was hang).

## Out of scope

- Two-phase `ag -l` then `ag -n --column` content-mode dance (works, leave it).
- Replacing `pathspec` with `git ls-files` (rejected — non-git workspaces).
- Exposing thresholds as config (defer until requested; then sync
  `config/config.template.yml` + `config/develop/config.yml` per CLAUDE.md rule 2).

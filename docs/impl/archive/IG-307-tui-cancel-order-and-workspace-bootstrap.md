# IG-307 TUI Cancel Order and Workspace Bootstrap

## Context

Two TUI issues were reported:

1. After user interrupt, a delayed daemon cancellation message appears after the
   next user input, which is confusing.
2. TUI daemon sessions do not honor configured workspace paths consistently.

## Root Cause

- The daemon broadcasts a custom `soothe.error` cancellation event from
  `QueryEngine` during `CancelledError` handling, even though cancellation is
  already represented by status transitions and command acknowledgements. That
  extra event can arrive after the next prompt starts.
- `bootstrap_thread_session()` always sends `Path.cwd()` as thread workspace,
  and `run_textual_tui()` does not pass `config.workspace_dir` into the app,
  so daemon-thread workspace and TUI cwd can diverge from configured workspace.

## Implementation Plan

1. Remove redundant custom error broadcasts in user-cancel paths from
   `QueryEngine` (single-thread and multithread flows).
2. Add optional `workspace` argument to SDK bootstrap session helper and use it
   for `new_thread` / `resume_thread` RPC calls.
3. Thread TUI cwd into daemon session bootstrap and respect non-default
   `config.workspace_dir` in `run_textual_tui()`.
4. Add focused regression tests for workspace propagation in SDK bootstrap and
   TUI wrapper.

## Expected Outcome

- No stale "query cancelled in thread ..." message appears after the next query.
- TUI daemon thread bootstrap uses the intended workspace path when configured.

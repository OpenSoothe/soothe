# IG-637: Background log lifecycle hardening (phase 3)

## Goal

Make background logs useful immediately after `run_background` and mark termination in the log when `kill_process` runs.

## Scope

1. Write a synchronous header (timestamp + command) to the log before spawning the shell.
2. Append a termination footer from `kill_process` when `bg-{pid}.log` exists.
3. Wire `KillProcessTool` with the same log-dir resolution as `run_background`.
4. Unit tests + verify.

## Out of scope

Dedicated log-tail tool, log retention/cleanup policy, streaming sync stdout.

## Verification

- `./scripts/verify_finally.sh`

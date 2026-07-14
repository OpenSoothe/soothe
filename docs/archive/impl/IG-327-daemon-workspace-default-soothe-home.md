# IG-327: Daemon workspace default (`$SOOTHE_HOME/Workspace`)

## Goal

- Default agent filesystem root is `$SOOTHE_HOME/Workspace` (not the process cwd).
- `workspace_dir` in `SootheConfig` / config YAML is the configured default; legacy `"."` / empty coerces to the install workspace.
- `soothed start` / `restart` detached subprocess does not use `Path.cwd()` as its working directory.

## Changes

- `soothe.config.env.default_soothe_workspace_dir()`
- `SootheConfig.workspace_dir` default factory + after-validator for legacy `.` / empty
- `resolve_daemon_workspace`: env override, then resolved `workspace_dir` (with legacy coercion), mkdir, validate
- `daemon_main.py`: `subprocess.Popen(..., cwd=SOOTHE_HOME)`
- `query_engine.py`: fall back to `_daemon_workspace` instead of `Path.cwd()`
- Template YAML comment; `build_daemon_config` sets isolated `workspace_dir` for integration tests
- Unit test updates

## Verification

`./scripts/verify_finally.sh`

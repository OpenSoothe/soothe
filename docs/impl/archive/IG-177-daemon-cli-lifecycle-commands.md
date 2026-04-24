# IG-177 Daemon CLI Lifecycle Commands

## Goal

Replace placeholder `soothe-daemon` command handlers with working lifecycle behavior so users can start, stop, restart, query status, and run doctor checks from the daemon CLI.

## Scope

- Update `packages/soothe/src/soothe/cli/daemon_main.py`.
- Wire commands to existing daemon runtime helpers in `soothe.daemon.server`.
- Keep foreground mode blocking and background mode detached.
- Provide actionable CLI messages and proper non-zero exits on failure.

## Plan

1. Load config from `--config` when provided.
2. Implement `start`:
   - Validate not already running.
   - Foreground: run daemon in current process.
   - Background: spawn detached subprocess via `python -m soothe.daemon`.
3. Implement `stop` via `SootheDaemon.stop_running()`.
4. Implement `status` via `SootheDaemon.is_running()` and `SootheDaemon.find_pid()`.
5. Implement `restart` as `stop` then `start`.
6. Implement `doctor` using daemon health checker and text formatter.

## Validation

- Run focused unit tests for the new daemon CLI module.
- Manually verify `soothe-daemon start/status/stop` output behavior.

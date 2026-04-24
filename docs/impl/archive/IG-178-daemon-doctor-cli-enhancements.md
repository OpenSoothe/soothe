# IG-178 Daemon Doctor CLI Enhancements

## Goal

Enhance `soothe-daemon doctor` to support practical operational workflows:

- Selective category execution.
- Multiple output formats.
- Optional report export to file.
- Config file selection.
- Exit-code thresholds suitable for CI checks.

## Scope

- Update `packages/soothe/src/soothe/cli/daemon_main.py`.
- Add unit tests in `tests/unit/test_daemon_main_cli.py`.

## Planned Behavior

`soothe-daemon doctor` adds options:

- `--config/-c`: use a specific config file.
- `--category`: repeatable; run only listed categories.
- `--exclude`: repeatable; skip listed categories.
- `--format`: `text`, `json`, `markdown`.
- `--output/-o`: write report to a file.
- `--no-color`: disable ANSI in text output.
- `--fail-on`: `never`, `warning`, `error` to control command exit code.

## Validation

- Run focused unit tests for daemon CLI:
  - `uv run pytest tests/unit/test_daemon_main_cli.py -q`
- Verify no lints on touched files.

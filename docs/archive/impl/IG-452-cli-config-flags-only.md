# IG-452: Remove CLI file-based config; use global flags only

## Goal

Drop `cli_config.yml` / `config/cli_config.template.yml` for the `soothe` CLI client. All client settings are supplied via global Typer flags on the root `soothe` command. No backward compatibility for file-based CLI config or ignored `--config` paths.

## What changed

### Removed

- `config/cli_config.template.yml`
- `CLIConfig.from_config_file()`, `CLI_CONFIG_FILE`, YAML parsing
- Compatibility shims on `CLIConfig` (`daemon`, `logging`, `home` properties)
- `--config` on `soothe autopilot run`
- `config_path` on `run_impl` and file-cache logic in `load_config()`

### Added — global CLI flags (root callback)

| Flag | Default | Purpose |
|------|---------|---------|
| `--daemon-host` | `127.0.0.1` | Daemon WebSocket host |
| `--daemon-port` | `8765` | Daemon WebSocket port |
| `--log-level` | `INFO` | CLI log file level (`SOOTHE_LOG_LEVEL` still overrides) |
| `--render-markdown` / `--no-render-markdown` | enabled | TUI Markdown rendering |
| `--soothe-home` | `~/.soothe` | Soothe home directory |
| `--streaming` / `--no-streaming` | daemon default | Output streaming override |
| `--streaming-mode` | daemon default | `streaming` or `batch` |

Subcommands inherit flags, e.g. `soothe --daemon-port 9000 loop list`.

### Runtime wiring

- Root `main.py` callback builds `CLIConfig` and calls `set_runtime_config()`
- `load_config()` reads from a `ContextVar` (or returns defaults when unset, e.g. direct test calls)
- `reset_runtime_config()` for tests

## Files touched

**Deleted**

- `config/cli_config.template.yml`

**CLI**

- `packages/soothe-cli/src/soothe_cli/cli/main.py`
- `packages/soothe-cli/src/soothe_cli/cli/commands/run_cmd.py`
- `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py`
- `packages/soothe-cli/src/soothe_cli/config/cli_config.py`
- `packages/soothe-cli/src/soothe_cli/config/loader.py`
- `packages/soothe-cli/src/soothe_cli/config/__init__.py`
- `packages/soothe-cli/src/soothe_cli/tui/model_config.py`

**Tests**

- `packages/soothe-cli/tests/unit/config/test_cli_config_loader.py` (new)
- `packages/soothe-cli/tests/unit/ux/cli/test_cli_positional_prompt.py`

**Docs / SDK**

- `packages/soothe-cli/README.md`
- `docs/howto_debug.md`
- `packages/soothe-sdk/src/soothe_sdk/utils/logging.py` (docstrings only)

## Not in scope

- Daemon config (`daemon.yml`) and agent config (`config.yml`) — unchanged
- TUI theme prefs in `config.yml` (`ui.theme`) — unchanged
- `SOOTHE_LOG_LEVEL` env precedence — unchanged

## Verification

```bash
cd packages/soothe-cli && uv run pytest tests/unit/config/test_cli_config_loader.py tests/unit/ux/cli/ -q
```

## Status

Completed.

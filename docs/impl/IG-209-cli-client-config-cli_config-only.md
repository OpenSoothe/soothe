# IG-209: CLI client config — `cli_config.yml` only

## Goal

- `~/.soothe/config/cli_config.yml` (respecting `SOOTHE_HOME`) is the **only** file used for soothe-cli client settings (including progress verbosity defaulting to `normal`).
- Do not load client settings from `~/.soothe/config.yml` or other YAML paths.
- Remove the `--verbosity` / `-v` CLI flag so verbosity is not overridden outside that file.

## Config Structure

CLI client config uses **flat top-level `verbosity`** (simpler than daemon's nested structure):

```yaml
verbosity: normal  # quiet, normal, detailed, debug

websocket:
  host: "127.0.0.1"
  port: 8765
```

CLI client is lightweight and doesn't need nested `logging:` structure like daemon config.

## Changes

- `CLI_CONFIG_FILE` constant and `load_config()` always read this path; a warning is logged if `--config` is passed (legacy) but ignored for client settings.
- `run_impl` no longer accepts verbosity from the command line.
- Config loader reads `data.get("verbosity", "normal")` from top-level (flat structure).

## Related TUI fix (tool cards)

`execute_task_textual` reads progress verbosity via `load_config()` (not `SootheApp._daemon_config`). When a `ToolMessage` arrives without a prior mounted `ToolCallMessage` (common on daemon/WebSocket paths), the TUI now mounts an orphan tool card and applies the result.

## Verification

Run `./scripts/verify_finally.sh`.

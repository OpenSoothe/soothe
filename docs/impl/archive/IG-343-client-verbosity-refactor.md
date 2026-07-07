# IG-343: Client verbosity refactor (CLI + TUI)

## Status

Implemented.

## Summary

- Removed user-configurable **client** verbosity from `CLIConfig` / `cli_config.yml`. Progress display level is no longer a client setting.
- **TUI**: Fixed internal behavior to previous **`normal`** semantics (tools, `StreamDisplayPipeline`, tier filtering).
- **Headless CLI**: Stdout only **RFC-614 loop-tagged** main-graph assistant text (`LOOP_ASSISTANT_OUTPUT_PHASES`). No progress, tools, or plan lines on stderr (errors only).
- **Logging**: `SOOTHE_LOG_LEVEL` and optional `logging_level` in client YAML; default **INFO** when unset (no verbosity-derived mapping).

## Breaking changes

- `verbosity` / `ui.verbosity` in `~/.soothe/config/cli_config.yml` are no longer read — safe to delete from local files.
- **`--format jsonl`**: Removed; headless output is plain text (loop-tagged assistant output only) per clean-final contract.

## Files touched

- `packages/soothe-cli/` — config, TUI, headless execution, `EventProcessor`, new headless renderer.
- `packages/soothe-sdk/` — `resolve_cli_log_level` signature.
- Tests updated accordingly.

## Risk: unphased main assistant text in headless mode

Headless suppresses main-graph assistant messages **without** a recognized loop `phase`. If any runtime path still emits user-visible answers without tagging, headless would show nothing — verify daemon/agent paths attach phases for all user-facing main output.

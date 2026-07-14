# IG-311: AgentLoop Default Output Mode to Batch

## Context

Current defaults favor streaming output for AgentLoop-related responses. This can
cause fragmented rendering in clients and inconsistent expectation when users
prefer stable final output by default.

## Goal

Set the default output behavior to batch mode (not streaming) for AgentLoop
output, while preserving explicit user overrides.

## Scope

- `packages/soothe/src/soothe/config/models.py`
- `packages/soothe/src/soothe/config/config.yml`
- `config/config.dev.yml`
- `packages/soothe-cli/src/soothe_cli/config/cli_config.py`
- `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
- `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py`

## Planned changes

- Change daemon config default `output_streaming.mode` from `streaming` to
  `batch`.
- Change CLI-side `final_output_mode` defaults/fallbacks to `batch`.
- Preserve existing `streaming`/`batch` validation and command-line overrides.

## Non-goals

- No protocol schema changes.
- No behavioral changes when users explicitly set streaming mode.
- No changes to model token streaming internals.

## Verification

- Run targeted unit tests for CLI/TUI event processor behavior.

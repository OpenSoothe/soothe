# IG-313: AgentLoop Output Streaming Default and Control

## Context

AgentLoop output streaming should be controlled by `agentic.output_streaming`.
Recent changes shifted multiple client defaults to batch mode, which diverges from
the desired default behavior and makes effective streaming policy harder to reason about.

## Goal

- Keep streaming as the default behavior.
- Ensure AgentLoop streaming/batch behavior is governed by `agentic.output_streaming`.

## Scope

- `packages/soothe/src/soothe/config/models.py`
- `packages/soothe/src/soothe/config/config.yml`
- `config/config.dev.yml`
- `packages/soothe-cli/src/soothe_cli/config/cli_config.py`
- `packages/soothe-cli/src/soothe_cli/shared/event_processor.py`
- `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`
- `packages/soothe-cli/src/soothe_cli/cli/execution/daemon.py`
- `packages/soothe/src/soothe/core/runner/_runner_shared.py` (verification-only)

## Planned changes

- Restore default output mode/fallbacks to streaming in CLI-facing settings.
- Restore `agentic.output_streaming` default to `true` in config models/templates.
- Keep runner-side stream wrapping gated by `config.agentic.output_streaming`.

## Non-goals

- No protocol schema changes.
- No markdown post-processing redesign.

## Verification

- Run targeted unit tests for CLI event processing and config defaults.

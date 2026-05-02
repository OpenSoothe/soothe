# IG-360: Compact logger module names in log lines

## Goal

Abbreviate dotted logger names for output: use the first letter of each segment except the last two, which stay full (e.g. `soothe.cognition.agent_loop.state.state_manager` → `s.c.a.state.state_manager`).

## Scope

- `soothe_sdk.utils.logging`: `abbreviate_logger_name()`, `ShortLevelFormatter` (`%(name)s`)
- Unit tests in `packages/soothe-sdk/tests/unit/utils/`

## Status

Implemented.

# IG-180 Unit Test Reorganization and WebSocket Integration Coverage

## Goal

Align test layout with package boundaries and strengthen daemon WebSocket integration coverage.

## Scope

- Move all daemon package unit tests from root `tests/unit/` to package-local `packages/soothe/tests/unit/`.
- Group moved tests by corresponding module domains (`daemon`, `core`, `cognition`, `tools`, `backends`, `ux`, etc.).
- Extend WebSocket integration coverage for:
  - daemon RPCs (`daemon_status`, `config_get`, `daemon_shutdown`),
  - CORS allow/deny behavior with explicit Origin headers,
  - heartbeat emission while daemon is in running-query state,
  - cross-transport thread synchronization between WebSocket and Unix transports.

## Key Changes

- Reorganized 100+ unit test files into package-local `packages/soothe/tests/unit/` subdirectories.
- Added new WebSocket integration tests in `tests/integration/test_daemon_websocket_protocol.py`.
- Added cross-transport synchronization test in `tests/integration/test_daemon_multi_transport.py`.
- Fixed daemon RPC status implementation to report WebSocket liveness via transport manager state.

## Validation

- Targeted unit and integration pytest runs for moved/added tests.
- Full repository verification with `./scripts/verify_finally.sh`.

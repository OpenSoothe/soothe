# Package Boundaries (MUST)

> Soothe is a **one-way dependency DAG**. Place code in the correct **monorepo-owned** package. **Never reverse an arrow.** Enforcement: `scripts/check_module_import_boundaries.sh` (wired into `./scripts/verify_finally.sh`).

**Owned**: `soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`, `soothe-sdk`. **Submodules** (`client/*`): consumed as code — do **not** format/lint/test/release them here. **PyPI-only**: `soothe-nano`, `soothe-deepagents` (maintain/release in their own repos).

> `soothe-sdk` keeps its own `VERSION` file (1.x line) because `soothe-nano` (PyPI) depends on `soothe-sdk>=1.0.7`. All other owned packages use the root `VERSION` file (0.x line).

## Placement (where new code goes)

| Concern | Package |
|---------|---------|
| Shared events, wire, display, plugin contracts, protocols | `soothe-sdk` |
| Coding CoreAgent, skills/MCP/backends in-proc | `soothe-nano` (PyPI) |
| StrangeLoop, Context Engine, identity, host runner | `soothe` |
| Autopilot (scheduling, dispatch, monitor, rails, verify, notify) | `soothe-autopilot` |
| Process lifecycle, channels, HTTP/WS server, admin IO, cron | `soothe-daemon` |
| Human CLI / TUI | `soothe-cli` |
| Language WS clients | `client/*` (submodules) |

## Import allow / deny (MUST) — this table IS the DAG

| Package | May import | Must NOT import |
|---------|------------|-----------------|
| `soothe-sdk` | `pydantic`, `langchain-core` only | `soothe`, `soothe_autopilot`, `soothe_daemon`, `soothe_cli` |
| `soothe` | `soothe-sdk`, `soothe-nano`, `soothe-deepagents` | `soothe_autopilot`, `soothe_daemon`, `soothe_cli` |
| `soothe-autopilot` | `soothe`, `soothe-nano`, `soothe-sdk` | `soothe_daemon`, `soothe_cli`, `soothe_client` |
| `soothe-daemon` | `soothe`, `soothe-autopilot`, `soothe-nano`, `soothe-sdk` | `soothe_cli`, `soothe_client` |
| `soothe-cli` | `soothe-sdk`, `soothe-client-python` | `soothe`, `soothe_daemon` (use WebSocket, not Python imports) |

## Hard bans (owned packages)
1. **CLI sits above the daemon** — `soothe_cli` must not import daemon/host; communicate via wire contracts in sdk + `soothe-client-python`.
2. **Daemon does not depend on the WS client** — `soothe_daemon` must not import `soothe_client` in runtime source; admin RPCs use `soothe_sdk.wire` (tests may use the client via the `dev` extra).
3. **Private nano middleware is closed** — owned packages must not import `soothe_nano.middleware._*`.

Host packages (`soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`, `soothe-sdk`) MAY reference internal design doc identifiers in comments.

## API Exposure (Minimum-Exposure) (MUST)
- A parent `__init__.py` re-exports only what users are expected to import. For processors, that is exactly the operator class(es) — nothing else.
- Do not re-export type schemas, builders, or helpers through parent packages when direct module imports suffice.
- Never list private `_`-prefixed names in `__all__`.

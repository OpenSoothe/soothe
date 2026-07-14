# IG-414: Soothe Daemon Package Split + Three-Config Refactor

**Status**: Completed
**Created**: 2026-05-13
**Last checkpoint**: 2026-05-13 22:30 UTC+8

## Goal

Carve the daemon server, daemon CLI, daemon-mode runners, and daemon-only tests out of `packages/soothe` into a new `packages/soothe-daemon` workspace package exposing the `soothe_daemon` import namespace. Split the previously monolithic `SootheConfig` into two configs—`SootheConfig` (in-proc, `~/.soothe/config/config.yml`) and `SootheDaemonConfig` (daemon, `~/.soothe/config/daemon_config.yml`)—and leave the existing `CLIConfig` (CLI client settings, `~/.soothe/config/cli_config.yml`) in place.

`packages/soothe` becomes a pure in-proc agent core consumable as a library by [examples/inproc_soothe_agent.py](../../examples/inproc_soothe_agent.py) and downstream projects, with no FastAPI/uvicorn/websockets server, no `soothed` CLI, and no daemon-side fields on `SootheConfig`.

## Scope

### `packages/soothe` (in-proc only)

- Remove `SootheConfig.daemon` field; delete `soothe/config/daemon_config.py`.
- Remove `apply_env_overrides()` from `soothe/config/env.py` (moves to `soothe_daemon.config.env`).
- Move `soothe/core/runner/{factory,pool_runner,ray_runner,ray_actor}.py` to `soothe_daemon/runner/`.
- Keep `SootheRunner`, `LocalLoopRunner`, `LoopRunnerProtocol` in `soothe`.
- Delete `soothe/daemon/**`, `soothe/cli/daemon_main.py`.
- Drop deps: `fastapi`, `uvicorn[standard]`, `psutil`. Drop `[project.scripts] soothed`. Add `daemon` extra.

### `packages/soothe-daemon` (new)

```
src/soothe_daemon/
├── __init__.py, __main__.py
├── config/
│   ├── __init__.py
│   ├── settings.py        # SootheDaemonConfig (BaseSettings, env_prefix=SOOTHE_DAEMON_)
│   ├── models.py          # WebSocketConfig, HttpRestConfig, TransportConfig, WorkerPoolConfig, DistributedConfig, RayClusterConfig
│   └── env.py             # apply_env_overrides (SOOTHE_DISTRIBUTED)
├── runner/                # factory, pool_runner, ray_runner, ray_actor
├── server.py, entrypoint.py, message_router.py, query_engine.py, ...
├── transports/, health/
└── cli/daemon_main.py     # `soothed` console script
```

`SootheDaemonConfig` carries `transports`, `worker_pool`, `distributed`, queue/dispatch limits, timeouts, event-size stats, plus `soothe_config_path` pointing to the agent config the daemon loads.

### `packages/soothe-cli`

- `CLIConfig` and `cli_config.yml` are unchanged. The CLI client never
  depended on `SootheConfig.daemon`; only the WebSocket endpoint settings it
  already reads from `cli_config.yml`.
- Replace `python -m soothe.daemon` subprocess argv with `python -m soothe_daemon`.

### Config YAML

`~/.soothe/config/` now hosts three independent files:
- `config.yml` — `SootheConfig` (in-proc agent, unchanged location)
- `daemon_config.yml` — `SootheDaemonConfig` (new)
- `cli_config.yml` — CLI client settings (unchanged location and class)

Repo templates / dev samples mirror this:
  - `config/config.template.yml`, `config/config.dev.yml` (already exist)
  - `config/daemon_config.template.yml` (new) — daemon template only;
    daemon-side dev overrides live in repo `config/config.dev.yml` siblings
    via env / explicit `--config` rather than a tracked dev file
  - `config/cli_config.template.yml` (already exists) — CLI template only

## Hard cut, no compat

No shims for: `soothe.daemon`, `soothe.cli.daemon_main`, `soothe.core.runner.factory`/`pool_runner`/`ray_runner`/`ray_actor`, `soothe.config.daemon_config`, or `SootheConfig.daemon`. All callers use the new names directly.

## Files touched (high level)

- 38 source files moved from `soothe/daemon/**` to `soothe_daemon/**`.
- 4 runner files moved from `soothe/core/runner/` to `soothe_daemon/runner/`.
- 1 daemon CLI file moved from `soothe/cli/daemon_main.py` to `soothe_daemon/cli/daemon_main.py`.
- 1 config file (`daemon_config.py`) moved to `soothe_daemon/config/models.py`.
- 33+ daemon unit tests + 10 daemon integration tests + 3 e2e core tests + 2 runner tests moved.
- All consumer imports rewritten (single audit grep returns zero hits outside `docs/impl/IG-*`).

## Done when

- `python -c "from soothe.config import SootheConfig; assert not hasattr(SootheConfig(), 'daemon')"` passes.
- `python -c "from soothe_daemon.config import SootheDaemonConfig; from soothe_daemon.server import SootheDaemon"` passes.
- `python -m soothe_daemon --help` runs.
- Audit grep returns zero hits outside `docs/impl/IG-*`:
  ```
  rg 'from soothe\.daemon|import soothe\.daemon|soothe\.cli\.daemon_main|python -m soothe\.daemon|SootheConfig\.daemon\b|config\.daemon\.|self\._config\.daemon\.|cfg\.daemon\.|soothe\.config\.daemon_config|soothe\.core\.runner\.(factory|pool_runner|ray_runner|ray_actor)'
  ```
- One-way dependency guard (added to `scripts/verify_finally.sh`):
  `soothe` distribution metadata must NOT list `soothe-daemon` as a dependency
  (the daemon depends on the agent core, never the reverse).
- `./scripts/verify_finally.sh` passes.

---

## Progress checkpoint (2026-05-13 21:44 UTC+8)

### Done

- **Scaffold**: `packages/soothe-daemon/{pyproject.toml,README.md,Dockerfile}`
  + `src/soothe_daemon/{config,runner,cli,health,transports,...}/` + tests
  layout; `soothed` console script wired to
  `soothe_daemon.cli.daemon_main:app`.
- **Config split (code)**:
  - `SootheConfig.daemon` field removed; `soothe/config/daemon_config.py` and
    `soothe/config/env.py::apply_env_overrides` deleted from soothe core.
  - `SootheDaemonConfig` (BaseSettings, prefix `SOOTHE_DAEMON_`) lives at
    `soothe_daemon.config.settings`. Fields: `transports`, all
    concurrency / safety knobs, `event_size_stats_*`, `distributed`,
    `worker_pool`, `soothe_config_path`. Loaders:
    `from_yaml_file`, `from_default_yaml`, `load_soothe_config`.
  - `soothe_daemon.config.models` holds nested schemas
    (`WebSocketConfig`, `HttpRestConfig`, `TransportConfig`,
    `WorkerPoolConfig`, `DistributedConfig`, `RayClusterConfig`); the
    old top-level `DaemonConfig` class is gone.
  - `soothe_daemon.config.env::apply_env_overrides(SootheDaemonConfig)`
    handles `SOOTHE_DISTRIBUTED`.
  - `CLIConfig` / `cli_config.yml` left untouched (per user direction).
- **Source moves (`git mv`)**:
  - `soothe/daemon/**` → `soothe_daemon/**`.
  - `soothe/core/runner/{factory,pool_runner,ray_runner,ray_actor}.py`
    → `soothe_daemon/runner/`.
  - `soothe/cli/daemon_main.py` → `soothe_daemon/cli/daemon_main.py`.
  - `soothe/config/daemon_config.py` → `soothe_daemon/config/models.py`.
  - Daemon-only tests (`tests/unit/{daemon,cli}`,
    `tests/integration/{daemon,runner,core}`) moved to
    `packages/soothe-daemon/tests/`.
  - `Dockerfile` moved from `packages/soothe/` to
    `packages/soothe-daemon/`; `.github/workflows/docker.yml` and
    Dockerfile internal paths updated; daemon now also installed via the
    workspace-stub layer + `uv pip install … ./packages/soothe-daemon`.
- **Wiring through both configs**:
  - `SootheDaemon.__init__(config, daemon_config=...)`; all
    `self._config.daemon.X` accesses replaced with `self._daemon_config.X`.
    Static helpers (`is_running`, `find_pid`, `stop_running`) now read
    `SootheDaemonConfig()` directly.
  - `LoopRunnerFactory(daemon_config, agent_config)` signature; server
    passes both. `PoolLoopRunner`, `WorkerPool` already daemon-config-aware.
  - `query_engine.QueryEngine` reads timeouts from `d._daemon_config`.
  - `HealthChecker(config, daemon_config=…)` and
    `health/checks/daemon_check.py` switched to `SootheDaemonConfig | None`;
    `config.daemon.X` → `config.X` everywhere in the file.
  - `entrypoint.run_daemon(config, daemon_config=..., detached=...)`
    + `__main__`-level argv: `--config` is the daemon config path,
    `--soothe-config` overrides the agent config; daemon config supplies
    `load_soothe_config()` by default.
  - `cli/daemon_main.py` `_load_daemon_config()` helper; `start`,
    `restart`, `doctor`, `stop` all flow through it.
- **Import rewrites**: bulk script removed (`_rewrite_imports.py` deleted).
  Stale string `python -m soothe.daemon` in
  `soothe-cli/.../headless.py` corrected to `soothe_daemon`. Comment in
  `soothe_daemon/server.py` ("running soothe.daemon module") refreshed.
- **YAML templates**:
  - `config/config.template.yml` and `config/config.dev.yml`: `daemon:`
    block removed; comment points to daemon template.
  - `config/config.integration-explore.yml`: same edit.
  - `config/daemon_config.template.yml` added (full reference matching
    `SootheDaemonConfig` defaults).
  - `config/cli_config.dev.yml` and `config/daemon_config.dev.yml`
    deleted (user direction: keep template-only). `cli_config.template.yml`
    creation pending — see resumption checklist.
- **Boundary script**: `scripts/check_module_import_boundaries.sh`
  rewritten for the monorepo: blocks
  `soothe → soothe_{daemon,cli}`,
  `soothe-daemon → soothe_cli`,
  `soothe-sdk → any soothe*`.
- **`verify_finally.sh`**: rule 3 already enforces "soothe must not depend
  on soothe-daemon" (source imports + `pyproject.toml` line). Boundary
  script invocation kept.
- **Doc nudges**: `packages/soothe/src/soothe/core/README.md` layer
  diagram and "downstream consumers" updated to `soothe_daemon` /
  `soothe_cli` namespaces.

### Outstanding work / resumption checklist

#### 1. `config/cli_config.template.yml` (id: cli-template)

File does **not** exist yet (Write tool interrupted mid-edit).
Create with these defaults — must round-trip through
`CLIConfig.from_config_file()` in
`packages/soothe-cli/src/soothe_cli/config/cli_config.py`:

```yaml
# Soothe CLI client configuration template (loaded as `CLIConfig`).
# Place at `~/.soothe/config/cli_config.yml` to override CLI defaults.
logging_level: INFO   # Python level for ~/.soothe/logs/cli.log; SOOTHE_LOG_LEVEL overrides.
daemon:
  transports:
    websocket:
      host: "127.0.0.1"   # must match daemon_config.yml transports.websocket.host
      port: 8765          # must match daemon_config.yml transports.websocket.port
```

#### 2. Prune empty test dirs (id: stale-pycache)

Only `__pycache__` left after `git mv`:
```bash
rm -rf packages/soothe/tests/unit/daemon \
       packages/soothe/tests/unit/cli \
       packages/soothe/tests/integration/daemon
```

#### 3. Daemon test-import rewrites (id: move-tests)

Files still hitting old names (re-grep before editing):
```bash
rg -l 'soothe\.core\.runner\.(factory|pool_runner|ray_runner|ray_actor)|soothe\.config\.daemon_config|\.daemon\.(max_concurrent|worker_pool|distributed|transports|max_input)' packages/soothe-daemon/tests
```
Known offenders:
- `packages/soothe-daemon/tests/unit/runner/test_loop_runner_factory.py`
- `packages/soothe-daemon/tests/unit/runner/test_pool_runner.py`
- `packages/soothe-daemon/tests/integration/runner/test_ray_runner_cluster.py`
- `packages/soothe-daemon/tests/integration/daemon/test_load_performance.py`

Rewrite mappings:
| Before | After |
|---|---|
| `from soothe.core.runner.factory import LoopRunnerFactory` | `from soothe_daemon.runner.factory import LoopRunnerFactory` |
| `from soothe.core.runner.pool_runner import …` | `from soothe_daemon.runner.pool_runner import …` |
| `from soothe.core.runner.ray_runner import RayLoopRunner` | `from soothe_daemon.runner.ray_runner import RayLoopRunner` |
| `from soothe.core.runner.ray_actor import …` | `from soothe_daemon.runner.ray_actor import …` |
| `from soothe.config.daemon_config import DaemonConfig` | `from soothe_daemon.config import SootheDaemonConfig` |
| `from soothe.config.daemon_config import WorkerPoolConfig` | `from soothe_daemon.config.models import WorkerPoolConfig` |
| `config.daemon.worker_pool` / `config.daemon.transports` / `config.daemon.max_concurrent_*` | use a separate `daemon_config.worker_pool` / `.transports` / `.max_concurrent_*` (instantiate `SootheDaemonConfig()` in fixtures) |
| `LoopRunnerFactory(config)` (single arg) | `LoopRunnerFactory(daemon_config, agent_config)` |

Also: split daemon-only helpers out of
`packages/soothe-daemon/tests/integration/conftest.py` if any leftover
helpers reach back into `soothe.daemon.*` paths (re-grep that file first).

#### 4. `pyproject.toml` + `uv.lock` audit (id: pyproject)

`packages/soothe/pyproject.toml`:
- Remove deps: `fastapi`, `uvicorn[standard]`, `psutil`, `aiohttp` (used
  only by daemon health-checks now), `websockets` (daemon transport).
- Remove `[project.scripts] soothed = …`.
- Add `[project.optional-dependencies] daemon = ["soothe-daemon"]` so
  `pip install 'soothe[daemon]'` still works as a meta-extra. Verify
  `verify_finally.sh` rule 3 (no `^[[:space:]]*"soothe-daemon"` in core
  `dependencies` block) still passes.

`packages/soothe-daemon/pyproject.toml`:
- Confirm `dependencies` keeps `soothe`, `soothe-sdk` (workspace),
  `fastapi`, `uvicorn[standard]`, `websockets`, `psutil`, `aiohttp`,
  `pydantic-settings`, `pyyaml`, `requests`, `typer`, `dotenv`.
- Confirm `[project.scripts] soothed = "soothe_daemon.cli.daemon_main:app"`.
- Confirm `[tool.uv.sources]` lists `soothe = { workspace = true }`,
  `soothe-sdk = { workspace = true }`.

Workspace root `pyproject.toml`:
- Confirm `[tool.uv.workspace] members` includes `packages/soothe-daemon`.

Then:
```bash
uv sync --all-extras
git add uv.lock pyproject.toml packages/*/pyproject.toml
```

#### 5. Doc sweep (id: docker-docs)

- `CLAUDE.md`:
  - Layer-stack diagram and "soothe Package (Daemon Server)" section
    must split into `soothe` (in-proc) vs `soothe-daemon`.
  - Critical Rule #2 ("MUST Keep Config Files Synchronized"): expand to
    cover `config.template.yml`, `daemon_config.template.yml`,
    `cli_config.template.yml` (no `*.dev.yml` for daemon/cli).
  - "Adding a New …" sections: `python -m soothe.daemon` →
    `python -m soothe_daemon`.
- `packages/soothe-daemon/README.md`: re-read after this checkpoint;
  confirm config snippet shows `config.yml` + `daemon_config.yml`.
- `docs/user_guide.md`, `docs/howto_debug.md`, `docs/quickstart*.md`:
  replace any `soothe.daemon` / `SootheConfig.daemon` /
  `python -m soothe.daemon` references.
- `docs/specs/RFC-400-daemon-communication.md` (and adjacent RFCs that
  cite `soothe.daemon` modules) — update qualified module names.

#### 6. Verification (id: verify)

```bash
# Workspace sync (root + each pkg)
uv sync --all-extras

# Import smoke checks
uv run python -c "from soothe.config import SootheConfig; assert not hasattr(SootheConfig(), 'daemon')"
uv run python -c "from soothe_daemon.config import SootheDaemonConfig; from soothe_daemon.server import SootheDaemon"
uv run python -m soothe_daemon --help

# Audit grep (must return zero hits outside docs/impl/IG-*)
rg 'from soothe\.daemon|import soothe\.daemon|soothe\.cli\.daemon_main|python -m soothe\.daemon|SootheConfig\.daemon\b|config\.daemon\.|self\._config\.daemon\.|cfg\.daemon\.|soothe\.config\.daemon_config|soothe\.core\.runner\.(factory|pool_runner|ray_runner|ray_actor)'

# Boundary + dep-guard + format + lint + tests
./scripts/check_module_import_boundaries.sh
./scripts/verify_finally.sh
```

If `verify_finally.sh` reports a `soothe-daemon` line in
`packages/soothe/pyproject.toml` `dependencies`, move it to
`[project.optional-dependencies] daemon`.

### Decisions captured for future me

- `CLIConfig` and `cli_config.yml` are **unchanged** — do not rename to
  `SootheCliConfig` / `soothe-cli.yml`.
- Repo tracks **template-only** YAML for daemon and CLI; only the agent
  core retains a `config.dev.yml`. `config/cli_config.dev.yml` and
  `config/daemon_config.dev.yml` were deleted on purpose.
- The Dockerfile is **owned by `soothe-daemon`** (it is the daemon
  image). CI: `.github/workflows/docker.yml` builds
  `packages/soothe-daemon/Dockerfile`.
- `soothed --config` means **daemon** config; agent config is reached
  via `SootheDaemonConfig.soothe_config_path` or the explicit
  `--soothe-config` override.
- `LoopRunnerFactory.__init__(daemon_config, agent_config)` —
  daemon-config first; this ordering was chosen so the factory can be
  constructed without an agent config in tests that only exercise
  pool/ray selection logic.

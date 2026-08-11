# Soothe Module Boundaries & Slice Ownership

Canonical architecture view: [`module_boundaries.mmd`](module_boundaries.mmd)

Generated from AGENTS.md §7b (Package Boundaries) and §10 (Unified Persistence
Backend). Reflects the one-way dependency DAG enforced by
`scripts/check_module_import_boundaries.sh` (wired into
`./scripts/verify_finally.sh`).

## Monorepo-owned packages (3)

| Package | PyPI? | Role |
|---------|-------|------|
| `soothe` | no — owned | Host: StrangeLoop, Autopilot, Context Engine, cron, identity, runner |
| `soothe-daemon` | no — owned | `soothed` process: HTTP/WS server, admin RPC, channels, lifecycle |
| `soothe-cli` | no — owned | Typer CLI + Textual TUI; talks to daemon over WebSocket |

## PyPI dependencies (consumed, not owned here)

| Package | Role |
|---------|------|
| `soothe-sdk` | Shared contracts: events, wire, display, plugin protocols (leaf) |
| `soothe-nano` | Coding CoreAgent, in-proc skills/MCP/backends |
| `soothe-deepagents` | deepagents fork, MemoryMiddleware (leaf) |
| `soothe-client-python` | WebSocket transport — runtime dep of CLI; dev/test-only in daemon |

## Dependency DAG (allowed direction only)

```text
soothe-sdk            ← shared contracts (PyPI; leaf)
soothe-deepagents     ← deepagents fork (PyPI; leaf)
        ↓
soothe-nano           ← Coding CoreAgent (PyPI)
        ↓
soothe                ← host: StrangeLoop, Autopilot, CE, cron, runner   ← OWNED
        ↓
soothe-daemon         ← soothed process                                 ← OWNED
        ↑
soothe-cli            ← Typer + Textual TUI                             ← OWNED
```

## Import allow / deny (monorepo-owned packages)

| Package | May import | Must NOT import |
|---------|------------|-----------------|
| `soothe` | `soothe-sdk`, `soothe-nano`, `soothe-deepagents` | `soothe_daemon`, `soothe_cli` |
| `soothe-daemon` | `soothe`, `soothe-nano`, `soothe-sdk` | `soothe_cli`, `soothe_client` (runtime) |
| `soothe-cli` | `soothe-sdk`, `soothe-client-python` | `soothe`, `soothe_daemon` (use WebSocket) |

### Hard bans (owned packages)

1. **CLI sits above the daemon** — `soothe_cli` must not import daemon/host;
   communicate via wire contracts in `soothe-sdk` + `soothe-client-python`.
2. **Daemon does not depend on the WS client** — `soothe_daemon` must not
   import `soothe_client` in runtime source; admin RPCs use
   `soothe_sdk.wire` (tests may use the client via the `dev` extra).
3. **Private nano middleware is closed** — owned packages must not import
   `soothe_nano.middleware._*`.

## `soothe` package — internal slices

| Slice | Owns |
|-------|------|
| `sloop/` | StrangeLoop graph — `engine/`, `orchestrator/`, `state/`, `stages/`, `cognition/`, `intention/`, `clarification/`, `plans/`, `nodes/`, `checkpoints/`, `prompts/` |
| `autopilot/` | Autopilot / GoalEngine (L3) — `service`, `cognition/`, `dispatch/`, `intake/`, `monitor/`, `notify/`, `rail/`, `schedule/`, `verify/`, `workers/`, `jobs/` |
| `coreagent/` | CoreAgent runtime (`core_agent`, `factory`, `builder`, `lazy`) — delegates to `soothe-nano` |
| `runner/` | Host runner — `_runner_strange_loop`, `_runner_autopilot_worker`, `_thread_manager`, `resolver/` |
| `context/` | Context Engine — `engine`, `ledger`, `retrieval`, `projection`, `semantic`, `store_{base,sqlite,pgsql,factory}` |
| `protocols/` | Abstract contracts — `loop_working_memory`, `loop_planner`, `runner`, `operation_security` |
| `rails/` | Execution discipline — `catalog`, `builtins`, `selector`, `l0_schema`, `verb_defaults` |
| `cron/` | Scheduler — `service`, `store{_postgres,_factory}`, `extraction`, `models`, `messages` |
| `persistence/` | Unified stores — `unified`, `sqlite_runtime`, `postgres_pool`, `loop_writer`, `checkpoint_split`, `db_init` |
| `identity/` | Auth & tokens — `identity_service`, `db`, `credentials`, `tokens`, `runtime`, `middleware` |
| `security/` | `operation_security`, `edit_lock`, `locked_backend`, `daemon_kill_guards` |
| `events/` | Internal bus — `catalog`, `internal_bus`, `internal_events`, `visibility` |
| `workspace/` | `loop_workspace`, `resolution`, `scoped` |
| `mcp/` | `progressive_registry` |
| `config/`, `subagents/`, `utils/`, `prompts/`, `logging/`, `diagnose/` | Supporting slices |

## `soothe-daemon` package — internal slices

| Slice | Owns |
|-------|------|
| `server/` | WS + HTTP core — `core`, `handlers`, `session`, `auth_handler`, `commands` |
| `channels/` | IM adapters (telegram, discord, slack, matrix, msteams, feishu, dingtalk, qq, wecom, weixin, whatsapp, signal, email, mochat, websocket) + `registry`, `base`, `message`, `events`, `platform_helpers` |
| `services/` | `memory_profiler`, `intent_hint_turn`, `image_understanding` |
| top-level | `cli.py` (Typer `soothed`), `__main__`, `admin_rpc`, `channel_manager`, `identity_cli` |
| `bootstrap/`, `config/`, `runtime/`, `setup/`, `health/`, `query/`, `display/`, `events/`, `notify/`, `persistence/`, `runner/`, `protocol/`, `skillify/` | Supporting slices |

## `soothe-cli` package — internal slices

| Slice | Owns |
|-------|------|
| `cli/` | `main.py` (Typer app), `commands/`, `execution/` |
| `tui/` | Textual `app/`, `widgets/`, `commands/`, `sessions`, `hooks`, `card_wire`, `composer_mode`, `tool_display`, `mermaid_render`, `markdown_theme`, `model_config`, `theme`, `media_utils`, `file_change_*`, `input`, `binding`, `command_registry`, `unicode_security` |
| `config/`, `runtime/` | Supporting slices |

## Persistence mode rule (§10)

`persistence.default_backend` is **one mode for the whole process**: either
`postgresql` or `sqlite`. Never mix the two in the same daemon/runtime.

- `default_backend: postgresql` → all durable stores use Postgres; vector
  store uses `pgvector`.
- `default_backend: sqlite` → use local `$SOOTHE_HOME` / `$SOOTHE_DATA_DIR`
  SQLite files; vector store uses `sqlite_vec`.
- Overrides (`agent.protocols.durability.backend` / `.checkpointer`) MUST stay
  `"default"` unless the operator intentionally switches the entire process.

## Data flow (end-to-end)

```text
User ── Typer/TUI (soothe-cli) ──WebSocket── soothe-client-python ──┐
                                                                    ▼
                              soothe-daemon server/ (WS/HTTP) ── session/auth ── handlers/commands
                                    │                                   ▲
                          channels/ (IM platforms) ─── inbound msg     │
                                    │                                   │
                                    ▼                                   │
        soothe host runner ──► Autopilot service (GoalEngine, L3)      │
                                    │ PERFORM (full delegation)         │
                                    ▼                                   │
                  StrangeLoop (sloop/engine/, L2)                      │
                  plan → assess → execute (iterative)                   │
                                    │ EXECUTE (step)                    │
                                    ▼                                   │
                  CoreAgent (coreagent/) ──► soothe-nano (L1 runtime)   │
                                    │                                    │
        Cross-cutting (all levels):                                     │
          • context/  — unbounded ledger + bounded projection          │
          • persistence/ — checkpointer + stores (sqlite|postgres)     │
          • identity/ — auth/tokens                                    │
          • cron/ — scheduled jobs                                     │
          • rails/ — execution discipline                              │
          • events/ — internal bus ─► daemon display/events ──────────────┘
                                          │ wire (soothe-sdk) ──► CLI TUI cards
```

Three-level execution (concrete names per AGENTS §7):
**Autopilot/GoalEngine** manages goal DAGs and delegates single-goal execution
to **StrangeLoop**, which iterates plan→execute and delegates steps to
**CoreAgent** (→ `soothe-nano`).

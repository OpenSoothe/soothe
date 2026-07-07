---
title: "Protocol Resolver"
parent: Core Modules
grand_parent: Wiki
nav_order: 6
description: Wiring protocol declarations from configuration to runtime instances.
---

# Protocol Resolver

Wiring protocol declarations from configuration to runtime instances.

---

## What This Module Is

The protocol resolver (`soothe.runner.resolver`) is the bridge between SootheConfig declarations and live runtime objects. It translates YAML configuration into instantiated protocols, tools, subagents, and persistence infrastructure. Both `create_soothe_agent()` and `SootheRunner.__init__()` call into the resolver — it's the single place where "config says X" becomes "runtime has an X instance."

The resolver is split across three files:
- `__init__.py` — protocol resolution (memory, planner, policy)
- `_resolver_tools.py` — tool and subagent registries
- `_resolver_infra.py` — durability and checkpointer backends

**Source**: `packages/soothe/src/soothe/runner/resolver/`

---

## Why a Dedicated Resolver?

Without a resolver, construction logic would be duplicated between the agent factory and the runner. The resolver centralizes three concerns:

1. **Protocol instantiation** — each protocol has one implementation; the resolver knows which.
2. **Backend selection** — durability/checkpointer have a binary choice (SQLite vs PostgreSQL) with no in-memory fallback.
3. **Capability assembly** — tools and subagents are assembled from built-in registries plus plugins plus MCP.

The design is intentionally **not** a generic plugin/dispatch system. Each protocol has exactly one implementation:

| Protocol | Implementation | Notes |
|----------|---------------|-------|
| Memory | `MemUMemory` | Semantic search + keyword indexing; `None` if disabled |
| Planner | `LLMPlanner` | Unified (IG-150 consolidation); always instantiated |
| Policy | `ConfigDrivenPolicy` | Profile-based; always instantiated |
| Durability | `SQLiteDurability` / `PostgreSQLDurability` | Binary choice, no fallback |

This intentional simplicity means adding a new protocol backend requires changing resolver code, not just config. The trade-off: less flexibility, but zero ambiguity about what gets instantiated.

---

## The No-In-Memory-Fallback Rule

This is the most important design decision in the resolver. `resolve_checkpointer()` and `resolve_durability()` **never fall back to in-memory storage**. If the configured backend fails to initialize, they raise `ConfigurationError`.

The rationale: in-memory storage silently loses state on process restart. For a daemon that may run for days, silently degrading to in-memory would cause checkpoint loss, thread state loss, and goal DAG loss — all without error messages. Failing loud at startup is better than failing silent at runtime.

The error messages are explicit about remediation:
- PostgreSQL: "Install with: `pip install 'soothe[postgres]'`" and "Verify `postgres_base_dsn` and `postgres_databases` configuration."
- SQLite: "Check sqlite3 installation and path configuration."

---

## Checkpointer Resolution — Deferred Async Initialization

The checkpointer has a subtlety: `resolve_checkpointer()` returns **either** a checkpointer **or** a `(None, resource)` tuple:

- **PostgreSQL** → returns `(None, SharedCheckpointerPool)` — the actual `AsyncPostgresSaver` is created from the pool in async context (during runner's async initialization). This avoids "no running event loop" errors.
- **SQLite** → returns `(None, db_path)` — the `AsyncSqliteSaver` is created from the path in async context.

The runner handles both cases: if it gets a tuple, it stores the pool/path and initializes the checkpointer lazily in `_ensure_checkpointer_initialized()`. The connection resource (pool) **must be closed during cleanup** via `runner.cleanup()`.

### SharedCheckpointerPool

For PostgreSQL, the resolver uses `SharedCheckpointerPool.get_or_create_pool(config)` — a singleton pool shared across multiple runners/loops for high-concurrency support. This avoids creating a new connection pool per runner instance.

### RFC-802 Multi-Database Architecture

PostgreSQL uses **dedicated databases** per concern:
- `metadata` database → durability
- `checkpoints` database → LangGraph checkpointer

The DSN is resolved via `config.resolve_postgres_dsn_for_database("metadata")` and `config.resolve_postgres_dsn_for_database("checkpoints")`.

---

## Protocol Resolution Details

### Memory (`resolve_memory`)

Returns `MemUMemory(config)` if `config.agent.protocols.memory.enabled` is `True`, else `None`. MemU uses two model roles: `llm_chat_role` (for extraction) and `llm_embed_role` (for embeddings). If disabled, the agent simply has no memory protocol — `agent.memory` returns `None`.

### Planner (`resolve_planner`)

Always returns an `LLMPlanner` instance — there is no "disabled" state for the planner. The model is resolved with a fallback chain: first the provided `model` argument, then `config.create_chat_model(planner_role)` (default role: `think`), then `config.create_chat_model("default")`. If all fail, the planner is created with `model=None` (it will degrade at runtime).

### Policy (`resolve_policy`)

Always returns `ConfigDrivenPolicy(config)`. No backend selection — config-driven policy is the only implementation.

---

## Tool and Subagent Resolution

`resolve_tools(config)` assembles the tool list from multiple sources:
1. **Built-in tools** — gated by `config.tools.execution.enabled`, `config.tools.websearch.enabled`, etc.
2. **Plugin tools** — loaded via `load_plugin_tools(config)`
3. **MCP tools** — loaded from configured MCP servers

`resolve_subagents(config)` assembles subagents from a `SUBAGENT_FACTORIES` registry — built-in subagents (planner, deep_research, academic_research, browser_use, veritas) plus plugin subagents. Semantic skill search is handled by `foundation.skillify.SkillifyService`, not the subagent registry.

The resolver also provides **lazy subagent** loading (`_lazy_subagent.py`) — subagents can be compiled on first use rather than at agent construction time, reducing startup cost.

---

## Configuration Mapping

The resolver reads from standard config sections:

```yaml
agent:
  protocols:
    memory:
      enabled: true
      llm_chat_role: think
      llm_embed_role: embedding
    planner:
      enabled: true
      model: think
    policy:
      enabled: true
      profile: standard
    durability:
      enabled: true
      backend: sqlite  # or postgresql

persistence:
  default_backend: sqlite  # drives ContextEngine backend too
```

Tool and subagent configs live under their own top-level keys (`tools:` and `subagents:`), each with per-item `enabled` flags.

---

## Integration Points

- **AgentBuilder** — calls `resolve_memory`, `resolve_planner`, `resolve_policy`, `resolve_tools`, `resolve_subagents` during `build()`.
- **SootheRunner** — calls `resolve_checkpointer`, `resolve_durability`, `resolve_planner`, `resolve_policy` in `__init__()`; the checkpointer is passed to `create_soothe_agent()`.
- **FrameworkFilesystem** — uses `resolve_daemon_workspace()` for the default root directory (see [Workspace](workspace.md)).

---

## Gotchas

- **PostgreSQL requires explicit setup** — the `metadata` and `checkpoints` databases must be created and accessible before starting the daemon. The resolver will not create them.
- **Checkpointer cleanup is the runner's responsibility** — if you bypass the runner and call `resolve_checkpointer` directly, you must close the returned connection resource yourself.
- **Planner model fallback is silent** — if the `think` model role isn't configured, the planner falls back to `default`, then to `None`. A `None` model won't fail at resolution time but will degrade during planning.
- **Tool cache** — `_tool_cache.py` caches resolved tools to avoid re-instantiating on repeated agent builds within the same process.

---

## Related

- **[Agent Factory](agent-factory.md)** — consumes resolved protocols
- **[SootheRunner](runner.md)** — consumes checkpointer and durability
- **[Configuration Guide](../configuration-guide/index.md)** — config schema
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** — architecture spec

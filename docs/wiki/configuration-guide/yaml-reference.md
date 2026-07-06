# YAML Reference

A condensed quick-reference for the Soothe YAML schema. This is a map, not an enumeration — for every field's type, default, and constraint, read the authoritative source in `packages/soothe/src/soothe/config/models.py`.

## How the Schema Is Organized

The top-level `SootheConfig` (in `config/settings.py`) is a Pydantic `BaseSettings` model with `env_prefix="SOOTHE_"`. Top-level fields and JSON-encoded list/object fields accept env overrides; nested dotted paths (e.g. `SOOTHE_ROUTER_DEFAULT`) do not — see [Environment Variables](environment-variables.md).

**Zero-config:** with no YAML file, set `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) and run. Soothe synthesizes a provider and uses built-in router/vector-store defaults. Explicit YAML `providers` always wins.

A minimal YAML file (when you need multi-provider or non-env secrets) touches only `providers` and `router_profiles`:

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o-mini]
router_profiles:
  - name: default
    router:
      default: openai:gpt-4o-mini
    embedding_dims: 1536
active_router_profile: default
```

Internal tuning (`agent.loop.*`, pool sizes, security deny lists, etc.) lives in Pydantic defaults — see `models.py`, not the template.

The full set of sections:

| Section | Source model | What it controls |
|---------|--------------|------------------|
| `providers` | `ModelProviderConfig` | LLM/embedding API endpoints and keys |
| `router_profiles` / `active_router_profile` | `RouterProfile` | Named presets; resolved into `router` + `embedding_dims` at load |
| `router` | `ModelRouter` | **Derived** (not in YAML) — role → `provider:model` mapping |
| `embedding_dims` | int | **Derived** from active profile; must match embedding model |
| `agent` | `AgentConfig` | Identity, loop, autonomous mode, protocols |
| `subagents` | `SubagentConfig` (dict) | plan / tacitus / browser_use / skillify / veritas |
| `tools` | `ToolsConfig` | Tool group enable/disable + config |
| `mcp_servers` | `MCPServerConfig` (list) | External MCP server connections |
| `observability` | `ObservabilityConfig` | Logging, verbosity, Langfuse |
| `persistence` | `PersistenceConfig` | SQLite / PostgreSQL backends + pools |
| `vector_stores` | `VectorStoreProviderConfig` (list) | Vector storage backends |
| `vector_store_router` | `VectorStoreRouter` | Role → `provider:collection` |
| `security` | `SecurityConfig` | Path policies, sandbox, approvals |
| `plugins`, `skills`, `memory` | various | Extension points |
| `ui`, `update`, `debug` | various | UI and runtime toggles |

YAML loading runs two pre-validation passes: `${VAR}` interpolation (see [Environment Variables](environment-variables.md)) and legacy-key folding (`logging:` → `observability:`, `strange_loop:` → `agent.loop:`). This is why older configs still work.

## Providers

Each entry is a `ModelProviderConfig` with `name` (referenced by the router), `provider_type` (`openai` | `anthropic` | `ollama`), `api_key` (supports `${VAR}`), `api_base_url` (override for compatible APIs), and `models` (documentation list, not enforced).

| Field | Purpose |
|-------|---------|
| `name` | Identifier referenced by the router |
| `provider_type` | LangChain provider type; custom `api_base_url` on `openai` auto-enables local-server wrappers |
| `api_key` | Supports `${VAR}` interpolation |
| `api_base_url` | Override for compatible APIs (DashScope, OpenRouter, vLLM, LMStudio) |
| `models` | Available model names (documentation; not enforced) |

See [Provider Setup](provider-setup.md) for selection criteria.

## Router

Define routing in **`router_profiles`** and select with **`active_router_profile`**. At load, Soothe copies the active profile into derived fields `router` and `embedding_dims`.

`ModelRouter` maps six roles to `"provider_name:model_name"` strings: `default`, `think`, `fast`, `image`, `ocr`, `embedding`. Unset roles inherit `default`. Agent code never names a model directly — it requests a role and the router resolves it.

## Agent

The largest section. `AgentConfig` consolidates identity (`name`, `system_prompt`), behavior (`goal_completion_mode`: llm_only/heuristic_only/hybrid; `final_response`: adaptive/always_synthesize), `autonomous`, `loop`, and `protocols`.

### Autonomous (`agent.autonomous`)

Controls 24/7 self-running. All fields are ceilings to bound cost and prevent runaway loops. Key ones: `enabled`, `max_iterations` (per goal), `max_parallel_goals`, `max_loops`, `dreaming_enabled`, `scheduler_enabled`, `max_scheduled_tasks`, `webhooks`. See [Autonomous Mode](../autonomous-mode.md) for detail.

### Loop (`agent.loop`)

CoreAgent internal tuning. Notable sub-sections:

| Sub-section | Purpose |
|-------------|---------|
| `max_iterations`, `context_window_limit` | Hard stops for the agent loop |
| `concurrency` | `max_parallel_steps`, `max_parallel_subagents`, `global_max_llm_calls`, `step_parallelism` |
| `llm_rate_limit` | RPM, concurrency, timeouts, 429/timeout retry policy |
| `tool_call_limit` | Per-thread and per-run tool call caps |
| `tool_retry` | Retry policy for tool failures |
| `output_streaming` | `batch` / `adaptive` / `streaming` delivery modes |
| `working_memory` | Inline context char caps |
| `checkpoint` | `progressive`, `auto_resume_on_start` |

### Protocols (`agent.protocols`)

Backend selection for four protocols:

| Protocol | Key fields | Default |
|----------|-----------|---------|
| `memory` (MemU) | `enabled`, `llm_chat_role`, `llm_embed_role`, `enable_embeddings` | enabled, roles `fast`/`embedding` |
| `planner` | `model` (role), `routing` (auto/always_direct/always_planner/always_claude) | `think`, `auto` |
| `policy` | `profile` | `standard` |
| `durability` | `backend`, `checkpointer` (both accept `default` to inherit `persistence.default_backend`), `thread_inactivity_timeout_hours` | `default`, 72h |

The `default` sentinel in durability lets you set the backend once in `persistence` and have protocols inherit it — change `persistence.default_backend` and all protocols follow.

## Subagents

A dict of `SubagentConfig` entries. Each has `enabled`, `model` (null → falls back to `fast` role), `transport` (local | acp | a2a | langgraph), `url`, `config` (subagent-specific), and `runtime_dir`. `tacitus` takes `config.effort` (minimal/normal/thorough); `plan` takes `config.routing` (auto/always_direct/always_planner).

Built-ins (`plan`, `tacitus`, `browser_use`, `skillify`, `veritas`) are merged automatically; you only override what you want to change. `browser_use` ships enabled by default in core. Claude Code runs via `agent.core_agent_backend`, not as a subagent.

## Tools

`ToolsConfig` holds independently toggleable groups: `execution` (run_command/run_python/run_background), `file_ops`, `datetime`, `data`, `wizsearch` (with `default_engines`, `max_results_per_engine`, `timeout`), `image`, `audio`, `video`, `http_requests` (with `allow_dangerous_requests`, `verify_ssl`), `deepxiv` (with `token`, `timeout`, `max_retries`). Disabling a group removes its tools from the model's array entirely (saves context tokens). See [Common Patterns](common-patterns.md) for use-case scoping.

## MCP Servers

A list of `MCPServerConfig` entries. Each has `name` (unique, validated at startup), `transport` (stdio | sse | streamable_http | websocket), `command`/`args`/`env` (for stdio), `url` (for remote), `auth` (bearer/header, supports `${VAR}`), `enabled`, `defer` (progressive — when true, tools aren't in the default array), `tool_filter` (glob allowlist), and timeout fields. `progressive_mcp` controls the listing budget as a fraction of context.

## Observability

`ObservabilityConfig` controls `verbosity` (quiet/normal/debug — TUI display), `log_file_*` (level, path, rotation), `console` (enabled/level/stream), `thread_logging_*`, `global_history`, `langfuse` (enabled/public_key/secret_key/host/environment/sample_rate), and `profile_model_calls`. Top-level `logging:` is accepted as a legacy alias and folded into `observability` + `agent.loop.report_output`.

## Persistence

`PersistenceConfig` supports two modes: single-database (`soothe_postgres_dsn`) or multi-database (`postgres_base_dsn` + `postgres_databases` map of checkpoints/metadata/vectors/memory, RFC-802). `default_backend` selects sqlite or postgresql. SQLite paths default to `~/.soothe/data/`. Pool fields: `postgres_pool_min_size`, `checkpointer_pool_size`, `sloop_pool_size`, and idle/lifetime/acquire timeouts. Multi-database is preferred for production — independent backup/restore per component. Pool sizing differs between thread-pool (shared singleton) and worker-pool (per-worker) modes; see [Provider Setup](provider-setup.md).

## Vector Stores

A list of `VectorStoreProviderConfig` entries (`name`, `provider_type`: pgvector/weaviate/in_memory/sqlite_vec) plus backend-specific fields (pgvector: `dsn`, `pool_size`, `index_type` hnsw/ivfflat/none; weaviate: `url`, `api_key`, `grpc_port`). `vector_store_router.default` is `"provider_name:collection_name"`; unset roles fall back to `default`. If using pgvector without an explicit `dsn`, Soothe auto-resolves from `persistence.postgres_base_dsn` (the `vectors` database).

## Security

`SecurityConfig` fields: `sandbox` (enables sandboxed `execute` tool; host tools always available), `allow_paths_outside_workspace`, `require_approval_for_outside_paths`, `denied_paths` (globs, checked first), `allowed_paths` (overrides denied within workspace), `denied_file_types`, `require_approval_for_file_types` (defaults to `.env`/`.pem`/`.key`/`.p12`/`.pfx`/`.crt`), plus `whitelist_paths_bypass` and `whitelist_commands_bypass`.

**Evaluation order:** denied_paths → allowed_paths → workspace boundary → file-type rules → default deny. See [Security](../deployment/security.md) for policy design.

## UI & Runtime

`UIConfig` (`theme`), top-level `debug`, `activity_max_lines`, `tui_debug`, and `UpdateConfig` (`check`, `auto_update`).

## Minimal Configs

**Production** needs only a provider with an interpolated key, a `router.default`, and `embedding_dims` matching the embedding model.

**Dev with reasoning + tracing** adds a `think` role, enables autonomous with a low `max_iterations`, bumps `loop.max_iterations`, and turns on `langfuse` with interpolated keys. See [Common Patterns](common-patterns.md) for the full recipes.

## Where to Look Next

- **Full field details:** `packages/soothe/src/soothe/config/models.py`
- **Top-level wiring & validators:** `packages/soothe/src/soothe/config/settings.py`
- **Interpolation implementation:** `packages/soothe/src/soothe/config/env.py`
- **Recipes & reasoning:** [Common Patterns](common-patterns.md)
- **Provider choice:** [Provider Setup](provider-setup.md)
- **Env vars:** [Environment Variables](environment-variables.md)

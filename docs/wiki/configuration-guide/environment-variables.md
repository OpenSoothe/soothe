---
title: "Environment Variables"
parent: Configuration Guide
grand_parent: Wiki
nav_order: 2
description: >-
  How Soothe consumes environment variables — the distinct mechanisms, what works today, and secrets management.
---

# Environment Variables

How Soothe consumes environment variables — the distinct mechanisms, what actually works today, and how to manage secrets safely.

## Five Mechanisms

Soothe reads the environment in several ways. Mixing them up is the most common config mistake:

1. **Zero-config provider keys** — with no YAML and empty `providers`, Soothe synthesizes a provider from `OPENAI_API_KEY` / `OPENAI_BASE_URL` or `ANTHROPIC_API_KEY` (see `SootheConfig._bootstrap_providers_from_env`).

2. **Top-level `SOOTHE_*` overrides** — Pydantic `BaseSettings` with `env_prefix="SOOTHE_"` maps env vars onto **top-level** `SootheConfig` fields (`debug`, `active_router_profile`, etc.).

3. **JSON `SOOTHE_*` blobs** — list and nested-object fields (`providers`, `router_profiles`, `persistence`, `vector_stores`, …) must be passed as **JSON strings**. Dotted path env vars like `SOOTHE_ROUTER_DEFAULT` or `SOOTHE_PERSISTENCE_POSTGRES_BASE_DSN` are **not** supported on `SootheConfig` (no `env_nested_delimiter`).

4. **`${VAR}` interpolation in YAML** — before Pydantic validation, `_expand_env_in_config` replaces `${VAR}` tokens in YAML strings. Use this for secrets inside structured config files.

5. **`SOOTHE_DAEMON_*` (daemon server)** — separate model (`SootheDaemonConfig`) with prefix `SOOTHE_DAEMON_` and nested delimiter `__` (e.g. `SOOTHE_DAEMON_TRANSPORTS__WEBSOCKET__HOST`).

They fail differently: an unset top-level `SOOTHE_*` var falls back to YAML/defaults; an unresolved `${VAR}` in YAML stays literal and usually fails validation; a malformed JSON env var fails at startup with a Pydantic error.

## Zero-Config (No YAML)

Minimum to run the agent core or daemon:

```bash
export OPENAI_API_KEY=sk-...
soothed start --foreground   # or Docker — see Quick Start in README
soothe "hello"
```

Bootstrap creates provider `openai` and applies the built-in **default** router profile (`openai:gpt-4o-mini`). Vector stores default to embedded `sqlite_vec`.

**OpenAI-compatible endpoints** (DashScope, OpenRouter, local vLLM):

```bash
export DASHSCOPE_API_KEY=sk-...
export OPENAI_API_KEY="$DASHSCOPE_API_KEY"
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]'
```

Provider bootstrap names the provider `openai`; router targets must use the `openai:` prefix (e.g. `openai:qwen3.7-plus`, not `dashscope:…`), unless you define a named provider via `SOOTHE_PROVIDERS` JSON.

**Anthropic:**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

To change the default model without YAML, set `SOOTHE_ROUTER_PROFILES` (JSON) — see [Router overrides](#router-overrides-env-only) below. `SOOTHE_ROUTER_DEFAULT` does **not** work.

## Top-Level `SOOTHE_*` (Agent Config)

These map directly and work as documented:

| YAML path | Env var | Notes |
|-----------|---------|-------|
| `debug` | `SOOTHE_DEBUG` | |
| `active_router_profile` | `SOOTHE_ACTIVE_ROUTER_PROFILE` | Also read inside `_apply_active_router_profile` |
| `tui_debug` | `SOOTHE_TUI_DEBUG` | |

```bash
export SOOTHE_DEBUG=true
export SOOTHE_ACTIVE_ROUTER_PROFILE=production   # profile must exist in YAML or SOOTHE_ROUTER_PROFILES
```

**Does not work via flat env vars:** nested paths such as `router.default`, `agent.loop.max_iterations`, `persistence.postgres_base_dsn`, `observability.langfuse.enabled`. Use JSON blobs, YAML, or CLI flags instead.

## JSON `SOOTHE_*` (Nested / List Fields)

Pydantic Settings accepts JSON for complex fields. Prefix is still `SOOTHE_`.

| Field | Env var | Example |
|-------|---------|---------|
| `providers` | `SOOTHE_PROVIDERS` | `'[{"name":"openai","api_key":"sk-..."}]'` |
| `router_profiles` | `SOOTHE_ROUTER_PROFILES` | See [Router overrides](#router-overrides-env-only) |
| `persistence` | `SOOTHE_PERSISTENCE` | `'{"default_backend":"postgresql","postgres_base_dsn":"postgresql://..."}'` |
| `vector_stores` | `SOOTHE_VECTOR_STORES` | `'[{"name":"pgvector","provider_type":"pgvector"}]'` |
| `vector_store_router` | `SOOTHE_VECTOR_STORE_ROUTER` | `'{"default":"pgvector:soothe_default"}'` |

```bash
export SOOTHE_PERSISTENCE='{"default_backend":"postgresql","postgres_base_dsn":"postgresql://postgres:postgres@localhost:5432"}'
export SOOTHE_VECTOR_STORES='[{"name":"pgvector","provider_type":"pgvector"}]'
export SOOTHE_VECTOR_STORE_ROUTER='{"default":"pgvector:soothe_default"}'
```

Quote carefully in shell and Compose — single quotes around the JSON are safest.

### Router overrides (env-only)

`router` on `SootheConfig` is **`init=False`**: it is computed from `router_profiles` + `active_router_profile`. Individual `SOOTHE_ROUTER_*` role vars are not applied.

**Replace the profile list (no YAML):**

```bash
# DashScope via OPENAI_* bootstrap (provider name "openai")
export SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]'
```

Generic OpenAI example:

```bash
export SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:gpt-4o","think":"openai:gpt-4o"},"embedding_dims":1536}]'
```

**Switch a named profile** (profiles defined in YAML or via `SOOTHE_ROUTER_PROFILES`):

```bash
export SOOTHE_ACTIVE_ROUTER_PROFILE=production
```

## `SOOTHE_DAEMON_*` (Daemon Server)

Daemon transport, concurrency, and paths use prefix `SOOTHE_DAEMON_` and nested delimiter `__`:

| YAML path (`daemon.yml`) | Env var |
|--------------------------|---------|
| `transports.websocket.host` | `SOOTHE_DAEMON_TRANSPORTS__WEBSOCKET__HOST` |
| `transports.http_rest.enabled` | `SOOTHE_DAEMON_TRANSPORTS__HTTP_REST__ENABLED` |
| `soothe_config_path` | `SOOTHE_DAEMON_SOOTHE_CONFIG_PATH` |
| `memory_profiling.enabled` | `SOOTHE_DAEMON_MEMORY_PROFILING__ENABLED` |

The production Docker image sets `SOOTHE_DAEMON_TRANSPORTS__WEBSOCKET__HOST=0.0.0.0` and enables HTTP REST by default.

If `soothe_config_path` points to a missing file, the daemon loads agent defaults (zero-config bootstrap). Do **not** mount a config file when running env-only.

## `${VAR}` Interpolation (YAML)

Write placeholders in YAML; Soothe resolves them at load time:

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
persistence:
  postgres_base_dsn: ${POSTGRES_DSN}
```

Behaviors (`config/env.py`):

- **Works anywhere in a string:** `${HOME}/workspaces`, `${VAR1}/${VAR2}`.
- **Unresolved vars stay literal** — usually fails validation or skips the provider.
- **Pattern:** `\$\{(\w+)\}` only (word characters; no `$VAR` POSIX form).

Production Compose often uses `${SOOTHE_POSTGRES_BASE_DSN}` inside mounted YAML — that is interpolation into the file, not a `SOOTHE_*` field override.

## Provider & Tool Keys (No Prefix)

Not `SOOTHE_*` — used by zero-config bootstrap, `${VAR}` in YAML, or LangChain directly:

| Variable | Used for |
|----------|----------|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI / compatible APIs |
| `ANTHROPIC_API_KEY` | Anthropic |
| `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL` | DashScope (usually via `${...}` in YAML) |
| `OPENROUTER_API_KEY` | OpenRouter |
| `TAVILY_API_KEY`, `SERPER_API_KEY`, `JINA_API_KEY` | Web search |
| `DEEPXIV_API_KEY`, `DEEPXIV_TOKEN` | Academic search |
| `GITHUB_TOKEN`, `GITHUB_MCP_TOKEN`, `LINEAR_MCP_TOKEN` | MCP auth |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Tracing |
| `POSTGRES_DSN`, `POSTGRES_VECTOR_DSN`, … | Storage (via `${...}` in YAML) |

## Path & Runtime Vars

| Variable | Purpose |
|----------|---------|
| `SOOTHE_HOME` | Base dir (default `~/.soothe`; `/var/lib/soothe` in Docker) |
| `SOOTHE_CONFIG_FILE` | Override agent config path (CLI `--config` wins first) |
| `SOOTHE_JWT_KEY` | Identity JWT signing key |
| `SOOTHE_WORKSPACE` | Daemon fallback workspace (`resolve_daemon_workspace`); also used in tests |

## CLI env vars (`SOOTHE_CLI_*`)

| Variable | Purpose |
|----------|---------|
| `SOOTHE_CLI_OMIT_WORKSPACE` | Optional `1`/`true`: omit `workspace` on `loop_new` (default: send `cwd`) |
| `SOOTHE_CLI_WORKSPACE` | Override project path sent to daemon (default: cwd); `none`/`-`/`omit` omits workspace |

Agent config (JSON or YAML) for Docker path mapping:

| Variable / YAML | Purpose |
|-----------------|---------|
| `SOOTHE_WORKSPACE_MOUNT` | JSON: `{"host_root":"/Users/you/Workspace","container_root":"/var/lib/soothe/workspaces"}` |
| `workspace_mount.host_root` | Host prefix of CLI project paths (RFC-621) |
| `workspace_mount.container_root` | In-container mount point (must match Docker `-v` target) |

## Priority & Override Chains

Resolution order, highest to lowest:

1. **CLI args** (`--config`, `--debug`, daemon `--soothe-config`)
2. **Top-level / JSON `SOOTHE_*` env vars**
3. **YAML file** (with `${VAR}` already interpolated)
4. **Pydantic model defaults** (+ zero-config provider bootstrap)

After load, `_apply_active_router_profile` copies the selected profile into `router` and `embedding_dims`. Env cannot patch individual router roles afterward unless you replace `SOOTHE_ROUTER_PROFILES` or edit YAML.

## Docker (Env-Only, No Config File)

**DashScope + `qwen3.7-plus`:**

```bash
export DASHSCOPE_API_KEY=sk-...
export SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]'

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e DASHSCOPE_API_KEY \
  -e OPENAI_API_KEY="$DASHSCOPE_API_KEY" \
  -e OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e SOOTHE_ROUTER_PROFILES \
  -v soothe-data:/var/lib/soothe \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

Postgres sidecar + persistence without YAML:

```bash
-e SOOTHE_PERSISTENCE='{"default_backend":"postgresql","postgres_base_dsn":"postgresql://postgres:postgres@soothe-pgvector:5432"}' \
-e SOOTHE_VECTOR_STORES='[{"name":"pgvector","provider_type":"pgvector"}]' \
-e SOOTHE_VECTOR_STORE_ROUTER='{"default":"pgvector:soothe_default"}'
```

Image: `registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest` (or a pinned tag). Health: `curl http://127.0.0.1:8765/healthz`.

### Host CLI + Docker daemon: workspace mount (RFC-621)

Use this when the CLI runs on the host and the daemon runs in Docker **and** you want file/shell tools to touch your local repo.

**Three pieces must align:**

| Piece | Example |
|-------|---------|
| Docker bind mount | `-v /Users/you/Workspace:/var/lib/soothe/workspaces` |
| `workspace_mount.host_root` | `/Users/you/Workspace` (must be a prefix of CLI `cwd`) |
| `workspace_mount.container_root` | `/var/lib/soothe/workspaces` (same as mount target in container) |

**Env-only (no config file):**

```bash
export HOST_WS=/Users/you/Workspace
export CONTAINER_WS=/var/lib/soothe/workspaces
export SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]'

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e DASHSCOPE_API_KEY \
  -e OPENAI_API_KEY="$DASHSCOPE_API_KEY" \
  -e OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e SOOTHE_ROUTER_PROFILES \
  -e SOOTHE_WORKSPACE_MOUNT="{\"host_root\":\"$HOST_WS\",\"container_root\":\"$CONTAINER_WS\"}" \
  -v soothe-data:/var/lib/soothe \
  -v "$HOST_WS:$CONTAINER_WS" \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest

cd /Users/you/Workspace/soothe && soothe
```

Path translation: CLI sends `/Users/chenxm/Workspace/soothe` → daemon uses `/var/lib/soothe/workspaces/soothe`.

**With YAML** (Compose / `deploy/`): same mapping under `workspace_mount:` in agent config; mount `${SOOTHE_WORKSPACE_HOST_ROOT}:/var/lib/soothe/workspaces` — see `deploy/config.prod.yml` and root `docker-compose.yml`.

**Rules:**

- `host_root` must be a **parent directory** of every project you `cd` into before running `soothe`.
- Do **not** set `SOOTHE_CLI_OMIT_WORKSPACE` when using a mount — the CLI must send host `cwd` for RFC-621 mapping.
- If you see `Client workspace does not exist`, the bind mount or `host_root` does not match your paths (or `workspace_mount` is unset).

### Host CLI + Docker daemon: chat-only (no mount)

When the daemon has **no** workspace volume and **no** `workspace_mount`, the CLI may still send host `cwd`. The daemon detects that the path is absent on the container filesystem and uses `$SOOTHE_HOME/data/workspaces/...` automatically — **`SOOTHE_CLI_OMIT_WORKSPACE` is not required**.

Optionally set `SOOTHE_CLI_OMIT_WORKSPACE=1` to omit `workspace` on the wire (slightly cleaner handshake; same runtime layout).

## Per-Environment Setup

Keep **structure** in YAML (or JSON env for headless Docker); keep **secrets** in the environment.

**Development:**

```bash
export OPENAI_API_KEY=sk-dev-...
export SOOTHE_DEBUG=true
# optional: export SOOTHE_CONFIG_FILE=~/.soothe/config.dev.yml
```

**Production / CI:** provider keys via secret manager; Postgres via YAML + `${POSTGRES_DSN}` or `SOOTHE_PERSISTENCE` JSON; Langfuse via `${LANGFUSE_*}` in YAML.

**Testing:**

```bash
export SOOTHE_PERSISTENCE='{"default_backend":"sqlite"}'
# observability flags: set in YAML or use JSON SOOTHE_OBSERVABILITY='{"langfuse":{"enabled":false}}'
```

## Secret Hygiene

- Never commit resolved secrets — use `${VAR}` in YAML.
- Rotate by updating env and restarting; no config edit needed for interpolated keys.
- Verify: `env | grep -E 'SOOTHE|OPENAI|ANTHROPIC'`.

## Troubleshooting

**Variable not applied?**

1. Top-level field? Must match exactly (`SOOTHE_DEBUG`, not `SOOTHE_DEBUG_MODE`).
2. Nested field? Use JSON (`SOOTHE_PERSISTENCE`, `SOOTHE_ROUTER_PROFILES`) or YAML — not `SOOTHE_FOO_BAR_BAZ` dotted paths.
3. Router model unchanged? `SOOTHE_ROUTER_DEFAULT` is ignored; use `SOOTHE_ROUTER_PROFILES` or YAML `router_profiles`.
4. Daemon transport? Use `SOOTHE_DAEMON_*` with `__` nesting.
5. Shell exported the var? `source ~/.zshrc` or restart the daemon container.

**Debug resolved config:**

```bash
soothe --debug "test"
soothed doctor
```

## See Also

- [Common Patterns](common-patterns.md) — zero-config and production recipes
- [YAML Reference](yaml-reference.md) — `router_profiles` schema
- [Daemon Setup](../deployment/production-setup.md) — full stack deploy
- Source: `packages/soothe/src/soothe/config/settings.py`, `packages/soothe-daemon/src/soothe_daemon/config/settings.py`

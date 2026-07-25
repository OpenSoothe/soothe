---
title: "Quick Start"
parent: Getting Started
grand_parent: Wiki
nav_order: 2
description: Install the CLI, start the daemon, and run your first prompt.
---

# Quick Start

Install the CLI, start the daemon, send a prompt. Python 3.11+.

---

## 1. Install the CLI

```bash
pip install -U soothe-cli
```

---

## 2. Start the daemon

Choose your deployment option below. All options run the daemon on port `8765`.

### Option A: Docker (OpenAI — zero-config)

Default model: `gpt-4o-mini`. No config file required.

```bash
docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e OPENAI_API_KEY=sk-... \
  -v soothe-data:/var/lib/soothe \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

### Option B: Docker (OpenAI-Compatible)

OpenAI-compatible endpoint using your provider's base URL.

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL="https://your-provider-endpoint/v1"

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e OPENAI_API_KEY \
  -e OPENAI_BASE_URL \
  -e SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"}}]' \
  -e SOOTHE_EMBEDDING_PROFILE='[{"model_role":"openai:text-embedding-3-small","embedding_dims":1536}]' \
  -v soothe-data:/var/lib/soothe \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

With workspace access (file tools):

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL="https://your-provider-endpoint/v1"
export HOST_WS="$HOME"
export CONTAINER_WS="/var/lib/soothe/workspaces"

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e OPENAI_API_KEY \
  -e OPENAI_BASE_URL \
  -e SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"}}]' \
  -e SOOTHE_EMBEDDING_PROFILE='[{"model_role":"openai:text-embedding-3-small","embedding_dims":1536}]' \
  -e SOOTHE_WORKSPACE_MOUNT="{\"host_root\":\"$HOST_WS\",\"container_root\":\"$CONTAINER_WS\"}" \
  -v soothe-data:/var/lib/soothe \
  -v "$HOST_WS:$CONTAINER_WS" \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

### Option C: Docker Compose (production full stack)

Production-ready stack with PostgreSQL + pgvector + Soothe daemon:

```bash
cd deploy
cp env-example .env
# Edit .env with your API keys
docker compose up -d
```

**Production stack components:**

| Component | Image | Port |
|-----------|-------|------|
| PostgreSQL + pgvector | `registry.cn-hangzhou.aliyuncs.com/lacogito/pgvector:pg17` | 5432 (internal) |
| Soothe Daemon | `registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest` | 8765 |

**Required environment variables** (in `deploy/.env`):

```bash
OPENAI_API_KEY=sk-...              # Required for production
OPENAI_BASE_URL=...                # Required for OpenAI-compatible providers
TAVILY_API_KEY=...                 # Optional (web search)
SOOTHE_WORKSPACE_HOST_ROOT=...     # Optional (default: $HOME)
SOOTHE_DEBUG=false                 # Optional (default: false)
```

**Persistence configuration** (production):

```yaml
# config/nano.yml (production)
persistence:
  default_backend: postgresql
  postgres_base_dsn: "postgresql://postgres:postgres@soothe-pgvector:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
  postgres:
    pool_min_size: 4
    checkpoints_pool_size: 32
    metadata_pool_size: 16
    vectors_pool_size: 16
  archive_enabled: true
  archive_retention_days: 90

agent:
  protocols:
    durability:
      backend: default
      checkpointer: default
      thread_inactivity_timeout_hours: 72
```

**PostgreSQL tuning** (production defaults):

```yaml
max_connections: 200
shared_buffers: 256MB
work_mem: 64MB
```

Full production deployment guide: see [`deploy/README.md`](../../../deploy/README.md).

---

### Option D: Local pip (development only)

> ⚠️ **Development use only.** For production, use Docker Compose (Option C).

```bash
pip install -U soothe soothe-daemon
export OPENAI_API_KEY=sk-...
soothed setup --yes   # scaffold nano.yml / soothe.yml / daemon.yml
soothed start
```

Or interactively (provider endpoint, key, model picker):

```bash
soothed setup
soothed start
```

Minimal daemon config is written by setup (`~/.soothe/config/daemon.yml`):

```yaml
transports:
  websocket:
    enabled: true
    host: 127.0.0.1
    port: 8765
```

#### D1: PostgreSQL (localhost — development)

For a local PostgreSQL database (port 5432):

```bash
# Create database
createdb soothe

# Start daemon with PostgreSQL backend
SOOTHE_PERSISTENCE_DEFAULT_BACKEND="postgresql" \
SOOTHE_PERSISTENCE_POSTGRES_BASE_DSN="postgresql://user:password@localhost:5432" \
soothed start
```

Or with config file (`~/.soothe/config/nano.yml`):

```yaml
persistence:
  default_backend: postgresql
  postgres_base_dsn: "postgresql://user:password@localhost:5432"
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
```

#### D2: SQLite (localhost — development)

For a lightweight SQLite database (no external dependency):

```bash
# Start daemon with SQLite backend (default)
soothed start
```

SQLite is the default backend. No configuration required.

Purpose databases live under `~/.soothe/data/databases/` (`checkpoints.db`,
`context.db`, `display.db`, `cron.db`, `identity.db`, `metadata.db`,
`persist.db`, `vectors.db`). Upgrading from older builds that used flat
`~/.soothe/data/*.db` files requires deleting those legacy files; there is
no automatic import.

Full reference: [Environment variables](../configuration-guide/environment-variables.md).

### Verify

```bash
curl -sf http://127.0.0.1:8765/healthz
```

---

## Persistence Verification Notes

### Key Persistence Parameters

| Parameter | Production (Docker Compose) | Development (SQLite) |
|-----------|------------------------------|----------------------|
| `default_backend` | `postgresql` | `sqlite` (default) |
| `archive_enabled` | `true` | `true` |
| `archive_retention_days` | 90 | 90 |
| `postgres.checkpoints_pool_size` | 32 | N/A |
| `thread_inactivity_timeout_hours` | 72 | 72 |

### Checkpoint & Durability

The daemon persists loop state automatically:

```yaml
agent:
  loop:
    checkpoint:
      progressive: true        # Incremental checkpoint writes
      auto_resume_on_start: false  # Manual resume required
  protocols:
    durability:
      backend: default          # Uses persistence.default_backend
      checkpointer: default     # Uses persistence backend
      thread_inactivity_timeout_hours: 72  # Cleanup threshold
```

### Vector Store Configuration

Default SQLite vector store:

```yaml
vector_stores:
- name: sqlite_vec_default
  provider_type: sqlite_vec
  index_type: hnsw

vector_store_router:
  default: sqlite_vec_default:soothe_default
```

For production PostgreSQL with pgvector:

```yaml
vector_stores:
- name: pgvector_default
  provider_type: pgvector
  dsn: "postgresql://postgres:postgres@soothe-pgvector:5432/soothe_vectors"

vector_store_router:
  default: pgvector_default:soothe_vectors
```

### Daemon Lifecycle Management

The daemon automatically manages stale resources:

| Setting | Default | Purpose |
|---------|---------|---------|
| `loop_gc.interval_seconds` | 3600 | Garbage collect ephemeral/empty loops hourly |
| `loop_gc.ephemeral_idle_hours` | 24 | Threshold for ephemeral loop cleanup |
| `loop_status_reconciliation.stale_running_seconds` | 180 | Demote stale `running` loops (no heartbeat) |
| `stale_worker_reap.interval_seconds` | 1800 | Cleanup idle workers every 30 min |

---

## 3. Run a prompt

```bash
soothe -p "Research top 5 Python web frameworks"
soothe   # interactive TUI
```

---

## Optional: Custom configuration

Prefer the setup wizard (scaffolds all three files and configures a provider):

```bash
soothed setup
```

Re-run anytime to modify or add providers without wiping unrelated keys. For a fresh copy of packaged templates over existing files, use `soothed setup --force`.

The daemon loads agent config from `SOOTHE_DAEMON_SOOTHE_CONFIG_PATH` or `~/.soothe/config/nano.yml` (composed with sibling `soothe.yml` when present).

---

## Next

| Guide | What you get |
|-------|----------------|
| [Installation](Installation.md) | Pip options, packages, verification, troubleshooting |
| [Language Clients](../clients.md) | Python / TypeScript / Go / Rust WebSocket SDKs |
| [Basic Concepts](Basic-Concepts.md) | Goals, loops, subagents, context |
| [Configuration guide](../configuration-guide/index.md) | YAML, providers, patterns |
| [CLI reference](../cli-reference.md) | All commands |
| [TUI guide](../tui-guide.md) | Interactive terminal UI |

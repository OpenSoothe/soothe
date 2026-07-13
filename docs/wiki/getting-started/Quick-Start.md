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

### Option B: Docker (DashScope)

OpenAI-compatible endpoint using `qwen3.7-plus`.

```bash
export DASHSCOPE_API_KEY=sk-...

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e OPENAI_API_KEY="$DASHSCOPE_API_KEY" \
  -e OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]' \
  -v soothe-data:/var/lib/soothe \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

With workspace access (file tools):

```bash
export DASHSCOPE_API_KEY=sk-...
export HOST_WS="$HOME"
export CONTAINER_WS="/var/lib/soothe/workspaces"

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e OPENAI_API_KEY="$DASHSCOPE_API_KEY" \
  -e OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]' \
  -e SOOTHE_WORKSPACE_MOUNT="{\"host_root\":\"$HOST_WS\",\"container_root\":\"$CONTAINER_WS\"}" \
  -v soothe-data:/var/lib/soothe \
  -v "$HOST_WS:$CONTAINER_WS" \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

### Option C: Docker Compose (dev environment)

Dev environment with PostgreSQL + pgvector:

```bash
# Start with default profile (pgvector only)
docker compose up -d

# Or with daemon included (after building image)
docker compose --profile daemon up -d
```

Environment variables (set in shell or `.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | — |
| `DASHSCOPE_API_KEY` | DashScope API key | — |
| `POSTGRES_PASSWORD` | PostgreSQL password | `postgres` |
| `POSTGRES_PORT` | PostgreSQL port | `6432` |

### Option D: Docker Compose (production full stack)

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
DASHSCOPE_API_KEY=sk-...           # Required for production
DASHSCOPE_BASE_URL=...             # Required for production
TAVILY_API_KEY=...                 # Optional (web search)
SOOTHE_WORKSPACE_HOST_ROOT=...     # Optional (default: $HOME)
SOOTHE_DEBUG=false                 # Optional (default: false)
```

**Database configuration** (production):

```yaml
# deploy/config.prod.yml (mounted at /app/config.yml)
database:
  backend: postgresql
  url: postgresql://postgres:postgres@soothe-pgvector:5432/soothe
  pool_size: 8
  vector:
    url: postgresql://postgres:postgres@soothe-pgvector:5432/soothe_vectors
```

**PostgreSQL tuning** (production defaults):

```yaml
max_connections: 200
shared_buffers: 256MB
work_mem: 64MB
```

Full production deployment guide: see [`deploy/README.md`](../../../deploy/README.md).

### Option E: Local pip

```bash
pip install -U soothe soothe-daemon
export OPENAI_API_KEY=sk-...
soothed start
```

Minimal daemon config (`~/.soothe/config/daemon.yml`):

```yaml
transports:
  websocket:
    enabled: true
    host: 127.0.0.1
    port: 8765
```

#### Option E1: PostgreSQL (localhost)

For a local PostgreSQL database (port 5432):

```bash
# Create database
createdb soothe

# Start daemon with PostgreSQL backend
SOOTHE_DATABASE_URL="postgresql://user:password@localhost:5432/soothe" soothed start
```

Or with config file (`~/.soothe/config/daemon.yml`):

```yaml
transports:
  websocket:
    enabled: true
    host: 127.0.0.1
    port: 8765

database:
  backend: postgresql
  url: postgresql://user:password@localhost:5432/soothe
```

#### Option E2: SQLite (localhost)

For a lightweight SQLite database (no external dependency):

```bash
# Start daemon with SQLite backend
SOOTHE_DATABASE_URL="sqlite:///./soothe.db" soothed start
```

Or with config file (`~/.soothe/config/daemon.yml`):

```yaml
transports:
  websocket:
    enabled: true
    host: 127.0.0.1
    port: 8765

database:
  backend: sqlite
  path: ./soothe.db
```

Full reference: [Environment variables](../configuration-guide/environment-variables.md).

### Verify

```bash
curl -sf http://127.0.0.1:8765/healthz
```

---

## 3. Run a prompt

```bash
soothe -p "Research top 5 Python web frameworks"
soothe   # interactive TUI
```

---

## Optional: Custom configuration

Copy the template config for multi-provider routing:

```bash
mkdir -p ~/.soothe/config
cp config/config.template.yml ~/.soothe/config/config.yml
```

Edit `~/.soothe/config/config.yml` to add providers, models, and router profiles. The daemon loads config from `SOOTHE_CONFIG_PATH` or `~/.soothe/config/config.yml`.

---

## Next

| Guide | What you get |
|-------|----------------|
| [Installation](Installation.md) | Pip options, packages, verification, troubleshooting |
| [Basic Concepts](Basic-Concepts.md) | Goals, loops, subagents, context |
| [Configuration guide](../configuration-guide/index.md) | YAML, providers, patterns |
| [CLI reference](../cli-reference.md) | All commands |
| [TUI guide](../tui-guide.md) | Interactive terminal UI |

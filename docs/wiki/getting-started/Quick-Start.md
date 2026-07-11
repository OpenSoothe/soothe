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

Docker image: `registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest`

### Docker — OpenAI (zero-config)

Default model: `gpt-4o-mini`. No config file required.

```bash
docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e OPENAI_API_KEY=sk-... \
  -v soothe-data:/var/lib/soothe \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
```

### Docker — DashScope

Uses the OpenAI-compatible endpoint. Router targets are `openai:qwen3.7-plus` (not `dashscope:…`).

```bash
export DASHSCOPE_API_KEY=sk-...
export HOST_WS=/Users/you/Workspace
export CONTAINER_WS=/var/lib/soothe/workspaces
export SOOTHE_ROUTER_PROFILES='[{"name":"default","router":{"default":"openai:qwen3.7-plus","fast":"openai:qwen3.7-plus","think":"openai:qwen3.7-plus"},"embedding_dims":1536}]'
export SOOTHE_WORKSPACE_MOUNT="{\"host_root\":\"$HOST_WS\",\"container_root\":\"$CONTAINER_WS\"}"

docker run --rm -d --name soothed \
  -p 8765:8765 \
  -e DASHSCOPE_API_KEY \
  -e OPENAI_API_KEY="$DASHSCOPE_API_KEY" \
  -e OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e SOOTHE_ROUTER_PROFILES \
  -e SOOTHE_WORKSPACE_MOUNT \
  -v soothe-data:/var/lib/soothe \
  -v "$HOST_WS:$CONTAINER_WS" \
  registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest

cd /Users/you/Workspace/soothe && soothe
```

Chat-only (no file tools): omit `HOST_WS`, `CONTAINER_WS`, `SOOTHE_WORKSPACE_MOUNT`, and the workspace `-v`.

### Local (pip)

```bash
pip install -U 'soothe[all]' soothe-daemon
export OPENAI_API_KEY=sk-...
soothed start
```

More env vars and Compose setups: [Environment variables](../configuration-guide/environment-variables.md).

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

## Production

Full stack (PostgreSQL + pgvector + config templates): [`deploy/`](../../../deploy/README.md) or [Production setup](../deployment/production-setup.md).

```bash
cd deploy && cp env-example .env && vim .env && docker compose up -d
```

Optional: copy `config/config.template.yml` to `~/.soothe/config/config.yml` for multi-provider routing.

---

## Next

| Guide | What you get |
|-------|----------------|
| [Installation](Installation.md) | Pip options, packages, verification, troubleshooting |
| [Basic Concepts](Basic-Concepts.md) | Goals, loops, subagents, context |
| [Configuration guide](../configuration-guide/index.md) | YAML, providers, patterns |
| [CLI reference](../cli-reference.md) | All commands |
| [TUI guide](../tui-guide.md) | Interactive terminal UI |

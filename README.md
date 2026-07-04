<div align="center">
  <img src="assets/soothe-logo.png" alt="Soothe Logo" width="280" />

  #

  [![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mirasoth/soothe)

  🎥 [Watch the demo video on Vimeo](https://player.vimeo.com/video/1185023866?h=72febe1ed2)
</div>

✨ Soothe is an **agent-harnessing framework**—an *Agentic OS* that pushes humans **out of the execution loop**.
Built on LangChain / DeepAgents, it adds a persistent **agentic loop** and **goal engine** that maintains context across sessions, sustains long-running goals, coordinates multiple objectives, and autonomously steers complex tasks. Shift from *human-in-the-loop* to **agent-in-the-loop**: define intent, let the system handle execution.

---

## ✨ Design Pillars

Five design choices make Soothe more than another agent loop.

- 🎯 **Goal-driven, natively** — A goal is a first-class, persisted entity: a 7-state lifecycle in a typed dependency DAG (`depends_on` / `informs` / `conflicts_with`), not a prompt string. Three-level execution keeps the loop a pure, fungible unit that knows nothing about sibling goals or scheduling; the daemon dispatches one goal at a time. You interact with **loops**, and thread IDs are an internal detail.
- 🔁 **Strange-loop cognitive architecture** — StrangeLoop is a compiled LangGraph graph—not an imperative `while` loop—running plan → assess → execute per goal with **goal-pull** flow: it actively pulls the next ready goal and reports back. Two-phase planning (cheap assessment, then conditional generation, skipped when done) saves tokens; evidence-bound steps validate before execute. The sharp line: the loop is the *runner*, not the consciousness.
- 🧠 **Unified context engine** — One DAG is the sole source of truth for goals, steps, **and** the message ledger—the ledger is derivable from step-execution records, not a parallel store. Lineage is first-class: every goal and step stores the reasoning that created it, so projections show *why*, not just *what*. Bounded structured projection plus in-place thread compaction handle the context window—complementary, not overlapping.
- 🔄 **Autopilot & long-term working** — A persistent daemon owns 24/7 state: `/detach` keeps a loop running while your client exits, and crash recovery bounds re-execution loss to one bundle of work per goal. Async backoff reasons over failures without blocking the scheduler, and a Layer-3 consensus loop double-checks "is it really done?" with a send-back budget. *Dreaming mode (memory consolidation, goal anticipation) is in progress.*
- 🌐 **Standard WebSocket protocol** — A published AsyncAPI 3.0 spec is the single source of truth: Pydantic wire schemas are generated from it and a CI drift check keeps code and spec in lockstep. Hybrid envelope (`proto/type/method/params/id`), schema validation at the transport boundary, capability negotiation with `readiness_state`, and a full `subscribe → next → complete` lifecycle. One wire contract, no compatibility shims.

## What Can Soothe Do?

| Capability | Features |
|------------|----------|
| **Autonomous Execution** | Multi-step workflows, file ops, code execution, shell commands |
| **Long-Running Ops** | Background daemon, thread/loop management, persistent state, `/detach` / `/reattach` |
| **Custom Plugins** | `@tool`, `@subagent`, `@plugin` decorators, MCP server integration |

## Milestones

| Status | Milestone |
|--------|-----------|
| ✅ | **Single-Session Autonomy** — End-to-end goal execution |
| ✅ | **Cross-Thread Continuity** — Persistent context across threads |
| ✅ | **Multi-Goal Orchestration** — Interdependent long-horizon workflows |
| ⏳ | **Benchmark Reproduction** — [Compiler experiment](https://github.com/anthropics/claudes-c-compiler) |  

## Quick Start

1. **Install the CLI** (Python 3.11+):

   ```bash
   pip install -U soothe-cli
   ```

2. **Start the daemon** (Docker, env-only — no config file):

   Image: `registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest`

   **OpenAI** (default model `gpt-4o-mini` via zero-config):

   ```bash
   docker run --rm -d --name soothed \
     -p 8765:8765 \
     -e OPENAI_API_KEY=sk-... \
     -v soothe-data:/var/lib/soothe \
     registry.cn-hangzhou.aliyuncs.com/lacogito/soothed:latest
   ```

   **DashScope** (`qwen3.7-plus` via `SOOTHE_ROUTER_PROFILES`; mount host workspace for file tools):

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

   DashScope uses the OpenAI-compatible endpoint; zero-config names the provider `openai`, so router targets are `openai:qwen3.7-plus` (not `dashscope:…`). Chat-only without a workspace mount: omit the `HOST_WS` / `CONTAINER_WS` / `SOOTHE_WORKSPACE_MOUNT` exports and the workspace `-v` — the CLI can still send `cwd`; the daemon ignores host paths that are missing in the container.

   **Local (pip)** instead of Docker:

   ```bash
   pip install -U 'soothe[all]' soothe-daemon
   export OPENAI_API_KEY=sk-...
   soothed start
   ```

   More env vars and Compose setups: [Configuration guide](docs/wiki/configuration-guide/environment-variables.md).

3. **Verify** the daemon:

   ```bash
   curl -sf http://127.0.0.1:8765/healthz
   ```

4. **Run a prompt:**

   ```bash
   soothe -p "Research top 5 Python web frameworks"
   # or interactive TUI:
   soothe
   ```

### Production deployment

Full stack (PostgreSQL + pgvector + config templates): [`deploy/`](deploy/README.md).

```bash
cd deploy && cp env-example .env && vim .env && docker compose up -d
```

Optional: copy `config/config.template.yml` to `~/.soothe/config/config.yml` for multi-provider routing and deployment overrides.

## Documentation

| Resource | Description |
|----------|-------------|
| [Configuration guide](docs/wiki/configuration-guide/) | YAML, env vars, zero-config |
| [User Guide](docs/user_guide.md) | End-user usage guide |
| [RFCs](docs/specs/) | Architecture specs |
| [CLAUDE.md](CLAUDE.md) | AI agent dev guide |

## License

MIT

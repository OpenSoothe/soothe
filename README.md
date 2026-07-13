<div align="center">
  <img src="assets/soothe-logo.png" alt="Soothe Logo" width="280" />

  #

  [![CI](https://github.com/mirasoth/soothe/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mirasoth/soothe/actions/workflows/ci.yml)
  [![PyPI version](https://img.shields.io/pypi/v/soothe)](https://pypi.org/project/soothe/)
  [![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mirasoth/soothe)

  🎥 [Watch the demo video on Vimeo](https://player.vimeo.com/video/1185023866?h=72febe1ed2) · 📖 [Documentation Wiki](https://mirasoth.github.io/soothe/)
</div>

✨ Soothe is a **goal-driven orchestration framework**—an *Agentic OS* for 24/7 autonomous work that keeps humans out of the execution loop. Built on LangChain and DeepAgents, it adds a persistent **agentic loop** and **goal engine**: context carries across sessions, long-running goals keep moving, interdependent objectives coordinate in a typed dependency graph, and complex tasks steer themselves to completion. Move from *human-in-the-loop* to **agent-in-the-loop**—define intent, let Soothe handle execution.

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

```bash
pip install -U soothe-cli
soothe -p "Your first task"   # requires a running daemon
```

**[Quick Start guide](docs/wiki/getting-started/Quick-Start.md)** — install, Docker (OpenAI / DashScope), local daemon, health check, production deploy.

## Documentation

| Resource | Description |
|----------|-------------|
| [Wiki](https://mirasoth.github.io/soothe/) | User, operator, and developer guides ([source](docs/wiki/index.md)) |
| [Quick Start](docs/wiki/getting-started/Quick-Start.md) | Install, daemon, first prompt |
| [Configuration guide](docs/wiki/configuration-guide/) | YAML, env vars, zero-config |
| [User Guide](docs/user_guide.md) | End-user usage guide |
| [RFCs](docs/specs/) | Architecture specs |
| [CLAUDE.md](CLAUDE.md) | AI agent dev guide |

## License

MIT

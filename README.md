<div align="center">
  <img src="docs/assets/soothe-logo.png" alt="Soothe Logo" width="200" />

  #

  [![CI](https://github.com/mirasoth/soothe/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mirasoth/soothe/actions/workflows/ci.yml)
  [![PyPI version](https://img.shields.io/pypi/v/soothe)](https://pypi.org/project/soothe/)
  [![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mirasoth/soothe)

  🎥 [Watch the demo video on Vimeo](https://player.vimeo.com/video/1185023866?h=72febe1ed2) · 📖 [Documentation Wiki](https://mirasoth.github.io/soothe/)
</div>

> **Define intent. Let Soothe handle the rest.**

Soothe is a **goal-driven orchestration framework** for 24/7 autonomous agents. It keeps humans out of the execution loop: you describe *what* you want, and Soothe plans, executes, and steers the work to completion — across sessions, across goals, across time.

Built on [soothe-nano](https://github.com/mirasoth/soothe-nano) and an [enhanced deepagents](https://github.com/mirasoth/soothe-deepagents), it adds a persistent **agentic loop** and **goal engine**: context carries across sessions, long-running goals keep moving, and interdependent objectives coordinate through a typed dependency graph. Move from *human-in-the-loop* to **agent-in-the-loop**.

---

## ✨ Vision

We believe autonomous agents should work the way great teams do: given a clear objective, they plan, act, remember, and adapt — without someone watching every step.

Soothe is built on five ideas:

- 🎯 **Goals, not prompts** — A goal is a first-class, persisted entity with its own lifecycle, not a string in a prompt. Soothe tracks dependencies between goals, coordinates them, and keeps each one moving.
- 🔁 **A loop that thinks** — StrangeLoop is a compiled plan → assess → execute graph that actively pulls the next ready goal and reports back. Two-phase planning keeps it frugal; evidence-bound steps keep it honest.
- 🧠 **One memory, one truth** — A single DAG is the source of truth for goals, steps, and the message ledger. Every record stores the reasoning that created it, so projections show *why*, not just *what*.
- 🔄 **Always-on, never-loses** — A persistent daemon owns 24/7 state. `/detach` keeps a loop running while your client exits; crash recovery bounds re-execution loss to one bundle of work per goal.
- 🌐 **One wire contract** — A published AsyncAPI 3.0 spec is the single source of truth for the WebSocket protocol. Schema validation at the transport boundary, capability negotiation, full `subscribe → next → complete` lifecycle. No compatibility shims.

---

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

---

## Quick Start

```bash
pip install -U soothe-cli soothe-daemon
soothed setup
soothed start
soothe -p "Your first task"   # requires a running daemon
```

Or submit a long-running Autopilot job from a `GOAL.md`:

```bash
soothed start
cd /path/to/repo
soothe autopilot submit -f GOAL.md --rail greenfield-system
soothe autopilot top   # live jobs / goals / loops dashboard
```

📖 **[Quick Start guide](docs/wiki/getting-started/Quick-Start.md)** — install, Docker, local daemon, first prompt.

### Language clients

| | Package | Latest |
|--|---------|--------|
| Python | [`soothe-client-python`](https://pypi.org/project/soothe-client-python/) | [![PyPI](https://img.shields.io/pypi/v/soothe-client-python.svg)](https://pypi.org/project/soothe-client-python/) |
| TypeScript | [`@mirasoth/soothe-client`](https://www.npmjs.com/package/@mirasoth/soothe-client) | [![npm](https://img.shields.io/npm/v/@mirasoth/soothe-client.svg)](https://www.npmjs.com/package/@mirasoth/soothe-client) |
| Go | [`soothe-client-go`](https://github.com/mirasoth/soothe-client-go) | [![Go](https://img.shields.io/github/v/release/mirasoth/soothe-client-go?label=go)](https://github.com/mirasoth/soothe-client-go/releases) |
| Rust | [`soothe-client`](https://crates.io/crates/soothe-client) | [![crates.io](https://img.shields.io/crates/v/soothe-client.svg)](https://crates.io/crates/soothe-client) |

📖 **[Clients guide](docs/wiki/clients.md)** — install, API tiers, protocol notes.

---

## Documentation

| Resource | Description |
|----------|-------------|
| [Wiki](https://mirasoth.github.io/soothe/) | User, operator, and developer guides |
| [Quick Start](docs/wiki/getting-started/Quick-Start.md) | Install, daemon, first prompt |
| [Language clients](docs/wiki/clients.md) | Python / TypeScript / Go / Rust WebSocket SDKs |
| [Configuration guide](docs/wiki/configuration-guide/) | YAML, env vars, zero-config |
| [RFCs](docs/specs/) | Architecture specs |
| [AGENTS.md](AGENTS.md) | AI agent dev guide |

## License

MIT

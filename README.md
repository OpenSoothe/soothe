# ✨ Soothe — Beyond Yet-Another Agent

<div align="center">
  <img src="assets/soothe-logo.png" alt="Soothe Logo" width="350" />

  #

  [![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
  [![soothe](https://img.shields.io/pypi/v/soothe?label=soothe)](https://pypi.org/project/soothe/)
  [![soothe-daemon](https://img.shields.io/pypi/v/soothe-daemon?label=soothe-daemon)](https://pypi.org/project/soothe-daemon/)
  [![soothe-cli](https://img.shields.io/pypi/v/soothe-cli?label=soothe-cli)](https://pypi.org/project/soothe-cli/)
  [![soothe-sdk](https://img.shields.io/pypi/v/soothe-sdk?label=soothe-sdk)](https://pypi.org/project/soothe-sdk/)
  [![License](https://img.shields.io/github/license/mirasoth/soothe)](https://github.com/mirasoth/soothe/blob/main/LICENSE)
  [![GitHub Stars](https://img.shields.io/github/stars/mirasoth/soothe)](https://github.com/mirasoth/soothe)
  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mirasoth/soothe)

  🎥 [Watch the demo video on Vimeo](https://player.vimeo.com/video/1185023866?h=72febe1ed2)
</div>

Soothe is an **agent-harnessing framework**—an *Agentic OS* that pushes humans **out of the execution loop**.

Built on LangChain / DeepAgents, it adds a persistent **agentic loop** and **goal engine** that maintains context across sessions, sustains long-running goals, coordinates multiple objectives, and autonomously steers complex tasks.

Shift from *human-in-the-loop* to **agent-in-the-loop**: define intent, let the system handle execution.

---

## 🚀 Key Features

- ✨ **Thinks Ahead** — Multi-step planning with dynamic adaptation
- 🚀 **Acts Autonomously** — Research, coding, file ops, plugin automation
- 🧠 **Learns & Remembers** — Persistent memory across sessions
- 🔒 **Stays Secure** — Least-privilege, local-first architecture
- 🔌 **Extends Easily** — Decorator-based plugins, custom tools, subagents
- 🌐 **Works Anywhere** — Multi-transport daemon (WebSocket, HTTP REST)

## Architecture

<div align="center">
  <img src="assets/logical-arch.png" alt="Arch" width="800" />
</div>

**Core Stack**: CLI → Daemon → Agent Loop → Goal Engine → Protocols → Backends → Capabilities (tools/subagents/MCP)

## Design Philosophy

| Principle | Description |
|-----------|-------------|
| **Plan → Execute** | Autonomous loop: plan, act, evaluate, adapt |
| **Persistent Memory** | Resume threads, recall context, track goals |
| **Security First** | Local execution, least-privilege policies |
| **Plugin Architecture** | Decorator-based tools, subagents, MCP servers |

## What Can Soothe Do?

| Capability | Features |
|------------|----------|
| **Deep Research** | Multi-source web search, academic papers (arXiv, DeepXiv), document analysis |
| **Autonomous Execution** | Multi-step workflows, file ops, code execution, shell commands |
| **Long-Running Ops** | Background daemon, thread management, persistent state |
| **Custom Plugins** | `@tool`, `@subagent`, `@plugin` decorators, MCP server integration |

## Milestones

| Status | Milestone |
|--------|-----------|
| ✅ | **Single-Session Autonomy** — End-to-end goal execution |
| ✅ | **Cross-Thread Continuity** — Persistent context across threads |
| ✅ | **Multi-Goal Orchestration** — Interdependent long-horizon workflows |
| ⏳ | **Benchmark Reproduction** — [Compiler experiment](https://github.com/anthropics/claudes-c-compiler) |  

## Getting Started

### Installation

Monorepo packages:

| Package | Purpose |
|---------|---------|
| `soothe` | Core agent framework + daemon server |
| `soothe-daemon` | Standalone daemon (WebSocket/HTTP) |
| `soothe-cli` | CLI client + TUI |
| `soothe-sdk` | SDK for plugins & custom clients |
| `soothe-community` | Community plugins ([separate repo](https://github.com/mirasoth/soothe-community)) |

```bash
# Full install
pip install -U 'soothe[all]'

# Or minimal
pip install soothe soothe-cli
```

### Quick Start

**1. Configure**:

```bash
mkdir -p ~/.soothe/config
cp config/config.template.yml ~/.soothe/config/config.yml
export OPENAI_API_KEY="sk-..."  # or ANTHROPIC_API_KEY, DASHSCOPE_API_KEY
```

**2. Run**:

```bash
# Start daemon
soothed start

# Interactive TUI
soothe

# Single prompt
soothe -p "Research top 5 Python web frameworks"
```

**Commands**:

| Command | Description |
|---------|-------------|
| `soothe` | Interactive TUI |
| `soothe -p "query"` | Single prompt |
| `soothed start/stop/status` | Daemon management |
| `soothed doctor` | Health diagnostics |

## Documentation

| Resource | Description |
|----------|-------------|
| [User Guide](docs/user_guide.md) | End-user usage guide |
| [RFCs](docs/specs/) | Architecture specs |
| [CLAUDE.md](CLAUDE.md) | AI agent dev guide |

## License

MIT

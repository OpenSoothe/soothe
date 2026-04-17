# ✨ Soothe — Beyond Yet-Another Agent

<div align="center">
  <img src="assets/soothe-logo.png" alt="Soothe Logo" width="350" />

  #

  [![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
  [![PyPI Version](https://img.shields.io/pypi/v/soothe)](https://pypi.org/project/soothe/)
  [![License](https://img.shields.io/github/license/caesar0301/Soothe)](https://github.com/caesar0301/Soothe/blob/main/LICENSE)
  [![GitHub Stars](https://img.shields.io/github/stars/caesar0301/Soothe)](https://github.com/caesar0301/Soothe)
  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/caesar0301/Soothe)

</div>

Soothe is **not** another Claude Code / OpenClaw clone.

Its ambition is to become an **agent-harnessing framework**, an *Agentic OS*, designed to push humans **out of the execution loop**.

After months of real-world "vibe coding" with coding agents, a clear pain emerged:  
humans are still responsible for holding everything together, driving agents across sessions, verifying intermediate results, recovering lost context, re-aligning goals, and manually relaying critical information between tools and skills. This constant supervision creates a heavy cognitive burden.

**Soothe was built to eliminate that loop.**

Instead of treating agents as isolated executors, Soothe introduces a higher-order orchestration layer. Built on top of LangChain / DeepAgents, it adds a persistent **agentic loop** and **goal engine** that can:

- maintain context across sessions  
- sustain and recover long-running goals  
- coordinate multiple objectives simultaneously  
- autonomously steer complex, long-horizon tasks  

In short, Soothe shifts the paradigm from *human-in-the-loop* to **agent-in-the-loop** systems—where humans define intent, and the system handles execution, continuity, and adaptation.

---

## 🚀 Key Features

- ✨ **Thinks Ahead** — Plans multi-step workflows and adapts dynamically based on outcomes  
- 🚀 **Acts Autonomously** — Executes tasks across research, coding, file ops, and browser automation  
- 🧠 **Learns & Remembers** — Persistent memory across sessions—no more repeating yourself  
- 🔒 **Stays Secure** — Enforces least-privilege access and keeps data under your control  
- 🔌 **Extends Easily** — Plugin system for custom tools and specialized sub-agents  
- 🌐 **Works Anywhere** — Multi-transport daemon (Unix, WebSocket, HTTP REST)

## Architecture

<div align="center">
  <img src="assets/logical-arch.png" alt="Arch" width="800" />
</div>

## Design Philosophy

**Plan → Execute**: Autonomous execution loop that plans, acts, evaluates, and adapts without manual intervention.

**Persistent Memory**: Sessions accumulate knowledge. Resume threads, recall context, and track long-running goals across conversations.

**Security First**: Local execution with least-privilege policies. Your infrastructure, your data, your control.

**Plugin Architecture**: Built-in tools for web search, code execution, and browser automation. Extend with custom plugins via decorator APIs.

## What Can Soothe Do?

**Deep Research**: Multi-source web search, academic papers, document analysis with automatic synthesis and citations.

**Autonomous Execution**: Multi-step workflows with automatic planning, file operations, code execution, and browser automation.

**Long-Running Operations**: Background daemon mode with thread management, persistent state, and resume capabilities.

**Custom Plugins**: Extend with decorator-based tools, specialized subagents, and MCP server integration.

## Milestones

- ✅ **Single-Session Autonomy** — Solve a complex goal end-to-end within a single session, fully out of the human loop  
- ⏳ **Cross-Session Continuity** — Sustain and complete complex tasks across multiple sessions with persistent context  
- ⏳ **Multi-Goal Orchestration** — Handle multiple interdependent goals over long-horizon workflows  
- ⏳ **Benchmark Reproduction** — Reproduce the Anthropic C Compiler [experiment](https://github.com/anthropics/claudes-c-compiler)  

## Getting Started

### Installation

Soothe is published as a monorepo with multiple packages:

- **`soothe`** (PyPI) — Main package: daemon server + CLI
- **`soothe-cli`** — Standalone WebSocket client
- **`soothe-sdk`** — Shared SDK for custom clients
- **`soothe-community`** — Optional community plugins

Install the main package:

```bash
pip install soothe
```

### Quick Start

1. **Configure your LLM provider**:

   ```bash
   # Create config directory
   mkdir -p ~/.soothe/config

   # Copy minimal config template
   cp config.minimal.yml ~/.soothe/config/config.yml

   # Set your API key
   export OPENAI_API_KEY="sk-..."
   # or export ANTHROPIC_API_KEY="sk-ant-..."
   # or export DASHSCOPE_API_KEY="sk-..."

   # Edit config with your preferred models
   vim ~/.soothe/config/config.yml
   ```

   The minimal config contains just essentials: provider settings and model router. All other settings use sensible defaults.

2. **Run your first query**:

   ```bash
   # Interactive TUI (default)
   soothe

   # Single-prompt mode
   soothe -p "Research the top 5 Python web frameworks and create a comparison table"
   ```

### Daemon Mode

For long-running operations and remote access:

```bash
# Start daemon server
soothe-daemon start

# Check daemon status
soothe-daemon status

# Run client (connects to daemon)
soothe

# Stop daemon
soothe-daemon stop
```

## Learn More

### 📚 Documentation

- **[Wiki](docs/wiki/)** - End-user guides organized by topic
  - [Getting Started](docs/wiki/getting-started.md) - Installation and first steps
  - [CLI Reference](docs/wiki/cli-reference.md) - Complete command documentation
  - [Configuration](docs/wiki/configuration.md) - Environment variables and YAML config
  - [Troubleshooting](docs/wiki/troubleshooting.md) - Common issues and solutions

- **[User Guide](docs/user_guide.md)** - Comprehensive usage guide with examples

- **[RFCs & Specs](docs/specs/)** - Technical specifications and architecture design
  - [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) - System conceptual design
  - [RFC-200](docs/specs/RFC-200-agentic-goal-execution.md) - Execution architecture
  - [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) - Plugin system design

### 🛠️ For Developers

- **[CLAUDE.md](CLAUDE.md)** - Development guide for AI agents
- **[Implementation Guides](docs/impl/)** - Detailed implementation documentation

## License

MIT

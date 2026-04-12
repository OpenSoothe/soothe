# Soothe

<div align="center">
  <img src="assets/soothe-logo.png" alt="Soothe Logo" width="350" />

  #

  [![Python](https://img.shields.io/pypi/pyversions/soothe)](https://pypi.org/project/soothe/)
  [![PyPI Version](https://img.shields.io/pypi/v/soothe)](https://pypi.org/project/soothe/)
  [![License](https://img.shields.io/github/license/caesar0301/Soothe)](https://github.com/caesar0301/Soothe/blob/main/LICENSE)
  [![GitHub Stars](https://img.shields.io/github/stars/caesar0301/Soothe)](https://github.com/caesar0301/Soothe)
  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/caesar0301/Soothe)

</div>

**Your 24/7 Autonomous AI Agent that Plans, Acts, and Delivers Results**

## What is Soothe?

Soothe is a protocol-driven AI orchestration framework that transforms how you work with AI. Unlike traditional chatbots that merely answer questions, Soothe acts as your intelligent digital colleague that:

- ✨ **Thinks Ahead** - Automatically plans multi-step workflows and adapts strategies based on results
- 🚀 **Acts Autonomously** - Executes complex tasks spanning web research, code execution, file operations, and browser automation
- 🧠 **Learns & Remembers** - Maintains persistent memory across sessions, so you never repeat yourself
- 🔒 **Stays Secure** - Enforces least-privilege policies and keeps your data under your control
- 🔌 **Extends Easily** - Plugin architecture lets you add custom tools and specialized subagents
- 🌐 **Works Anywhere** - Multi-transport daemon supports Unix, WebSocket, and HTTP REST connections

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

## Getting Started

### Quick Start

1. **Install Soothe**:
   ```bash
   pip install soothe
   ```
2. **Initialize config**:
   ```bash
   # Create Soothe home directory
   mkdir -p ~/.soothe/config

   # Copy minimal config template
   cp config.minimal.yml ~/.soothe/config/config.yml

   # Edit with your preferred provider and models
   vim ~/.soothe/config/config.yml  # or use your favorite editor
   ```

   The minimal config file contains just the essentials: provider settings and model router. All other settings use sensible defaults.

3. **Run your first task**:
   ```bash
   # Interactive TUI mode (default)
   soothe -p "Research the top 5 Python web frameworks and create a comparison table"

   # Or just launch TUI and type your query
   soothe
   ```

### Background Daemon

For long-running operations and remote access:

```bash
# Start daemon
soothe daemon start

# Attach from any terminal
soothe daemon attach

# Or connect via WebSocket/HTTP
soothe daemon start --enable-websocket --enable-http
```

## Architecture Highlights

Soothe is built on a **protocol-driven architecture** that ensures flexibility and maintainability:

```
┌─────────────────────────────────────────────────────────┐
│  CLI / TUI Layer (User Interface)                       │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Daemon Layer (Multi-Transport Server)                  │
│  Unix Socket | WebSocket | HTTP REST                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Core Framework (Agent Factory & Runner)                │
│  Plan → Execute Loop                                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Protocol Layer (8 Swappable Protocols)                 │
│  Context | Memory | Planning | Policy | Durability |    │
│  Remote | Persistence | VectorStore                     │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Capability Layer (Plugins)                             │
│  Tools | Subagents | MCP Servers                        │
└─────────────────────────────────────────────────────────┘
```

**Why This Matters**:
- **Swap any component** without changing your code
- **Add custom capabilities** via the plugin system
- **Scale from local CLI to remote daemon** seamlessly
- **Maintain isolation** between threads and sessions

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
  - [RFC-201](docs/specs/RFC-201-agentic-goal-execution.md) - Execution architecture
  - [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) - Plugin system design

### 🛠️ For Developers

- **[CLAUDE.md](CLAUDE.md)** - Development guide for AI agents
- **[Implementation Guides](docs/impl/)** - Detailed implementation documentation

## License

MIT

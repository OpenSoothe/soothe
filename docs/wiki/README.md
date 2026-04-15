# Soothe Wiki

Welcome to the Soothe end-user wiki. This directory contains comprehensive guides organized by topic to help you get the most out of Soothe.

## 🎯 Quick Navigation

**New to Soothe?** Start here → [Getting Started Guide](getting-started.md)

**Looking for a specific command?** → [CLI Reference](cli-reference.md)

**Having issues?** → [Troubleshooting Guide](troubleshooting.md)

---

## Wiki Index

### 🚀 Getting Started

| Guide | What You'll Learn |
|-------|-------------------|
| **[Getting Started](getting-started.md)** | Install, configure, and run your first session with Soothe |
| **[CLI Reference](cli-reference.md)** | Complete command-line interface documentation with examples |
| **[TUI Guide](tui-guide.md)** | Terminal UI usage, slash commands, keyboard shortcuts |

### 🤖 Core Capabilities

| Guide | What You'll Learn |
|-------|-------------------|
| **[Autonomous Mode](autonomous-mode.md)** | Enable autonomous iteration for complex multi-step tasks |
| **[Specialized Subagents](subagents.md)** | Browser automation, research, planning, and skill creation |
| **[Thread Management](thread-management.md)** | Work with conversation threads, resume previous sessions |

### 🔧 Configuration & Management

| Guide | What You'll Learn |
|-------|-------------------|
| **[Configuration](configuration.md)** | Environment variables, YAML config, model routing |
| **[Daemon Management](daemon-management.md)** | Manage the Soothe daemon lifecycle (start, stop, attach) |
| **[Multi-Transport Setup](multi-transport.md)** | Configure Unix Socket, WebSocket, and HTTP REST transports |
| **[Authentication](authentication.md)** | External authentication with reverse proxies |

### 🛠️ Troubleshooting & Advanced

| Guide | What You'll Learn |
|-------|-------------------|
| **[Troubleshooting](troubleshooting.md)** | Common issues, error messages, and solutions |
| **[Query Processing Flow](query-processing-flow.md)** | How user queries flow through the system architecture |

---

## Key Concepts

### Execution Modes

Soothe provides multiple execution modes for different use cases:

| Mode | When to Use | Command |
|------|-------------|---------|
| **Default (TUI)** | Standard tasks, research, file operations | `soothe -p "your query"` or just `soothe` |
| **Headless** | Quick one-off queries, scripts | `soothe -p "your query" --no-tui` |
| **Autonomous** | Complex multi-step workflows | `soothe autopilot run "your query"` |
| **Daemon** | Background operations, remote access | `soothe-daemon start` |

Learn more: [Getting Started](getting-started.md#execution-modes)

### Architecture Overview

Soothe uses a **Plan → Execute** execution loop:

```
User Query → PLAN (LLM plans, assesses progress, decides steps) → EXECUTE (execute tools)
                ↑                                                                                ↓
                └────────────────── Retry/Adjust ←───────────────────────┘
```

**Key Benefits**:
- Automatic strategy adjustment based on results
- Structured tool outputs for reliable evaluation
- Sub-second responses for simple queries
- Intelligent iteration for complex tasks

Learn more: [RFC-201: Agentic Loop Execution](../specs/RFC-201-agentic-loop-execution.md)

### Plugin System

Soothe's extensible architecture allows you to add custom capabilities:

```python
from soothe_sdk import plugin, tool

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_tool", description="Custom tool")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"
```

Learn more: [RFC-600: Plugin Extension System](../specs/RFC-600-plugin-extension-system.md)

---

## Feature Status

| Feature | Status | Documentation |
|---------|--------|---------------|
| **Intelligent Execution Loop** | ✅ Production Ready | [RFC-201](../specs/RFC-201-agentic-loop-execution.md) |
| **Research Subagent** | ✅ Production Ready | [Subagents Guide](subagents.md#research-subagent) |
| **Plugin System** | ✅ Production Ready | [RFC-600](../specs/RFC-600-plugin-extension-system.md) |
| **Multi-Transport Daemon** | ✅ Production Ready | [Multi-Transport Setup](multi-transport.md) |
| **Thread Management** | ✅ Production Ready | [Thread Management](thread-management.md) |
| **Security Policies** | ✅ Production Ready | [RFC-102](../specs/RFC-102-secure-filesystem-policy.md) |
| **Autonomous Mode** | 🚧 Experimental | [Autonomous Mode](autonomous-mode.md) |

---

## Additional Resources

### 📖 Extended Documentation

- **[User Guide](../user_guide.md)** - Comprehensive usage guide with detailed examples
- **[RFCs & Specifications](../specs/)** - Technical architecture and design documents
- **[Implementation Guides](../impl/)** - Development documentation

### 🔗 External Links

- **[PyPI Package](https://pypi.org/project/soothe/)** - Install the latest version
- **[GitHub Repository](https://github.com/caesar0301/Soothe)** - Source code and issues
- **[DeepWiki](https://deepwiki.com/caesar0301/Soothe)** - AI-powered documentation search

---

## Getting Help

### Common Issues

- **API key errors**: See [Configuration](configuration.md#api-keys)
- **Connection errors**: See [Troubleshooting](troubleshooting.md#connection-errors)
- **Performance issues**: See [Troubleshooting](troubleshooting.md#performance)

### Community

- **Report issues**: [GitHub Issues](https://github.com/caesar0301/Soothe/issues)
- **Ask questions**: Use GitHub Discussions or check the Troubleshooting guide

---

## Contributing

Interested in contributing to Soothe? See:

- **[CLAUDE.md](../../CLAUDE.md)** - Development guide for AI agents
- **[RFCs](../specs/)** - Architecture design documents
- **[Implementation Guides](../impl/)** - Development documentation
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

✨ **Thinks Ahead** - Automatically plans multi-step workflows and adapts strategies based on results
🚀 **Acts Autonomously** - Executes complex tasks spanning web research, code execution, file operations, and browser automation
🧠 **Learns & Remembers** - Maintains persistent memory across sessions, so you never repeat yourself
🔒 **Stays Secure** - Enforces least-privilege policies and keeps your data under your control
🔌 **Extends Easily** - Plugin architecture lets you add custom tools and specialized subagents
🌐 **Works Anywhere** - Multi-transport daemon supports Unix, WebSocket, and HTTP REST connections

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRESENTATION LAYER                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │     CLI     │  │     TUI     │  │   Daemon    │  │    REST API         │ │
│  │  (click)    │  │ (textual)   │  │  (asyncio)  │  │   (fastapi)         │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│                         ORCHESTRATION LAYER                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                    Agent Factory (create_soothe_agent)                  ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  ││
│  │  │   Context   │  │   Memory    │  │   Planner   │  │     Policy     │  ││
│  │  │  Protocol   │  │  Protocol   │  │  Protocol   │  │   Protocol     │  ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────────┘  ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  ││
│  │  │ Durability  │  │   Remote    │  │ Concurrency │  │ Vector Store   │  ││
│  │  │  Protocol   │  │   Agent     │  │   Policy    │  │   Protocol     │  ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│                          FRAMEWORK LAYER                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         deepagents Framework                            ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  ││
│  │  │   Backend   │  │  Middleware │  │  SubAgent   │  │ Summarization  │  ││
│  │  │  Protocol   │  │   System    │  │   System    │  │   Middleware   │  ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│                          RUNTIME LAYER                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  LangChain  │  │  LangGraph  │  │   LiteLLM   │  │  External Protocols │ │
│  │   (tools)   │  │  (graphs)   │  │   (models)  │  │  (MCP, A2A, ACP)    │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Design Philosophy

### 🎯 Intelligent by Default

Soothe uses a **PLAN → ACT → JUDGE** execution loop that automatically:
- Analyzes your request and decides the best approach
- Executes tools with structured outputs for reliable results
- Evaluates success and adjusts strategy without manual intervention
- Works for simple queries in milliseconds or complex tasks in minutes

No micromanagement needed—just state your goal and let Soothe deliver.

### 🧠 Persistent Memory & Context

Every conversation builds upon the last:
- **Session memory**: Accumulates knowledge within a thread
- **Cross-session memory**: Recalls important context from past interactions
- **Thread management**: Resume, archive, and organize conversation history
- **Goal tracking**: Long-running objectives persist across sessions

### 🔒 Security & Privacy First

Your infrastructure, your rules:
- **Local execution**: Browser automation, file operations, and code execution run on your machine
- **Policy enforcement**: Fine-grained access control with least-privilege defaults
- **No vendor lock-in**: Bring your own API keys, storage backends, and models
- **Flexible deployment**: Run as CLI, daemon, or integrate into your applications

### 🔌 Extensible Plugin System

Soothe grows with your needs:
- **Built-in tools**: Web search (Tavily, DuckDuckGo), code execution, file operations, browser automation
- **Specialized subagents**: Research, browser automation, planning, and more
- **MCP integration**: Connect to external services via Model Context Protocol
- **Custom plugins**: Create your own tools and subagents with decorator-based APIs

## What Can Soothe Do?

### 🔍 Deep Research & Synthesis
**Multi-source investigation in minutes, not hours**
- Web search with intelligent query generation (Tavily, DuckDuckGo)
- Academic paper discovery (ArXiv integration)
- Document analysis (PDF, DOCX, text files)
- Automatic summarization with citations
- Iterative refinement based on findings

**Example**: *"Research the latest advances in RAG architectures and compare three different approaches"*

### 🤖 Autonomous Task Execution
**From goal to deliverable without hand-holding**
- Multi-step workflow execution with automatic planning
- File operations with security policy enforcement
- Code execution in sandboxed environments
- Browser automation for web interactions
- Parallel tool execution for faster results

**Example**: *"Set up a new Python project with FastAPI, create the directory structure, and initialize git"*

### 📊 Long-Running Operations
**Work that spans hours or days, managed automatically**
- Background daemon mode with multi-transport support
- Thread management with resume capabilities
- Persistent state across sessions
- Progress tracking and artifact storage

**Example**: *"Monitor this website every 6 hours and alert me when the price drops below $50"*

### 🎨 Extensible via Plugins
**Custom capabilities for your unique workflows**
- Decorator-based tool creation (`@tool`)
- Subagent development with `CompiledSubAgent`
- MCP server integration for external services
- Custom event types and handlers

**Example**: Create a custom tool that queries your internal APIs and processes results

## Getting Started

### Quick Start (3 Steps)

1. **Install Soothe**:
   ```bash
   pip install soothe
   ```

2. **Set your API key**:
   ```bash
   export OPENAI_API_KEY=sk-your-key-here
   # or use Anthropic Claude:
   export ANTHROPIC_API_KEY=sk-ant-your-key-here
   ```

3. **Run your first task**:
   ```bash
   # Interactive TUI mode (default)
   soothe -p "Research the top 5 Python web frameworks and create a comparison table"

   # Or just launch TUI and type your query
   soothe
   ```

### Try Different Modes

**Interactive TUI** (default):
```bash
soothe -p "Analyze this codebase and suggest improvements"
```

**Headless single-shot**:
```bash
soothe -p "What is 2 + 2?" --no-tui
```

**Autonomous mode** for complex tasks:
```bash
soothe autopilot run "Set up a monitoring system that checks website uptime every 5 minutes"
```

The TUI shows:
- Tool execution in real-time
- Subagent activities and progress
- Structured event stream
- Keyboard shortcuts for control

### Run as a Background Daemon

For long-running operations and remote access:

```bash
# Start daemon
soothe daemon start

# Attach from any terminal
soothe daemon attach

# Or connect via WebSocket/HTTP
soothe daemon start --enable-websocket --enable-http
```

## Real-World Examples

### Research Workflow
```bash
# Default mode with automatic planning
soothe -p "Research best practices for securing REST APIs, summarize the top 5 recommendations, and create a checklist document"
```

### Codebase Analysis
```bash
# TUI mode shows real-time progress
soothe -p "Analyze the authentication module in src/auth/, identify potential security vulnerabilities, and suggest fixes"
```

### Autonomous Mode (Complex Tasks)
```bash
# Use autopilot for autonomous execution
soothe autopilot run "Set up a monitoring system that checks website uptime every 5 minutes and logs results to a database"
```

### Resume Previous Work
```bash
# List previous threads
soothe thread list

# Continue from where you left off
soothe thread continue <thread-id>
```

## Key Features

| Feature | Status | Description |
|---------|--------|-------------|
| **Intelligent Execution Loop** | ✅ Implemented | PLAN → ACT → JUDGE architecture with automatic strategy adjustment |
| **Multi-Source Research** | ✅ Implemented | Web search, academic papers, documents with automatic synthesis |
| **Specialized Subagents** | ✅ Implemented | Browser automation, planning, research, skill creation |
| **Plugin System** | ✅ Implemented | Decorator-based tools and subagents with lifecycle management |
| **Multi-Transport Daemon** | ✅ Implemented | Unix socket, WebSocket, and HTTP REST support |
| **Thread Management** | ✅ Implemented | Persistent threads with resume, archive, and search |
| **Security Policies** | ✅ Implemented | Least-privilege access control with configurable policies |
| **Persistent Memory** | ✅ Implemented | Context and memory across sessions with vector storage support |

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
│  PLAN → ACT → JUDGE Loop                                │
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

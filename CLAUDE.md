# Soothe Development Guide for AI Agents

> **Purpose**: This guide helps AI coding agents work effectively on the Soothe codebase.

---

## 🎯 Project Overview

**Soothe** is a protocol-driven orchestration framework for building 24/7 long-running autonomous agents. It extends deepagents with planning, context engineering, security policy, durability, and remote agent interop while remaining langchain-ecosystem-friendly.

**Key Architecture**: See [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) for the full conceptual design.

---

## ⚠️ CRITICAL RULES - READ FIRST

### 1. MUST Create Implementation Guide
**Before implementing ANY plan or refactoring task**, create a new implementation guide in `docs/impl/`:
- Naming: `NNN-brief-title.md` (NNN = next available number)
- Purpose: Track all implementation work
- Example: This document guides all code changes

### 2. MUST Keep Config Files Synchronized
**When updating `packages/soothe/src/soothe/config/config.yml` (template)**, you MUST also update `config.dev.yml` in the project root (dev defaults):
- Both files must have matching structure
- Dev config should have sensible defaults for local development
- This ensures developers see the latest configuration options

### 3. Ecosystem Dependencies
**DO NOT reinvent modules** if langchain ecosystem already provides them:
- Tools: Use `langchain.BaseTool` or `@tool` decorator
- Subagents: Use `deepagents.SubAgent` or `CompiledSubAgent`
- MCP: Use `langchain-mcp-adapters`
- Skills: Use `deepagents.SkillsMiddleware`
- Memory: Use `deepagents.MemoryMiddleware`
- Check: `langchain-core`, `langchain-community`, `deepagents` first!

### 3. Verification Before Commit
**MANDATORY**: Run verification script after ANY code change:
```bash
./scripts/verify_finally.sh
```
This runs:
- Code formatting check
- Linting (zero errors required)
- Unit tests (900+ tests must pass)

**NEVER commit code without running this verification first!**

### 4. Talking style

1. Think before acting. Read existing files before writing code.
2. Be concise in output but thorough in reasoning.
3. Prefer editing over rewriting whole files.
4. Do not re-read files you have already read.
5. Test your code before declaring done.
6. No sycophantic openers or closing fluff.
7. Keep solutions simple and direct.
8. User instructions always override this file.
9. **NEVER use "layer N" terminology** - Use concrete module names instead:
   - "Layer 1" → "CoreAgent"
   - "Layer 2" → "AgentLoop"
   - "Layer 3" → "GoalEngine" or "autonomous goal management"
   - Apply to: docstrings, comments, log messages, parameter names, documentation
   - Example: `agentloop_result` instead of `layer2_result`

---

## 🏗️ Architecture at a Glance

### Layer Stack (Bottom to Top)

```
┌─────────────────────────────────────────────────────────┐
│  CLI Layer (cli/)                                        │
│  - Typer app, commands/, TUI, execution                  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Daemon Layer (daemon/)                                  │
│  - Multi-transport server (Unix, WebSocket, HTTP REST)  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Core Framework (core/)                                  │
│  - Agent factory, runner, resolver, events               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Protocol Layer (protocols/)                             │
│  - 8 runtime-agnostic protocol definitions              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Backends Layer (backends/)                              │
│  - Protocol implementations (context, memory, etc.)     │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Capability Layer (subagents/, tools/, mcp/)            │
│  - Subagents, tools, MCP servers                        │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  deepagents + langchain / langgraph                     │
└─────────────────────────────────────────────────────────┘
```

### Key Entry Points

| Entry Point | Location | Purpose |
|-------------|----------|---------|
| Agent Factory | `core/agent.py:create_soothe_agent()` | Main factory, returns `CompiledStateGraph` |
| Configuration | `config.py:SootheConfig` | Declarative config with `SOOTHE_` env prefix |
| CLI | `cli/main.py:app` | Typer app entry point |
| Runner | `core/runner.py:SootheRunner` | Protocol orchestration + streaming |

---

## 📁 Module Map

### Monorepo Structure
```
packages/
├── soothe-sdk/        # Shared SDK (WebSocket client, protocol, types, decorators)
├── soothe-cli/        # CLI client (Typer CLI + Textual TUI)
├── soothe/            # Daemon server (main package, reuses PyPI name)
└── soothe-community/  # Community plugins (optional)
```

### soothe Package (Daemon Server)
| Package | Purpose |
|---------|---------|
| `core/` | Framework logic (factory, runner, events, goal engine) |
| `protocols/` | 8 runtime-agnostic protocol definitions |
| `middleware/` | deepagents middleware wrappers |
| `utils/` | Shared runtime helpers |

### Backends (Protocol Implementations)
| Package | Implements |
|---------|------------|
| `backends/context/` | ContextProtocol (KeywordContext, VectorContext) |
| `backends/memory/` | MemoryProtocol (KeywordMemory, VectorMemory) |
| `cognition/planning/` | PlannerProtocol (Simple, Subagent, Claude, Auto) |
| `backends/policy/` | PolicyProtocol (ConfigDrivenPolicy) |
| `backends/durability/` | DurabilityProtocol (Json, RocksDB, PostgreSQL) |
| `core/remote_agent/` | RemoteAgentProtocol (LangGraphRemoteAgent) |
| `backends/persistence/` | PersistStore for context/memory/durability |
| `backends/vector_store/` | VectorStoreProtocol (PGVector, Weaviate, InMemory) |

### Capabilities
| Package | Contents |
|---------|----------|
| `subagents/` | Browser, Claude (deepagents SubAgents) |
| `tools/` | Tool groups (execution, websearch, research, etc.) |
| `mcp/` | MCP server loading and management |

### User Interface
| Package | Purpose |
|---------|---------|
| `cli/` | Daemon management CLI (start/stop/status/doctor) |
| `daemon/` | Multi-transport daemon server (WebSocket, HTTP) |

---

## 🔧 Configuration System

### SootheConfig (BaseSettings)
- **Environment prefix**: `SOOTHE_` (e.g., `SOOTHE_PROVIDERS__OPENAI__API_KEY`)
- **Config file**: YAML/JSON via `--config` flag
- **Secret injection**: `${ENV_VAR}` syntax in config values

### Key Methods
```python
config.resolve_model(role)          # Map purpose role to "provider:model"
config.create_chat_model(role)       # Instantiate langchain chat model
config.create_embedding_model()      # Instantiate embedding model
config.propagate_env()               # Set OPENAI_API_KEY for downstream libs
```

---

## 📚 Specifications (RFCs)

All RFCs are in `docs/specs/`. Key specifications:

| RFC | Title | Purpose |
|-----|-------|---------|
| [RFC-000](docs/specs/RFC-000-system-conceptual-design.md) | System Conceptual Design | Overall architecture |
| [RFC-001](docs/specs/RFC-001-core-modules-architecture.md) | Core Modules Architecture | Module interactions |
| [RFC-200](docs/specs/RFC-200-agentic-goal-execution.md) | Agentic Goal Execution (Layer 2) | Iteration patterns |
| [RFC-400](docs/specs/RFC-400-daemon-communication.md) | Daemon Communication Protocol | Multi-transport daemon |
| [RFC-400](docs/specs/RFC-400-event-processing.md) | Event Processing & Filtering | Event system |
| [RFC-600](docs/specs/RFC-600-plugin-extension-system.md) | Plugin Extension System | Plugin architecture |

**See all RFCs**: Check `docs/specs/` directory.

---

## 📝 Implementation Guides

All implementation guides are in `docs/impl/`. Recent guides:

| Guide | Title | Status |
|-------|-------|--------|
| IG-047 | Module Self-Containment Refactoring | ✅ Completed |
| IG-051 | Plugin API Implementation | ✅ Completed |
| IG-052 | RFC-600 Event System Optimization | ✅ Completed |

**See all guides**: Check `docs/impl/` directory.

---

## 🔌 Plugin System (RFC-600)

### Event Registration (NEW!)
Each module registers its own events using `register_event()`:

```python
from soothe.core.event_catalog import register_event
from soothe.core.base_events import SootheEvent

class MyCustomEvent(SootheEvent):
    type: str = "soothe.plugin.custom.event"
    data: str

# Register at module load time
register_event(MyCustomEvent, summary_template="Custom: {data}")
```

**Third-party plugins** can now register custom events without modifying core files!

### Plugin Structure
```python
from soothe_sdk.plugin import plugin, tool, subagent, register_event

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    async def on_load(self, context):
        # Initialize plugin
        pass

    @tool(name="my_tool", description="Does something")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"

    @subagent(name="my_agent", description="Custom agent")
    async def create_agent(self, model, config, context):
        # Return deepagents CompiledSubAgent
        pass
```

---

## 🚦 Development Workflow

### 1. Plan Mode
When in plan mode:
- **ASK for confirmation** when alternatives exist
- **EXPLORE the codebase** first
- **CREATE implementation guide** before starting
- **END with ExitPlanMode** for user approval

### 2. Implementation
1. Read existing code thoroughly
2. Check langchain ecosystem first
3. Follow existing patterns
4. Add type hints and docstrings
5. Run `make lint` frequently

### 3. Verification
```bash
# Run full verification suite
./scripts/verify_finally.sh

# Or run checks individually:
make format-check    # Check formatting
make lint            # Check linting (zero errors)
make test-unit       # Run 900+ tests
```

### 4. Commit
**Only after all checks pass!**

---

## 🎨 Code Standards

### Python Style
- **Python >=3.11**
- **Type hints** on all public functions
- **Google-style docstrings** with Args, Returns, Raises
- **Ruff** for linting and formatting
- **No bare `except:`** - use typed exception handling

### Docstring Format
```python
def my_function(arg: str, optional: int = 0) -> dict:
    """Brief description of function.

    Args:
        arg: Description of arg.
        optional: Description of optional parameter.

    Returns:
        Description of return value.

    Raises:
        ValueError: When arg is invalid.
    """
    pass
```

### Single Backticks
Use single backticks for inline code in docstrings (not Sphinx double backticks):
```python
# ✅ Good
"""Use `create_agent()` to instantiate."""

# ❌ Bad
"""Use ``create_agent()`` to instantiate."""
```

---

## 🛠️ What NOT to Implement

**Check these before implementing anything:**

### deepagents Provides
- File operations: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- Shell execution: `execute`
- Task tracking: `write_todos`
- SubAgent spawning: `task` tool
- Skills: SKILL.md discovery
- Memory: AGENTS.md loading
- Summarization: auto-compaction
- Middleware: TodoList, Filesystem, SubAgent, Summarization, PromptCaching
- Streaming: `agent.astream(stream_mode=["messages", "updates", "custom"], subgraphs=True)`

### langchain Provides
- Web search: `TavilySearchResults`, `DuckDuckGoSearchRun`
- ArXiv: `ArxivQueryRun`
- Wikipedia: `WikipediaQueryRun`
- GitHub: `GitHubAPIWrapper`
- Gmail: `GmailToolkit`
- Python REPL: `PythonREPLTool`
- Document loaders: `PyPDFLoader`, `Docx2txtLoader`, etc.
- Model init: `init_chat_model()`, `init_embeddings()`

---

## 📖 Configuration Reference

| File | Purpose |
|------|---------|
| [config/env.example](config/env.example) | All environment variables |
| [config/config.yml](config/config.yml) | Full YAML config example |
| [docs/user_guide.md](docs/user_guide.md) | End-user guide |

---

## 🐛 Debugging Tips

### Check Health
```bash
soothe doctor
```
Runs comprehensive health checks for daemon, protocols, persistence, and integrations.

### Verbose Logging
```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "your query"
```

### TUI Debug Mode
```bash
# TUI is default - just add --debug flag
soothe --debug "your query"
```

---

## 📦 Third-party Reference Code

The `thirdparty/` directory contains source code of upstream dependencies for **reference only**.
- **DO NOT** copy code from `thirdparty/`
- **DO NOT** import modules from `thirdparty/`
- **ONLY USE** to understand upstream APIs and behavior

---

## 🔄 Recent Changes

### IG-052: Event System Optimization (Just Completed)
- Created `register_event()` public API
- Migrated plugin/tool/subagent events to self-registration
- Reduced `event_catalog.py` by 12% (105 lines)
- Enabled third-party plugins to register custom events
- All tests passing ✅

### IG-051: Plugin API Implementation
- Implemented decorator-based plugin system
- Added plugin lifecycle management
- Created plugin discovery and loading

### IG-047: Module Self-Containment
- Moved events into their respective modules
- Converted tools to packages
- Eliminated redundant plugin shims

---

## 🎯 Quick Start for Common Tasks

### Adding a New Tool
1. Create package in `tools/my_tool/`
2. Add `__init__.py`, `events.py`, `implementation.py`
3. Use `@tool` decorator in plugin class
4. Register events with `register_event()`
5. Run `./scripts/verify_finally.sh`

### Adding a New Subagent
1. Create package in `subagents/my_agent/`
2. Add `__init__.py`, `events.py`, `implementation.py`
3. Use `@subagent` decorator in plugin class
4. Return `CompiledSubAgent` from factory
5. Run `./scripts/verify_finally.sh`

### Modifying Core Events
1. Check if event should be in core or module
2. If core: add to `core/event_catalog.py`
3. If module: add to module's `events.py`
4. Use `register_event()` for registration
5. Run `./scripts/verify_finally.sh`

---

## 💡 Key Design Principles

From RFC-000:

1. **Protocol-first, runtime-second** - Every module is a protocol; implementations are swappable
2. **Extend deepagents, don't fork it** - Use deepagents as-is
3. **Orchestration is the product** - Compose capabilities, don't implement domain logic
4. **Unbounded context, bounded projection** - Context ledger is unlimited; projections are bounded
5. **Durable by default** - Agent state is persistable and resumable
6. **Plan-driven execution** - Complex goals decompose into plans with steps
7. **Least-privilege delegation** - Every action passes through PolicyProtocol
8. **Controlled concurrency** - Parallel execution within configurable limits
9. **Uniform delegation envelope** - Local and remote subagents share the same interface
10. **Graceful degradation** - Partial results over hard failure

---

## 📋 Interaction Rules

### MUST Rules
1. **Create implementation guide** before implementing any plan
2. **Check langchain ecosystem** before implementing any functionality
3. **Run verification script** before committing any code
4. **Fix all linting errors** before committing
5. **Call platonic-coding skill** when generating plans and implementing code to follow spec-driven development workflow

### SHOULD Rules
1. **Ask for clarification** when requirements are ambiguous
2. **Read existing code** before proposing changes
3. **Follow existing patterns** in the codebase
4. **Add tests** for new functionality

### Plan Mode Behavior
- **CALL platonic-coding skill** to follow spec-driven development workflow
- **ASK for confirmation** when alternatives exist
- **EXPLORE thoroughly** before planning
- **USE AskUserQuestion** for clarifications
- **END with ExitPlanMode** for approval

---

## 🆘 Getting Help

- **Architecture questions**: Check RFCs in `docs/specs/`
- **Implementation patterns**: Check recent IGs in `docs/impl/`
- **API questions**: Check `thirdparty/` for upstream code
- **User guide**: See `docs/user_guide.md`
- **Issues**: Report at GitHub issues

---

**Remember**: When in doubt, read the code first, check the ecosystem second, and ask for clarification third! 🚀

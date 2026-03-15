# Soothe Development Rules

## Project Vision

Soothe is a protocol-driven orchestration framework for building 24/7 long-running autonomous
agents. It extends deepagents with planning, context engineering, security policy, durability,
and remote agent interop while remaining langchain-ecosystem-friendly. See
[RFC-0001](docs/specs/RFC-0001.md) for the full conceptual design.

## Design Principles (RFC-0001)

1. **Protocol-first, runtime-second** -- every module is a protocol; implementations are swappable.
2. **Extend deepagents, don't fork it** -- use deepagents as-is for what it provides.
3. **Orchestration is the product** -- compose capabilities, don't implement domain logic.
4. **Unbounded context, bounded projection** -- context ledger is unlimited; only projections are bounded.
5. **Durable by default** -- agent state is persistable and resumable.
6. **Plan-driven execution** -- complex goals decompose into plans with steps.
7. **Least-privilege delegation** -- every action passes through PolicyProtocol.
8. **Controlled concurrency** -- parallel execution within configurable limits.
9. **Uniform delegation envelope** -- local and remote subagents share the same interface.
10. **Graceful degradation** -- partial results over hard failure.

## Mandatory Constraints

- **Built on deepagents and langchain ecosystem.** DO NOT reinvent modules if the langchain
  ecosystem already provides them. Always check langchain-core, langchain-community, and
  deepagents before implementing any tool, middleware, or agent pattern.
- Subagents MUST use deepagents' `SubAgent` or `CompiledSubAgent` types.
- Tools MUST use langchain's `BaseTool` subclass or `@tool` decorator.
- MCP integration MUST use `langchain-mcp-adapters`.
- Skills MUST use deepagents' `SkillsMiddleware` (SKILL.md format).
- Memory MUST use deepagents' `MemoryMiddleware` (AGENTS.md format).
- Protocols MUST be defined as `typing.Protocol` with no runtime dependencies in signatures.
- All protocol implementations MUST be swappable via `SootheConfig`.

## Code Standards

- Python >=3.11, type hints on all public functions.
- Google-style docstrings with Args, Returns, Raises sections.
- Use `ruff` for linting and formatting.
- Unit tests for all new features; `pytest` with `asyncio_mode = "auto"`.
- No bare `except:`; use typed exception handling.
- Single backticks for inline code in docstrings (not Sphinx double backticks).

## Architecture

```
+--------------------------------------------------------------+
|  CLI Layer                                                    |
|  cli/main.py (Typer), cli/daemon.py,                        |
|  cli/tui_app.py, cli/tui.py, cli/commands.py, cli/session.py|
+--------------------------------------------------------------+
|  Core Framework (no CLI deps)                                |
|  core/agent.py (factory), core/runner.py (SootheRunner),    |
|  core/resolver.py (protocol resolution), core/events.py     |
+--------------------------------------------------------------+
|  Protocol Layer                                               |
|  protocols/: Context, Memory, Planner, Policy, Durability,  |
|  RemoteAgent, Concurrency, VectorStore                        |
+--------------------------------------------------------------+
|  Backends Layer                                               |
|  backends/context/, backends/memory/, backends/planning/,    |
|  backends/policy/, backends/durability/, backends/remote/,   |
|  backends/persistence/, backends/vector_store/               |
+--------------------------------------------------------------+
|  Capability Layer                                             |
|  subagents/ (planner, scout, research, browser, claude,     |
|              skillify, weaver)                                |
|  tools/ (jina, serper, image, audio, video, tabular)         |
|  mcp/ (MCP server loading)                                   |
+--------------------------------------------------------------+
|  deepagents + langchain / langgraph                          |
+--------------------------------------------------------------+
```

### Entry Points

- `create_soothe_agent()` in `core/agent.py` -- main factory, returns `CompiledStateGraph`
- `SootheConfig` in `config.py` -- declarative configuration (pydantic-settings, `SOOTHE_` prefix)
- `soothe` CLI in `cli/main.py` -- Typer app, entry point `soothe.cli:app`
- `SootheRunner` in `core/runner.py` -- protocol orchestration + streaming wrapper

### Configuration System

- `SootheConfig(BaseSettings)` with `env_prefix = "SOOTHE_"` for env var overrides
- YAML/JSON config file loaded via `--config` CLI flag
- `resolve_model(role)` maps purpose roles to `provider:model` strings
- `create_chat_model(role)` and `create_embedding_model()` instantiate langchain models
- `propagate_env()` sets `OPENAI_API_KEY`/`OPENAI_BASE_URL` for downstream libraries
- Provider `api_key` supports `${ENV_VAR}` syntax for secret injection

## Module Map

| Package | Contents | Purpose |
|---------|----------|---------|
| `core/` | `agent`, `runner`, `resolver`, `events`, `goal_engine` | Framework logic (factory, orchestration, resolution, goal lifecycle) |
| `protocols/` | `context`, `memory`, `planner`, `policy`, `durability`, `remote`, `concurrency`, `vector_store` | 8 runtime-agnostic protocol definitions |
| `backends/context/` | `KeywordContext`, `VectorContext` | ContextProtocol implementations |
| `backends/memory/` | `StoreBackedMemory`, `VectorMemory` | MemoryProtocol implementations |
| `backends/planning/` | `DirectPlanner`, `SubagentPlanner`, `ClaudePlanner`, `AutoPlanner` | PlannerProtocol implementations |
| `backends/policy/` | `ConfigDrivenPolicy` | PolicyProtocol implementations |
| `backends/durability/` | `InMemoryDurability` | DurabilityProtocol implementations |
| `backends/remote/` | `LangGraphRemoteAgent` | RemoteAgentProtocol implementations |
| `backends/persistence/` | `JsonPersistStore`, `RocksDBPersistStore` | Persistence backends for context/memory |
| `backends/vector_store/` | `PGVectorStore`, `WeaviateVectorStore`, `InMemoryVectorStore` | VectorStoreProtocol implementations |
| `subagents/` | `planner`, `scout`, `research`, `browser`, `claude`, `skillify`, `weaver` | deepagents SubAgent/CompiledSubAgent |
| `tools/` | `jina`, `serper`, `image`, `audio`, `video`, `tabular`, `goals` | langchain BaseTool groups |
| `mcp/` | `loader` | MCP server session management |
| `cli/` | `main`, `tui_shared`, `tui_app`, `daemon`, `commands`, `session` | Typer CLI + Textual TUI + Daemon |
| `middleware/` | `ContextMiddleware`, `PolicyMiddleware` | deepagents AgentMiddleware wrappers |
| `utils/` | `progress` | Shared runtime progress helper |

## What deepagents Provides (DO NOT reimplement)

- File operations: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- Shell execution: `execute`
- Task tracking: `write_todos`
- SubAgent spawning: `task` tool
- Skills: SKILL.md discovery
- Memory: AGENTS.md loading
- Summarization: auto-compaction
- Middleware: TodoList, Filesystem, SubAgent, Summarization, PromptCaching
- Streaming: `agent.astream(stream_mode=["messages", "updates", "custom"], subgraphs=True)`

## What langchain Provides (DO NOT reimplement)

- Web search: `TavilySearchResults`, `DuckDuckGoSearchRun`
- ArXiv: `ArxivQueryRun`
- Wikipedia: `WikipediaQueryRun`
- GitHub: `GitHubAPIWrapper`
- Gmail: `GmailToolkit`
- Python REPL: `PythonREPLTool`
- Document loaders: `PyPDFLoader`, `Docx2txtLoader`, etc.
- Model init: `init_chat_model()`, `init_embeddings()`

## CLI TUI Architecture (RFC-0003)

- `SootheRunner` wraps `create_soothe_agent()` with three-phase execution:
  pre-stream (context, memory, planner, policy), LangGraph stream pass-through
  with HITL interrupt loop, post-stream (ingestion, reflection, persistence).
- Protocol events are `((), "custom", {"type": "soothe.*", ...})` plain dicts
  in the deepagents-canonical `(namespace, mode, data)` stream format.
- **Daemon mode**: `SootheDaemon` in `daemon.py` runs `SootheRunner` in background,
  serves events over Unix domain socket (`~/.soothe/soothe.sock`).
- **Textual TUI**: `SootheApp` in `tui_app.py` connects to daemon, provides always-on
  two-column layout with ChatInput, ConversationPanel, PlanPanel, ActivityPanel.
- **Shared TUI helpers**: `tui_shared.py` provides shared activity/plan/subagent rendering utilities for the Textual app and commands.
- **Headless**: `_run_headless` renders `soothe.*` events as progress, supports `--format jsonl`.
- Slash commands and subagent routing in `commands.py`.
- Session logging (JSONL) and input history in `session.py`.

## Specifications and Implementation Guides

### RFCs

| RFC | Title |
|-----|-------|
| [RFC-0001](docs/specs/RFC-0001.md) | System Conceptual Design |
| [RFC-0002](docs/specs/RFC-0002.md) | Core Modules Architecture Design |
| [RFC-0003](docs/specs/RFC-0003.md) | CLI TUI Architecture Design |
| [RFC-0004](docs/specs/RFC-0004.md) | Skillify Agent Architecture Design |
| [RFC-0005](docs/specs/RFC-0005.md) | Weaver Agent Architecture Design |
| [RFC-0006](docs/specs/RFC-0006.md) | Context and Memory Architecture Design |
| [RFC-0007](docs/specs/RFC-0007.md) | Autonomous Iteration Loop |

### Implementation Guides

| Guide | Title |
|-------|-------|
| [IG-001](docs/impl/001-soothe-setup-migration.md) | Soothe Setup and Migration |
| [IG-002](docs/impl/002-soothe-polish.md) | Soothe Polish |
| [IG-003](docs/impl/003-streaming-examples.md) | Streaming Examples |
| [IG-004](docs/impl/004-ecosystem-capability-analysis.md) | Ecosystem Capability Analysis |
| [IG-005](docs/impl/005-core-protocols-implementation.md) | Core Protocols Implementation |
| [IG-006](docs/impl/006-vectorstore-router-persistence.md) | VectorStore, Router, Persistence |
| [IG-007](docs/impl/007-cli-tui-implementation.md) | CLI TUI Implementation |
| [IG-008](docs/impl/008-config-docs-revision.md) | Config and Docs Revision |
| [IG-009](docs/impl/009-ollama-provider.md) | Ollama Provider |
| [IG-010](docs/impl/010-tui-layout-history-refresh.md) | Textual TUI and Daemon Implementation |
| [IG-011](docs/impl/011-skillify-agent-implementation.md) | Skillify Agent Implementation |
| [IG-012](docs/impl/012-weaver-agent-implementation.md) | Weaver Agent Implementation |
| [IG-013](docs/impl/013-soothe-polish-pass.md) | Soothe Polish Pass |
| [IG-014](docs/impl/014-code-structure-revision.md) | Code Structure Revision |
| [IG-015](docs/impl/015-rfc-gap-closure-and-compat-hard-cut.md) | RFC Gap Closure and Compatibility Hard-Cut |
| [IG-016](docs/impl/016-agent-optimization-pass.md) | Agent Optimization Pass |
| [IG-017](docs/impl/017-progress-events-tools-polish.md) | Progress Events and Tools Polish |
| [IG-018](docs/impl/018-autonomous-iteration-loop.md) | Autonomous Iteration Loop |
| [IG-017](docs/impl/017-progress-events-tools-polish.md) | Progress Events and Tools Polish |

## Interaction Rules

- **Plan mode confirmation**: In plan mode, ALWAYS ask for the user's confirmation when
  there are alternative solutions or design trade-offs before proceeding.

## Third-party Reference Code

The `thirdparty/` directory contains source code of upstream dependencies
(deepagents, langchain, langgraph, browser-use, claude-agent-sdk, etc.)
for **reference only**. DO NOT copy code from or import modules in `thirdparty/`.
These are solely to help understand upstream APIs and behaviour.

### Configuration Reference

| File | Purpose |
|------|---------|
| [config/env.example](config/env.example) | All environment variables |
| [config/config.yml](config/config.yml) | Full YAML config example |
| [docs/user_guide.md](docs/user_guide.md) | End-user guide |

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
|  main.py (Typer), runner.py (SootheRunner),                  |
|  tui.py (Rich TUI), commands.py, session.py                 |
+--------------------------------------------------------------+
|  Agent Factory                                                |
|  create_soothe_agent() wraps create_deep_agent()             |
|  SootheConfig drives all wiring                               |
+--------------------------------------------------------------+
|  Protocol Layer                                               |
|  Context, Memory, Planner, Policy, Durability,               |
|  RemoteAgent, Concurrency, VectorStore                        |
+--------------------------------------------------------------+
|  Implementation Layer                                         |
|  context/, memory_store/, planning/, policy/,                |
|  durability/, remote/, middleware/, vector_store/,            |
|  persistence/                                                 |
+--------------------------------------------------------------+
|  Capability Layer                                             |
|  subagents/ (planner, scout, research, browser, claude)      |
|  tools/ (jina, serper, image, audio, video, tabular)         |
|  mcp/ (MCP server loading)                                   |
+--------------------------------------------------------------+
|  deepagents + langchain / langgraph                          |
+--------------------------------------------------------------+
```

### Entry Points

- `create_soothe_agent()` in `agent.py` -- main factory, returns `CompiledStateGraph`
- `SootheConfig` in `config.py` -- declarative configuration (pydantic-settings, `SOOTHE_` prefix)
- `soothe` CLI in `cli/main.py` -- Typer app, entry point `soothe.cli:app`
- `SootheRunner` in `cli/runner.py` -- protocol orchestration + streaming wrapper

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
| `protocols/` | `context`, `memory`, `planner`, `policy`, `durability`, `remote`, `concurrency`, `vector_store` | 8 runtime-agnostic protocol definitions |
| `context/` | `KeywordContext`, `VectorContext` | ContextProtocol implementations |
| `memory_store/` | `StoreBackedMemory`, `VectorMemory` | MemoryProtocol implementations |
| `planning/` | `DirectPlanner` | PlannerProtocol implementations |
| `policy/` | `ConfigDrivenPolicy` | PolicyProtocol implementations |
| `durability/` | `InMemoryDurability` | DurabilityProtocol implementations |
| `remote/` | `LangGraphRemoteAgent` | RemoteAgentProtocol implementations |
| `middleware/` | `ContextMiddleware`, `PolicyMiddleware` | deepagents AgentMiddleware wrappers |
| `subagents/` | `planner`, `scout`, `research`, `browser`, `claude`, `skillify`, `weaver` | deepagents SubAgent/CompiledSubAgent |
| `tools/` | `jina`, `serper`, `image`, `audio`, `video`, `tabular` | langchain BaseTool groups |
| `mcp/` | `loader` | MCP server session management |
| `cli/` | `main`, `runner`, `tui`, `tui_app`, `daemon`, `commands`, `session` | Typer CLI + Textual TUI + Daemon + SootheRunner |
| `vector_store/` | `PGVectorStore`, `WeaviateVectorStore`, `InMemoryVectorStore` | VectorStoreProtocol implementations |
| `persistence/` | `JsonStore`, `RocksDbStore` | Persistence backends for context/memory |
| `utils/` | `_streaming`, `_progress` | Shared streaming and progress helpers |

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
- **Legacy TUI**: `tui.py` provides Rich Live-based fallback when Textual unavailable.
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

### Configuration Reference

| File | Purpose |
|------|---------|
| [config/env.example](config/env.example) | All environment variables |
| [config/config.yml](config/config.yml) | Full YAML config example |
| [docs/user_guide.md](docs/user_guide.md) | End-user guide |

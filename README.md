# Soothe

A protocol-driven orchestration framework for building 24/7 long-running autonomous agents.
Built on [deepagents](https://github.com/deepagents-ai/deepagents) and the langchain/langgraph ecosystem.

## Architecture

```
+--------------------------------------------------------------+
|  Soothe  (orchestration framework)                           |
|  Protocols: Context, Memory, Planner, Policy, Durability,    |
|             RemoteAgent, Concurrency, VectorStore             |
|  CLI TUI:  SootheRunner, Rich Live display, slash commands   |
|  create_soothe_agent() wires everything together             |
+--------------------------------------------------------------+
|  deepagents  (agent framework)                               |
|  BackendProtocol, AgentMiddleware, SubAgent, Summarization   |
|  create_deep_agent()                                         |
+--------------------------------------------------------------+
|  langchain / langgraph  (runtime layer)                      |
|  BaseChatModel, BaseTool, StateGraph, Checkpointer           |
+--------------------------------------------------------------+
```

Soothe extends deepagents with seven core protocols that the ecosystem does not provide:
cognitive context engineering, cross-thread memory, plan-driven execution, least-privilege
policy, durable thread lifecycle, remote agent interop, and controlled concurrency.
It does not implement domain logic -- it composes capabilities provided by langchain tools,
MCP servers, deepagents subagents, and remote agents via ACP/A2A.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install

```bash
git clone <repository-url>
cd soothe
make sync        # or: uv sync --all-extras
```

### Configure

```bash
cp config/env.example .env       # set your API keys
cp config/config.yml my-config.yml  # customize as needed
```

At minimum, set `OPENAI_API_KEY` in `.env` (or export it in your shell).

### Run

```bash
# Interactive TUI mode
soothe run

# Single prompt (headless)
soothe run "Summarize the latest AI research papers"

# With config file and thread resume
soothe run --config my-config.yml --thread abc123
```

## Configuration

Soothe is configured through two mechanisms:

- **Environment variables** -- See [`config/env.example`](config/env.example) for the full list.
  `SOOTHE_*` vars map directly to `SootheConfig` fields via pydantic-settings.
  Provider and tool keys (`OPENAI_API_KEY`, `SERPER_API_KEY`, etc.) are standard env vars.

- **YAML config file** -- See [`config/config.yml`](config/config.yml) for a fully-commented
  example. Pass via `soothe run --config path/to/config.yml`. Supports `${ENV_VAR}` syntax
  in `providers[].api_key` for secret injection.

## CLI

| Command | Description |
|---------|-------------|
| `soothe run` | Interactive TUI with Rich Live display |
| `soothe run "prompt"` | Headless single-prompt mode |
| `soothe run --no-tui` | Headless interactive mode (no Rich) |
| `soothe thread list` | List all threads |
| `soothe thread archive <id>` | Archive a thread |
| `soothe list-subagents` | Show available subagents |
| `soothe config` | Display current configuration |

### TUI Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Commands and subagent selector |
| `/plan` | Show current task plan |
| `/memory` | Memory statistics |
| `/context` | Context statistics |
| `/policy` | Active policy profile |
| `/thread list` | List threads |
| `/thread resume <id>` | Resume a thread |
| `/config` | Active configuration |
| `/exit` | Exit |

Numeric prefix routes to subagents: `1`=Main, `2`=Planner, `3`=Scout, `4`=Research, `5`=Browser, `6`=Claude, `7`=Skillify, `8`=Weaver.

## Project Structure

```
src/soothe/
├── __init__.py               # Public API exports
├── config.py                 # SootheConfig (pydantic-settings)
├── protocols/                # Runtime-agnostic protocol definitions
├── backends/                 # Protocol implementations
│   ├── context/              # KeywordContext, VectorContext
│   ├── memory/               # StoreBackedMemory, VectorMemory
│   ├── planning/             # DirectPlanner
│   ├── policy/               # ConfigDrivenPolicy
│   ├── durability/           # InMemoryDurability
│   ├── remote/               # LangGraphRemoteAgent
│   ├── persistence/          # JSON, RocksDB stores
│   └── vector_store/         # PGVector, Weaviate
├── middleware/               # ContextMiddleware, PolicyMiddleware
├── core/                     # agent, runner, resolver, goal_engine (autonomous iteration)
├── subagents/                # planner, scout, research, browser, claude, skillify, weaver
├── tools/                    # jina, serper, image, audio, video, tabular, bash, file_edit, document, python_executor, goals, wizsearch
├── mcp/                      # MCP server loading
├── cli/                      # Typer CLI, SootheRunner, Rich TUI
├── built_in_skills/          # Built-in skill implementations
└── utils/                    # Streaming helpers
```

## Documentation

### Design Specifications

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
| [IG-010](docs/impl/010-tui-layout-history-refresh.md) | TUI Layout, History, and Refresh |
| [IG-011](docs/impl/011-skillify-agent-implementation.md) | Skillify Agent Implementation |
| [IG-012](docs/impl/012-weaver-agent-implementation.md) | Weaver Agent Implementation |
| [IG-013](docs/impl/013-soothe-polish-pass.md) | Soothe Polish Pass |
| [IG-014](docs/impl/014-code-structure-revision.md) | Code Structure Revision |
| [IG-015](docs/impl/015-rfc-gap-closure-and-compat-hard-cut.md) | RFC Gap Closure and Compatibility Hard-Cut |
| [IG-016](docs/impl/016-agent-optimization-pass.md) | Agent Optimization Pass |
| [IG-017](docs/impl/017-progress-events-tools-polish.md) | Progress Events and Tools Polish |
| [IG-018](docs/impl/018-autonomous-iteration-loop.md) | Autonomous Iteration Loop |
| [IG-019](docs/impl/019-soothe-tools-enhancement.md) | Soothe Tools Enhancement |

### User Guide

See [docs/user_guide.md](docs/user_guide.md) for the comprehensive end-user guide.

## Privacy

The Browser subagent uses [browser-use](https://github.com/browser-use/browser-use)
with **privacy-first defaults**: browser extensions, cloud services, and anonymous
telemetry are disabled by default. Re-enable them in the subagent config if needed:

```yaml
subagents:
  browser:
    enabled: true
    config:
      disable_extensions: false
      disable_cloud: false
      disable_telemetry: false
```

## Development

```bash
make help          # show all commands
make sync-dev      # sync dev dependencies
make format        # format code with ruff
make lint          # lint code with ruff
make test          # run all tests
make test-unit     # run unit tests only
make build         # build the package
```

### Infrastructure (for integration tests)

```bash
docker compose up -d    # starts PGVector + Weaviate
make test-integration   # requires --run-integration
```

## License

MIT

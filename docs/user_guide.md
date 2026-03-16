# Soothe User Guide

---

# Part 1: End-User Guide

## Introduction

Soothe is an intelligent AI assistant that can work autonomously on complex tasks. This guide will help you get started and make the most of Soothe's capabilities.

## Installation

### Basic Installation

Install Soothe with pip:

```bash
pip install soothe
```

### Set Your API Key

Soothe needs an API key to access AI models. Set your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

You can also create a `.env` file in your working directory:

```bash
OPENAI_API_KEY=sk-your-key-here
```

### Optional: Install from Source

For the latest development version:

```bash
git clone <repository-url>
cd soothe
make sync
```

## Basic Usage

### Interactive TUI Mode

Launch the interactive terminal interface:

```bash
soothe run
```

This opens a rich terminal UI where you can:
- See real-time progress as Soothe works
- View plans and task decomposition
- Track subagent activity
- Use slash commands for quick actions

Just type your request and press Enter. Soothe will process it and show you what it's doing.

### Headless Mode

Run a single prompt and exit:

```bash
soothe run "Research the latest developments in quantum computing"
```

This is useful for:
- Quick one-off queries
- Scripts and automation
- CI/CD pipelines
- Background jobs

### Resume a Previous Session

Continue from where you left off:

```bash
soothe run --thread abc123
```

Replace `abc123` with your thread ID (shown in previous sessions).

## TUI Interface

### Slash Commands

Type these commands in the interactive prompt:

| Command | Description |
|---------|-------------|
| `/help` | Show all commands and available subagents |
| `/auto <prompt>` | Run one prompt in autonomous mode |
| `/auto <max_iterations> <prompt>` | Run in autonomous mode with custom iteration limit |
| `/plan` | Show the current task plan |
| `/memory` | Show memory statistics |
| `/context` | Show context statistics |
| `/policy` | Show active policy profile |
| `/thread list` | List all conversation threads |
| `/thread resume <id>` | Resume a specific thread |
| `/thread archive <id>` | Archive a thread |
| `/config` | Show active configuration |
| `/session` | Show session log path |
| `/clear` | Clear the screen |
| `/exit` or `/quit` | Exit the TUI |

### Routing to Specialized Subagents

Prefix your message with a number to route to a specific subagent:

| Prefix | Subagent | Best For |
|--------|----------|----------|
| `1` | Main | General tasks (default) |
| `2` | Planner | Creating plans for complex goals |
| `3` | Scout | Quick file searches and code navigation |
| `4` | Research | Deep web research |
| `5` | Browser | Web browsing and automation |
| `6` | Claude | Tasks requiring Claude's strengths |
| `7` | Skillify | Retrieving relevant skills |
| `8` | Weaver | Generating specialized agents |

**Examples:**

```
4 Search for papers on transformer architectures
5 Open https://example.com and take a screenshot
2 Create a plan for building a REST API
```

Route to multiple subagents:

```
4,5 Find and visit the top 3 AI news sites
```

### Multi-Line Input

Continue your input on multiple lines by ending with `\`:

```
soothe> Write a function that \
...  takes a list of numbers \
...  and returns the median
```

### Keyboard Shortcuts

- `Ctrl+C` once: Cancel current task
- `Ctrl+C` twice: Exit the TUI

## Autonomous Iteration Mode

Soothe can work autonomously on complex tasks that require iterative refinement.

### When to Use Autonomous Mode

Use autonomous mode for tasks that:
- Require iterative refinement based on results
- Involve multi-phase research where findings inform next steps
- Need long-running workflows without manual intervention
- Decompose into sub-goals that emerge during execution

### How to Use It

Enable autonomous mode with the `--autonomous` flag:

```bash
# Autonomous iteration with default settings
soothe run --autonomous "Optimize the simulation parameters"

# With custom iteration limit
soothe run --autonomous --max-iterations 20 "Research quantum error correction advances"

# In TUI
/auto Optimize the simulation parameters
/auto 15 Research and improve model performance
```

### What Happens

1. Soothe creates a plan for your goal
2. Executes the plan step-by-step
3. Reflects on results after each iteration
4. Adjusts the plan if needed
5. Continues until the goal is achieved or iteration limit is reached

You'll see progress events:
- `soothe.iteration.started` - Iteration began
- `soothe.iteration.completed` - Iteration finished
- `soothe.goal.created` - New goal created
- `soothe.goal.completed` - Goal achieved
- `soothe.goal.failed` - Goal failed

### Configuration

Set defaults in your config:

```yaml
autonomous_enabled_by_default: false
autonomous_max_iterations: 10
autonomous_max_retries: 2
```

## Thread Management

### What Are Threads?

Threads are conversation sessions. Each thread maintains:
- Your conversation history
- Context and accumulated knowledge
- Memory of important findings
- Task plans and progress

### Listing Threads

```bash
soothe thread list
```

Or in the TUI:

```
/thread list
```

### Resuming Threads

Continue a previous conversation:

```bash
soothe run --thread abc123
```

Or in TUI:

```
/thread resume abc123
```

### Archiving Threads

Clean up old threads:

```bash
soothe thread archive abc123
```

Or in TUI:

```
/thread archive abc123
```

## Specialized Subagents

### Research Agent (Prefix: 4)

Deep web research using Tavily search. Automatically:
- Breaks queries into sub-searches
- Gathers sources
- Synthesizes findings

**Requires**: `pip install soothe[research]` + `TAVILY_API_KEY`

### Browser Agent (Prefix: 5)

Automated web browsing. Can:
- Navigate pages
- Fill forms
- Click elements
- Take screenshots

**Requires**: `pip install soothe[browser]`

**Privacy**: Extensions, cloud sync, and telemetry are disabled by default.

### Planner Agent (Prefix: 2)

Creates structured task plans. Best for:
- Complex multi-step goals
- Breaking down problems
- Planning with dependencies

### Scout Agent (Prefix: 3)

Lightweight exploration for:
- Quick file searches
- Code navigation
- Codebase understanding

### Claude Agent (Prefix: 6)

Direct access to Claude. Useful for:
- Long context reasoning
- Careful analysis

**Requires**: `pip install soothe[claude]` + `ANTHROPIC_API_KEY`

### Skillify Agent (Prefix: 7)

Skill warehouse and retrieval. Helps discover and apply:
- Previously learned patterns
- Reusable workflows
- Best practices

### Weaver Agent (Prefix: 8)

Agent generation system. Creates specialized agents for specific tasks.

## Examples

### Research Task

```
You: "Research the latest developments in quantum error correction and summarize the top 5 papers"

Soothe: [Searches databases, reads papers, synthesizes findings]
        "I've analyzed recent publications. Here are the top 5 papers on quantum error correction..."
```

### Multi-Step Workflow

```
You: "Find the top 3 AI news sites, visit each one, and create a summary of today's announcements"

Soothe: [Plans → Searches → Visits → Extracts → Summarizes]
        "I've visited TechCrunch AI, VentureBeat AI, and AI News. Here's today's summary..."
```

### Autonomous Operation

```
You: "Optimize the simulation parameters across the search space"

Soothe: [Creates plan → Runs iterations → Analyzes results → Refines approach]
        "After 15 iterations, I found the optimal configuration. Performance improved by 23%."
```

### File Analysis

```
You: "Analyze the codebase structure and identify the main components"

Soothe: [Explores directories → Reads key files → Builds mental model]
        "The codebase has three main components: protocols, backends, and tools..."
```

## Configuration

### Quick Configuration

For basic usage, you only need to set your API key:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

### Using a Config File

For more control, create a YAML config file:

```bash
cp config/config.yml my-config.yml
# Edit my-config.yml
soothe run --config my-config.yml
```

### Essential Settings

In `my-config.yml`, you can customize:

```yaml
# Model selection
router:
  default: "openai:gpt-4o-mini"

# Enable/disable subagents
subagents:
  research:
    enabled: true
  browser:
    enabled: true
  claude:
    enabled: false

# Progress verbosity
progress_verbosity: normal  # minimal | normal | detailed | debug
```

See the [Developer Guide](#part-2-developer-guide) for full configuration details.

## Troubleshooting

### API Key Issues

**Error**: `Could not resolve model openai:gpt-4o-mini`

**Solution**: Set your API key:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

### Browser Agent Not Working

**Solution**: Install the browser extra:

```bash
pip install soothe[browser]
```

### Research Agent Not Working

**Solution**: Install the research extra and set your Tavily key:

```bash
pip install soothe[research]
export TAVILY_API_KEY=tvly-your-key-here
```

### Debug Mode

Enable verbose logging to see what's happening:

```bash
export SOOTHE_DEBUG=true
soothe run
```

### Getting Help

- Use `/help` in the TUI to see available commands
- Check the [Developer Guide](#part-2-developer-guide) for advanced configuration
- Review the [documentation](docs/) for design specifications

---

# Part 2: Developer Guide

## Architecture Overview

Soothe is built on three layers:

```
┌──────────────────────────────────────────────────────────────┐
│  Soothe (orchestration framework)                            │
│  Protocols: Context, Memory, Planner, Policy, Durability,    │
│             RemoteAgent, Concurrency, VectorStore             │
│  CLI TUI: SootheRunner, Rich Live, slash commands            │
│  create_soothe_agent() wires everything together             │
├──────────────────────────────────────────────────────────────┤
│  deepagents (agent framework)                                 │
│  BackendProtocol, AgentMiddleware, SubAgent, Summarization   │
│  create_deep_agent()                                         │
├──────────────────────────────────────────────────────────────┤
│  langchain / langgraph (runtime layer)                       │
│  BaseChatModel, BaseTool, StateGraph, Checkpointer           │
└──────────────────────────────────────────────────────────────┘
```

Soothe extends deepagents with seven core protocols:
- **Context Protocol**: Cognitive context engineering
- **Memory Protocol**: Cross-thread memory
- **Planner Protocol**: Plan-driven execution
- **Policy Protocol**: Least-privilege security
- **Durability Protocol**: Thread lifecycle management
- **RemoteAgent Protocol**: Remote agent interop (ACP/A2A)
- **Concurrency Protocol**: Controlled concurrency

## Installation

### Optional Extras

Install additional capabilities as needed:

| Extra | Command | Adds |
|-------|---------|------|
| `research` | `pip install soothe[research]` | Tavily web search |
| `browser` | `pip install soothe[browser]` | Browser automation via browser-use |
| `claude` | `pip install soothe[claude]` | Claude agent SDK integration |
| `serper` | `pip install soothe[serper]` | Google Serper search |
| `wizsearch` | `pip install soothe[wizsearch]` | Multi-engine search + crawler |
| `jina` | `pip install soothe[jina]` | Jina web reader |
| `media` | `pip install soothe[media]` | Image generation (DALL-E) |
| `rocksdb` | `pip install soothe[rocksdb]` | RocksDB persistence backend |
| `pgvector` | `pip install soothe[pgvector]` | PostgreSQL vector store |
| `weaviate` | `pip install soothe[weaviate]` | Weaviate vector store |
| `ollama` | `pip install soothe[ollama]` | Ollama local LLM provider |
| `all` | `pip install soothe[all]` | Everything above |

### Development Setup

```bash
git clone <repository-url>
cd soothe
make sync-dev    # sync with dev dependencies
make test        # run tests
make lint        # lint code
make format      # format code
```

## Configuration

### Environment Variables

All `SootheConfig` fields can be set with `SOOTHE_` prefixed env vars:

```bash
export SOOTHE_DEBUG=true
export SOOTHE_PLANNER_ROUTING=auto
export SOOTHE_CONTEXT_BACKEND=keyword
```

Standard provider keys:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export TAVILY_API_KEY=tvly-...
```

### YAML Config File

Full configuration via YAML:

```yaml
# Providers
providers:
  - name: openai
    provider_type: openai
    api_base_url: "${OPENAI_BASE_URL}"  # supports env vars
    api_key: "${OPENAI_API_KEY}"
    models:
      - gpt-4o-mini
      - gpt-4o

# Model router
router:
  default: "openai:gpt-4o-mini"
  think: "openai:o3-mini"
  fast: "openai:gpt-4o-mini"
  embedding: "openai:text-embedding-3-small"

# Protocols
context_backend: keyword
memory_backend: keyword
planner_routing: auto
policy_profile: standard

# Autonomous mode
autonomous_enabled_by_default: false
autonomous_max_iterations: 10
autonomous_max_retries: 2

# Progress verbosity
progress_verbosity: normal

# Subagents
subagents:
  research:
    enabled: true
  browser:
    enabled: true
  claude:
    enabled: false

# Tools
tools:
  - serper
  - wizsearch
  - jina
  - image
  - audio
  - video
  - tabular

# MCP servers
mcp_servers:
  - command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    transport: stdio
```

See [config/config.yml](../config/config.yml) for the complete reference.

### Model Router

The router maps purpose-based roles to specific models:

| Role | Purpose | Default |
|------|---------|---------|
| `default` | Orchestrator reasoning | `openai:gpt-4o-mini` |
| `think` | Planning, complex reasoning | Falls back to default |
| `fast` | Classification, scoring | Falls back to default |
| `image` | Vision/image understanding | Falls back to default |
| `embedding` | Vector operations | Falls back to default |
| `web_search` | Web search tasks | Falls back to default |

### Message Surfacing Behavior

Soothe separates conversation view from activity view:

- **ConversationPanel (TUI)**: User turns and final responses
- **ActivityPanel (TUI)**: Protocol events, tool calls, subagent activity
- **Headless text mode**: Main response to stdout, progress to stderr
- **Headless JSONL mode**: Raw stream chunks for machine processing

**Verbosity levels**:

- `minimal`: Assistant text + errors only
- `normal`: Assistant text + protocol events + errors
- `detailed`: Adds subagent events + tool activity
- `debug`: All events (including heartbeat/thinking)

## Protocols

### Context Protocol

Accumulates knowledge and projects relevant subsets into bounded token windows.

**Backends**:
- `keyword`: Tag-based matching
- `vector`: Semantic search
- `none`: Disabled

**Configuration**:

```yaml
context_backend: keyword
context_persist_dir: ~/.soothe/context
```

### Memory Protocol

Cross-thread long-term memory for important findings.

**Backends**:
- `keyword`: Keyword retrieval
- `vector`: Semantic retrieval
- `none`: Disabled

**Configuration**:

```yaml
memory_backend: keyword
memory_persist_path: ~/.soothe/memory/
```

### Planner Protocol

Decomposes goals into structured plans with three tiers:

1. **DirectPlanner**: Single LLM call (simple tasks)
2. **SubagentPlanner**: Multi-turn planner subagent (medium tasks)
3. **ClaudePlanner**: Claude CLI for deep planning (complex tasks)

**Auto routing**: Uses heuristic classification + LLM verification.

**Configuration**:

```yaml
planner_routing: auto  # auto | always_direct | always_planner | always_claude
```

### Policy Protocol

Enforces least-privilege delegation for tools and subagents.

**Profiles**:
- `standard`: Balanced permissions
- `readonly`: Read-only operations
- `privileged`: Elevated permissions

**Configuration**:

```yaml
policy_profile: standard
```

### Durability Protocol

Persists and restores agent state across sessions.

**Features**:
- Thread lifecycle: create, resume, suspend, archive
- Crash recovery
- State persistence

## MCP Integration

Connect to MCP servers for additional tools.

**Configuration**:

```yaml
mcp_servers:
  # Stdio server
  - command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    transport: stdio

  # HTTP/SSE server
  - url: http://localhost:3000/mcp
    transport: sse
```

Sessions are managed alongside thread lifecycle.

## Tools

Enable additional tools in your config:

```yaml
tools:
  - serper      # Google search (requires SERPER_API_KEY)
  - wizsearch   # Multi-engine search + crawler
  - jina        # Web reader (requires JINA_API_KEY)
  - image       # Image generation via DALL-E
  - audio       # Audio processing
  - video       # Video processing
  - tabular     # Tabular data analysis
```

**Note**: deepagents provides file operations (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`), shell execution (`execute`), and task tracking (`write_todos`) by default.

### Tool Details

#### Bash Toolkit

Persistent shell execution with session management.

- Maintains shell state across commands
- Environment variable management
- Working directory tracking
- Timeout handling

#### File Edit Toolkit

File operations with safety features.

- Create, read, edit with backups
- Pattern-based editing
- Rollback capabilities

#### Python Executor Toolkit

IPython-based code execution.

- Execute Python code
- Matplotlib visualization
- Variable persistence
- Output capture

#### Document Toolkit

Document processing.

- Extract text and metadata
- Support for PDF, DOCX, TXT
- Structured data extraction

#### Goals Tool

Goal lifecycle management.

- Create/list/complete goals
- Hierarchical goals (parent/child)
- Priority management

## Using Ollama (Local Models)

Run local models without API keys.

**Setup**:

```bash
pip install soothe[ollama]
ollama serve
ollama pull llama3.2
```

**Configuration**:

```yaml
providers:
  - name: ollama
    provider_type: ollama
    api_base_url: http://localhost:11434
    models:
      - llama3.2

router:
  default: "ollama:llama3.2"
```

**Note**: Use `provider_type: ollama`, not `openai`. No API key required.

## Advanced Troubleshooting

### Vector Store Connection Errors

Start infrastructure:

```bash
docker compose up -d  # starts PGVector + Weaviate
```

Configure connection:

```yaml
vector_store_provider: pgvector
vector_store_config:
  dsn: "postgresql://postgres:postgres@localhost:5432/vectordb"
```

### Model Resolution Issues

Ensure provider name matches:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"

router:
  default: "openai:gpt-4o-mini"  # "openai" must match providers[].name
```

### Debug Mode

Enable verbose logging:

```bash
export SOOTHE_DEBUG=true
```

Or in YAML:

```yaml
debug: true
```

## Development

### Commands

```bash
make help          # show all commands
make sync-dev      # sync dev dependencies
make format        # format with ruff
make lint          # lint with ruff
make test          # run all tests
make test-unit     # run unit tests
make test-integration  # run integration tests (requires docker compose)
make build         # build package
```

### Infrastructure

For integration tests:

```bash
docker compose up -d
make test-integration
```

## Documentation

### Design Specifications

| RFC | Title |
|-----|-------|
| [RFC-0001](docs/specs/RFC-0001.md) | System Conceptual Design |
| [RFC-0002](docs/specs/RFC-0002.md) | Core Modules Architecture |
| [RFC-0003](docs/specs/RFC-0003.md) | CLI TUI Architecture |
| [RFC-0004](docs/specs/RFC-0004.md) | Skillify Agent Architecture |
| [RFC-0005](docs/specs/RFC-0005.md) | Weaver Agent Architecture |
| [RFC-0006](docs/specs/RFC-0006.md) | Context and Memory Architecture |
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
| [IG-010](docs/impl/010-tui-layout-history-refresh.md) | TUI Layout, History, Refresh |
| [IG-011](docs/impl/011-skillify-agent-implementation.md) | Skillify Agent Implementation |
| [IG-012](docs/impl/012-weaver-agent-implementation.md) | Weaver Agent Implementation |
| [IG-013](docs/impl/013-soothe-polish-pass.md) | Soothe Polish Pass |
| [IG-014](docs/impl/014-code-structure-revision.md) | Code Structure Revision |
| [IG-015](docs/impl/015-rfc-gap-closure-and-compat-hard-cut.md) | RFC Gap Closure and Compatibility |
| [IG-016](docs/impl/016-agent-optimization-pass.md) | Agent Optimization Pass |
| [IG-017](docs/impl/017-progress-events-tools-polish.md) | Progress Events and Tools Polish |
| [IG-018](docs/impl/018-autonomous-iteration-loop.md) | Autonomous Iteration Loop |
| [IG-019](docs/impl/019-soothe-tools-enhancement.md) | Soothe Tools Enhancement |
| [IG-020](docs/impl/020-detached-daemon-autonomous-capability.md) | Detached Daemon Autonomous Capability |

## Privacy

The Browser subagent uses [browser-use](https://github.com/browser-use/browser-use) with privacy-first defaults:
- Browser extensions: disabled
- Cloud services: disabled
- Anonymous telemetry: disabled

Re-enable in config if needed:

```yaml
subagents:
  browser:
    config:
      disable_extensions: false
      disable_cloud: false
      disable_telemetry: false
```

## License

MIT
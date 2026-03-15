# Soothe User Guide

## Installation

### From Source (recommended for development)

```bash
git clone <repository-url>
cd soothe
make sync          # installs all dependencies via uv
```

### With pip

```bash
pip install soothe
```

### Optional Extras

Install additional capabilities as needed:

| Extra | Command | What it adds |
|-------|---------|-------------|
| `research` | `pip install soothe[research]` | Tavily web search |
| `browser` | `pip install soothe[browser]` | Browser automation via browser-use |
| `claude` | `pip install soothe[claude]` | Claude agent SDK integration |
| `serper` | `pip install soothe[serper]` | Google Serper search |
| `jina` | `pip install soothe[jina]` | Jina web reader |
| `media` | `pip install soothe[media]` | Image generation (DALL-E) |
| `rocksdb` | `pip install soothe[rocksdb]` | RocksDB persistence backend |
| `pgvector` | `pip install soothe[pgvector]` | PostgreSQL vector store |
| `weaviate` | `pip install soothe[weaviate]` | Weaviate vector store |
| `ollama` | `pip install soothe[ollama]` | Ollama local LLM provider |
| `all` | `pip install soothe[all]` | Everything above |

## Configuration

Soothe uses two configuration mechanisms: environment variables and a YAML config file.

### Environment Variables

Copy the example and fill in your API keys:

```bash
cp config/env.example .env
```

At minimum, set `OPENAI_API_KEY` (or another LLM provider key):

```bash
export OPENAI_API_KEY=sk-...
```

All `SootheConfig` fields can be overridden with `SOOTHE_` prefixed env vars:

```bash
export SOOTHE_DEBUG=true
export SOOTHE_PLANNER_ROUTING=auto
export SOOTHE_CONTEXT_BACKEND=keyword
```

### YAML Config File

For full control, use a YAML config file:

```bash
cp config/config.yml my-config.yml
# Edit my-config.yml
soothe run --config my-config.yml
```

The YAML file supports `${ENV_VAR}` syntax in provider fields such as `api_key` and `api_base_url`:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_base_url: "${OPENAI_BASE_URL}"
    api_key: "${OPENAI_API_KEY}"
```

See [config/config.yml](../config/config.yml) for the complete reference with all fields.

### Model Router

The model router maps purpose-based roles to specific models:

| Role | Purpose | Default |
|------|---------|---------|
| `default` | Orchestrator reasoning | `openai:gpt-4o-mini` |
| `think` | Planning, complex reasoning | Falls back to default |
| `fast` | Classification, scoring | Falls back to default |
| `image` | Vision/image understanding | Falls back to default |
| `embedding` | Vector operations | Falls back to default |
| `web_search` | Web search tasks | Falls back to default |

Configure in YAML:

```yaml
router:
  default: "openai:gpt-4o-mini"
  think: "openai:o3-mini"
  fast: "openai:gpt-4o-mini"
  embedding: "openai:text-embedding-3-small"
```

## Running the Agent

### Interactive TUI Mode

Launch the interactive terminal UI:

```bash
soothe run
```

This opens a Rich-powered TUI with real-time progress, plan visualization, and slash
commands. The TUI shows:

- Subagent activity tracking (running/done status)
- Tool call progress
- Protocol events (context projection, memory recall, plan creation)
- Spinner with phase-aware thinking messages

### Headless Mode

Run a single prompt and exit:

```bash
soothe run "What are the latest developments in quantum computing?"
```

### With Options

```bash
# Use a specific config file
soothe run --config my-config.yml

# Resume a specific thread
soothe run --thread abc123

# Disable TUI (plain streaming output)
soothe run --no-tui
```

## TUI Interface

### Slash Commands

Type these in the TUI prompt:

| Command | Description |
|---------|-------------|
| `/help` | Show all commands and subagent selector |
| `/plan` | Show current task plan tree |
| `/memory` | Show memory statistics |
| `/context` | Show context statistics |
| `/policy` | Show active policy profile |
| `/thread list` | List all threads |
| `/thread resume <id>` | Resume a specific thread |
| `/thread archive <id>` | Archive a thread |
| `/config` | Show active configuration |
| `/session` | Show session log path |
| `/clear` | Clear screen |
| `/exit` or `/quit` | Exit the TUI |

### Subagent Routing

Prefix your message with a number to route to a specific subagent:

| Prefix | Subagent |
|--------|----------|
| `1` | Main (default) |
| `2` | Planner |
| `3` | Scout |
| `4` | Research |
| `5` | Browser |
| `6` | Claude |

Examples:

```
4 Search for papers on transformer architectures
5 Open https://example.com and take a screenshot
2 Create a plan for building a REST API
```

Multiple subagents: `4,5 Find and visit the top 3 AI news sites`

### Multi-line Input

End a line with `\` to continue on the next line:

```
soothe> Write a function that \
...  takes a list of numbers \
...  and returns the median
```

### Keyboard Shortcuts

- `Ctrl+C` once: cancel current task
- `Ctrl+C` twice: exit the TUI

## Subagents

### Research

Deep web research using Tavily search. Automatically breaks queries into sub-searches,
gathers sources, and synthesizes findings.

**Requires**: `pip install soothe[research]` + `TAVILY_API_KEY`

### Planner

Creates structured task plans for complex goals. Decomposes problems into steps with
dependencies. Works with the PlannerProtocol for plan-driven execution.

### Scout

Lightweight exploration agent for quick file searches, code navigation, and codebase
understanding. Uses deepagents' filesystem tools.

### Browser

Automated web browsing via browser-use. Can navigate pages, fill forms, click elements,
and take screenshots.

**Requires**: `pip install soothe[browser]`

Privacy-first defaults: extensions, cloud sync, and telemetry are disabled.

### Claude

Direct access to Claude via the Anthropic SDK. Useful for tasks that benefit from Claude's
strengths (long context, careful reasoning).

**Requires**: `pip install soothe[claude]` + `ANTHROPIC_API_KEY`

### Enabling/Disabling

In your config YAML:

```yaml
subagents:
  research:
    enabled: true
  browser:
    enabled: true     # enable browser
  claude:
    enabled: false    # keep disabled
```

## Protocols

Soothe's core protocols provide capabilities beyond what deepagents offers.
All protocols are optional and configured via `SootheConfig`.

### Context Protocol

Accumulates knowledge from tool results, subagent outputs, and agent reflections in an
unbounded context ledger. Projects relevant subsets into bounded token windows for LLM
calls and subagent briefings.

```yaml
context_backend: keyword     # keyword (tag matching) | vector (semantic) | none
context_persist_dir: ~/.soothe/context
```

### Memory Protocol

Cross-thread long-term memory. Stores important findings that survive beyond a single
conversation. Retrieved by keyword or semantic relevance at the start of new threads.

```yaml
memory_backend: keyword      # keyword | vector (semantic) | none
memory_persist_path: ~/.soothe/memory/
```

### Planner Protocol

Decomposes complex goals into structured plans with steps, dependencies, and status
tracking. Two tiers: DirectPlanner (single LLM call) and SubagentPlanner (multi-turn).

```yaml
planner_routing: auto        # auto | always_direct | always_subagent | none
```

### Policy Protocol

Enforces least-privilege delegation. Every tool call and subagent spawn passes through
a policy check. Permissions are structured by category, action, and scope.

```yaml
policy_profile: standard     # named profile (standard, readonly, privileged)
```

### Durability Protocol

Persists and restores agent state. Thread lifecycle management: create, resume, suspend,
archive. Ensures continuity across crashes and restarts.

## Thread Management

### CLI Commands

```bash
# List all threads
soothe thread list

# Archive a thread
soothe thread archive abc123
```

### TUI Commands

```
/thread list
/thread resume abc123
/thread archive abc123
```

### Resuming Threads

```bash
# Resume from CLI
soothe run --thread abc123

# Resume from TUI
/thread resume abc123
```

## MCP Integration

Connect to MCP servers for additional tool capabilities. Configure in YAML using the
Claude Desktop `.mcp.json` format:

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

MCP sessions are managed alongside thread lifecycle: created on thread start, cleaned
up on suspend/archive.

## Tools

Enable tool groups by name in your config:

```yaml
tools:
  - serper     # Google search (requires SERPER_API_KEY)
  - jina       # Web reader (requires JINA_API_KEY)
  - image      # Image generation via DALL-E
  - audio      # Audio processing
  - video      # Video processing
  - tabular    # Tabular data analysis
```

Note: deepagents already provides file operations (`ls`, `read_file`, `write_file`,
`edit_file`, `glob`, `grep`), shell execution (`execute`), and task tracking
(`write_todos`). These are always available and do not need to be listed in `tools`.

## Using Ollama (Local Models)

Soothe supports [Ollama](https://ollama.ai) for running local LLMs without API keys.

### Setup

```bash
pip install soothe[ollama]    # install langchain-ollama
ollama serve                  # start the Ollama server
ollama pull llama3.2          # pull a model
```

### Configuration

```yaml
providers:
  - name: ollama
    provider_type: ollama
    api_base_url: http://localhost:11434
    models:
      - llama3.2
      - qwen3:8b

router:
  default: "ollama:llama3.2"
  fast: "ollama:llama3.2"
```

Ollama uses `provider_type: ollama` (native `ChatOllama` via `langchain-ollama`), **not**
`provider_type: openai`. No API key is required for local models.

## Troubleshooting

### Missing API Key

```
Error: Could not resolve model openai:gpt-4o-mini
```

Set your API key:

```bash
export OPENAI_API_KEY=sk-...
```

### Model Resolution

The `provider:model` format requires the provider to be defined in `providers`:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"

router:
  default: "openai:gpt-4o-mini"   # "openai" must match providers[].name
```

### Browser Subagent Not Working

Install the browser extra:

```bash
pip install soothe[browser]
# or
uv sync --extra browser
```

### Vector Store Connection Errors

Start infrastructure services:

```bash
docker compose up -d   # starts PGVector + Weaviate
```

Configure the connection:

```yaml
vector_store_provider: pgvector
vector_store_config:
  dsn: "postgresql://postgres:postgres@localhost:5432/vectordb"
```

### Debug Mode

Enable verbose logging:

```bash
export SOOTHE_DEBUG=true
soothe run
```

Or in YAML:

```yaml
debug: true
```

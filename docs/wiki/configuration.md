# Configuration Guide

Comprehensive configuration reference for Soothe.

## Configuration Methods

Soothe supports three configuration methods:

1. **Environment Variables** - Quick setup for single values
2. **YAML Configuration File** - Full configuration control
3. **Command-Line Arguments** - Override specific settings

### Environment Variables

All `SootheConfig` fields can be set with `SOOTHE_` prefixed environment variables:

```bash
export SOOTHE_DEBUG=true
export SOOTHE_PLANNER_ROUTING=auto
export SOOTHE_PROGRESS_VERBOSITY=detailed
```

Standard provider keys:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export TAVILY_API_KEY=tvly-...
```

### YAML Configuration File

Create a YAML configuration file for complete control:

```bash
# Use default config location
soothe --config config/config.yml

# Use custom config
soothe --config my-config.yml
```

## Essential Settings

### API Keys

Set your OpenAI API key (required for most operations):

```bash
export OPENAI_API_KEY=sk-your-key-here
```

Or in configuration:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"  # References env var
```

### Model Selection

Configure which models to use:

```yaml
router:
  default: "openai:gpt-4o-mini"     # Orchestrator reasoning
  think: "openai:o3-mini"            # Planning, complex reasoning
  fast: "openai:gpt-4o-mini"         # Classification, scoring
  image: "openai:gpt-4o"             # Vision/image understanding
  embedding: "openai:text-embedding-3-small"  # Vector operations
```

### Workspace Directory

Set the working directory:

```yaml
workspace_dir: "."
```

## Model Router

The router maps purpose-based roles to specific models:

| Role | Purpose | Default |
|------|---------|---------|
| `default` | Orchestrator reasoning | `openai:gpt-4o-mini` |
| `think` | Planning, complex reasoning | Falls back to `default` |
| `fast` | Classification, scoring | Falls back to `default` |
| `image` | Vision/image understanding | Falls back to `default` |
| `embedding` | Vector operations | Falls back to `default` |

## Progress Verbosity

Control output detail level:

```yaml
progress_verbosity: normal  # minimal | normal | detailed | debug
```

**Levels**:
- `minimal`: Assistant text + errors only
- `normal`: Assistant text + protocol events + errors
- `detailed`: Adds subagent events + tool activity
- `debug`: All events (including heartbeat/thinking)

### Message Surfacing Behavior

Soothe separates conversation view from activity view:
- **ConversationPanel (TUI)**: User turns and final responses
- **ActivityInfo (TUI)**: Last 5 lines of protocol events, tool calls, subagent activity
- **Headless text mode**: Main response to stdout, progress to stderr
- **Headless JSONL mode**: Raw stream chunks for machine processing

## Subagents

Enable or disable subagents:

```yaml
subagents:
  browser:
    enabled: true
    config:
      runtime_dir: ""
      disable_extensions: true
      disable_cloud: true

  claude:
    enabled: true
    model: "anthropic:claude-sonnet-4-20250514"

  skillify:
    enabled: true
    warehouse_paths: []
    index_interval_seconds: 300

  weaver:
    enabled: true
```

## Daemon Configuration

Configure daemon behavior:

```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"

    websocket:
      enabled: false
      host: "127.0.0.1"
      port: 8765
      cors_origins: ["http://localhost:*"]

    http_rest:
      enabled: false
      host: "127.0.0.1"
      port: 8766
```

**Note**: Authentication is handled by external reverse proxies, not by Soothe. See [Authentication Guide](authentication.md) for details.

## Autonomous Mode

Configure autonomous iteration:

```yaml
autonomous_enabled_by_default: false
autonomous_max_iterations: 10
autonomous_max_retries: 2
```

## Optional Extras

Install additional capabilities as needed:

| Extra | Command | Adds |
|-------|---------|------|
| `research` | `pip install soothe[research]` | Tavily web search |
| `browser` | `pip install soothe[browser]` | Browser automation |
| `claude` | `pip install soothe[claude]` | Claude agent SDK |
| `serper` | `pip install soothe[serper]` | Google Serper search |
| `wizsearch` | `pip install soothe[wizsearch]` | Multi-engine search |
| `jina` | `pip install soothe[jina]` | Jina web reader |
| `media` | `pip install soothe[media]` | Image generation (DALL-E) |
| `rocksdb` | `pip install soothe[rocksdb]` | RocksDB persistence |
| `pgvector` | `pip install soothe[pgvector]` | PostgreSQL vector store |
| `weaviate` | `pip install soothe[weaviate]` | Weaviate vector store |
| `ollama` | `pip install soothe[ollama]` | Ollama local models |
| `all` | `pip install soothe[all]` | Everything above |

## Using Ollama (Local Models)

Run local models without API keys:

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

## MCP Integration

Connect to MCP servers for additional tools:

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

## Tools

Enable additional tools:

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

**Note**: deepagents provides file operations, shell execution, and task tracking by default.

## Protocols

Configure protocol backends:

```yaml
protocols:
  context:
    backend: keyword-postgresql  # keyword-json | keyword-postgresql | vector-postgresql

  memory:
    backend: keyword-postgresql  # keyword-json | keyword-postgresql | vector-postgresql
```

## Complete Configuration Example

```yaml
# Model Providers
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models:
      - gpt-4o
      - gpt-4o-mini

  - name: ollama
    provider_type: ollama
    api_base_url: http://localhost:11434
    models:
      - llama3.2

# Model Router
router:
  default: "openai:gpt-4o-mini"
  think: "openai:o3-mini"
  fast: "openai:gpt-4o-mini"
  image: "openai:gpt-4o"
  embedding: "openai:text-embedding-3-small"

# Agent Behavior
workspace_dir: "."
debug: false
progress_verbosity: normal

# Protocols
protocols:
  context:
    backend: keyword-postgresql
  memory:
    backend: keyword-postgresql

# Subagents
subagents:
  browser:
    enabled: true
  claude:
    enabled: true

# Daemon
daemon:
  transports:
    unix_socket:
      enabled: true
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
  auth:
    enabled: true
    mode: "api_key"

# Autonomous Mode
autonomous_enabled_by_default: false
autonomous_max_iterations: 10

# Tools
tools:
  - jina
  - image

# MCP Servers
mcp_servers:
  - command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    transport: stdio
```

## Configuration File Location

Default locations (checked in order):
1. `--config <file>` CLI argument
2. `./config.yml` (current directory)
3. `~/.soothe/config.yml` (user home)
4. `/etc/soothe/config.yml` (system-wide)

## Related Guides

- [Getting Started](getting-started.md) - Basic setup
- [Multi-Transport Setup](multi-transport.md) - Daemon configuration
- [Authentication](authentication.md) - Auth configuration
- [Troubleshooting](troubleshooting.md) - Configuration issues
# Frequently Asked Questions (FAQ)

Common questions and answers about Soothe.

---

## General

### What is Soothe?

Soothe is a **goal-driven orchestration framework** for building 24/7 long-running autonomous agents. It extends LangChain/DeepAgents with:
- Persistent **agentic loop** (Plan → Execute iterations)
- **Goal engine** for multi-goal orchestration
- **Protocol-first design** with pluggable backends
- **Durable execution** with crash recovery
- **Security policies** and least-privilege delegation

**Key difference**: Shift from *human-in-the-loop* to **agent-in-the-loop** — define intent, let the system handle execution.

### What can Soothe do?

| Capability | Examples |
|------------|----------|
| **Deep Research** | Multi-source web search, academic papers (arXiv, DeepXiv), document analysis |
| **Autonomous Execution** | Multi-step workflows, file operations, code execution, shell commands |
| **Long-Running Ops** | Background daemon, thread management, persistent state |
| **Custom Plugins** | `@tool`, `@subagent`, `@plugin` decorators, MCP server integration |

### How does Soothe differ from LangChain/LangGraph?

**Soothe adds**:
- **Goal management**: Multi-goal orchestration with goal DAGs
- **Agentic loop**: Plan → Execute iterations for complex goals
- **Persistent memory**: MemU semantic memory across sessions
- **Durability**: Automatic crash recovery and checkpointing
- **Security policies**: Config-driven least-privilege
- **Daemon server**: WebSocket/HTTP REST transports

**Built on**:
- LangGraph for agent runtime (CoreAgent)
- DeepAgents for subagent orchestration
- LangChain for tools and model abstraction

### What Python version is required?

**Python 3.11+** is required. Soothe uses modern Python features:
- Type hints with `typing` module
- `match/case` statements
- Async improvements
- Dataclasses and Pydantic v2

---

## Installation

### What packages do I need to install?

**Recommended** (full stack):
```bash
pip install -U 'soothe[all]' soothe-cli soothe-daemon
```

This installs:
- `soothe[all]` - Core agent runtime + all optional extras
- `soothe-cli` - CLI and TUI
- `soothe-daemon` - Background daemon server

**Minimal** (core + CLI only):
```bash
pip install soothe soothe-cli
```

Add daemon later: `pip install soothe-daemon`

### What optional extras are available?

| Extra | Adds |
|-------|------|
| `research` | Tavily web search |
| `wizsearch` | Multi-engine search (Tavily, DuckDuckGo, Brave) |
| `jina` | Jina web reader |
| `media` | Image generation (DALL-E), audio/video analysis |
| `pgvector` | PostgreSQL vector store |
| `weaviate` | Weaviate vector store |
| `rocksdb` | RocksDB persistence |
| `langfuse` | Langfuse LLM observability |
| `dashscope` | DashScope provider (Qwen, GLM, etc.) |
| `all` | Everything above |

**Install specific extras**:
```bash
pip install 'soothe[research,wizsearch,pgvector]' soothe-cli soothe-daemon
```

### Why do I need soothe-community?

`soothe-community` is a **separate package** (separate repo) with optional delegated agents:
- `claude` - Anthropic Claude delegation
- `browser_use` - Browser automation specialist
- Other community plugins

**Install**:
```bash
pip install soothe-community
```

**Configure**:
```yaml
subagents:
  claude:
    enabled: true
  browser_use:
    enabled: true
```

See [soothe-community repo](https://github.com/mirasoth/soothe-community) for details.

### How do I verify installation?

```bash
# Check CLI
soothe --help

# Check daemon
soothed doctor

# Run test query
soothe -p "What is the capital of France?"
```

---

## Configuration

### How do I configure Soothe?

Three methods:
1. **Environment variables**: `export SOOTHE_<FIELD>=<value>`
2. **YAML config file**: `~/.soothe/config.yml` or `--config path/to/config.yml`
3. **CLI arguments**: `soothe --debug --config my.yml`

See [Configuration Guide](configuration-guide/README.md) for complete reference.

### How do I set API keys?

**Environment variables** (recommended):
```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export DASHSCOPE_API_KEY=...
```

**YAML config** (with env var interpolation):
```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models: [gpt-4o-mini]
```

**Secret management** (production):
- Vault
- AWS Secrets Manager
- GCP Secret Manager
- Azure Key Vault

See [Configuration Guide - Provider Setup](configuration-guide/provider-setup.md).

### How do I choose which model to use?

Use **model router** to map purpose roles to models:

```yaml
router:
  default: "openai:gpt-4o-mini"     # Main orchestrator
  think: "openai:o3-mini"            # Complex reasoning
  fast: "openai:gpt-4o-mini"         # Classification
  image: "openai:gpt-4o"             # Vision
  embedding: "openai:text-embedding-3-small"
```

**Roles**:
- `default`: Orchestrator reasoning (CoreAgent)
- `think`: Planning, complex reasoning
- `fast`: Classification, routing
- `image`: Vision/image understanding
- `embedding`: Vector operations (MemU)

See [Configuration Guide - Model Router](configuration-guide/yaml-reference.md#model-router).

### How do I use local models (Ollama)?

**Install Ollama**:
```bash
# macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
ollama serve
```

**Configure Soothe**:
```yaml
providers:
  - name: ollama
    provider_type: ollama
    api_base_url: "http://localhost:11434"
    models: [llama3.2]

router:
  default: "ollama:llama3.2"
```

See [Configuration Guide - Provider Setup](configuration-guide/provider-setup.md#ollama).

---

## Usage

### How do I run a quick query?

**One-shot mode** (no TUI):
```bash
soothe -p "List Python files in current directory and count lines"
```

**TUI mode** (interactive):
```bash
soothe
# Opens TUI, type your query
```

**Daemon mode** (background):
```bash
soothed start
soothe --daemon "Analyze codebase structure"
```

### How do I enable autonomous mode?

Autonomous mode allows multi-step autonomous execution:

```yaml
agent:
  autonomous:
    enabled_by_default: true
    max_iterations: 10
    max_retries: 2
```

**Or per-request**:
```bash
soothe --autonomous "Research AI safety papers and summarize findings"
```

See [Autonomous Mode Guide](autonomous-mode.md).

### How do I manage conversation threads?

**List threads**:
```bash
soothe thread list
```

**Continue thread**:
```bash
soothe thread continue <thread-id>
```

**Resume last thread**:
```bash
soothe thread continue
```

**Thread directory**: `~/.soothe/data/threads/<thread-id>/`

See [Thread Management Guide](thread-management.md).

### How do I use subagents?

Subagents are specialized helper agents:

**Built-in** (always available):
- `explore` - Targeted filesystem search
- `plan` - Planning delegate
- `tacitus` - Deep public-domain research

**Community** (requires `soothe-community`):
- `claude` - Anthropic Claude delegation
- `browser_use` - Browser automation

**Configure**:
```yaml
subagents:
  tacitus:
    enabled: true
    config:
      llm_role: fast
      synthesis_role: think
      effort: normal
```

See [Subagents Guide](subagents.md).

---

## Daemon

### How do I start the daemon?

```bash
# Start daemon in background
soothed start

# Check status
soothed status

# Stop daemon
soothed stop

# Restart daemon
soothed restart
```

**Foreground mode** (debugging):
```bash
soothed start --foreground
```

See [Daemon Management Guide](daemon-management.md).

### How do I connect to a running daemon?

**CLI connects automatically** if daemon is running:

```bash
soothe --daemon "your query"
```

**Or via WebSocket/HTTP** (remote):
```bash
# WebSocket
soothe --ws-url ws://localhost:8765 "your query"

# HTTP REST
curl -X POST http://localhost:8766/api/query \
  -H "Content-Type: application/json" \
  -d '{"input": "your query"}'
```

See [Multi-Transport Guide](multi-transport.md).

### How do I enable WebSocket/HTTP REST?

**Configure transports**:
```yaml
# In daemon_config.yml
daemon:
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"
    
    websocket:
      enabled: true
      host: "0.0.0.0"
      port: 8765
    
    http_rest:
      enabled: true
      host: "0.0.0.0"
      port: 8766
```

**Start daemon**:
```bash
soothed --config daemon_config.yml start
```

See [Multi-Transport Guide](multi-transport.md).

---

## Deployment

### How do I deploy Soothe in production?

See [Deployment Guide](deployment/README.md) for comprehensive production deployment instructions.

**Quick start** (Docker Compose):
```bash
cd deploy
cp .env.example .env
vim .env  # Set API keys and passwords
docker compose up -d
```

**Production components**:
- PostgreSQL + pgvector (multi-database architecture)
- Soothe daemon (WebSocket/HTTP REST)
- Reverse proxy (nginx) for authentication and TLS
- Langfuse for LLM observability

See [Deployment Guide - Production Setup](deployment/production-setup.md).

### How do I monitor Soothe?

**Health checks**:
```bash
soothed doctor
soothed status
```

**Logs**:
```bash
# Daemon logs
tail -f ~/.soothe/logs/daemon.log

# Thread logs
tail -f ~/.soothe/data/threads/<thread-id>/thread.log
```

**Langfuse** (LLM traces):
```yaml
observability:
  langfuse:
    enabled: true
    public_key: "${LANGFUSE_PUBLIC_KEY}"
    secret_key: "${LANGFUSE_SECRET_KEY}"
    host: "https://cloud.langfuse.com"
```

See [Deployment Guide - Monitoring](deployment/monitoring.md).

### How do I secure Soothe?

**Soothe does NOT have built-in authentication**. Use reverse proxy:

```
Client → nginx (Auth + TLS) → Soothe Daemon
```

**Reverse proxy handles**:
- TLS termination (HTTPS/WSS)
- Authentication (API key, JWT, OAuth)
- Authorization (RBAC)
- Rate limiting

See [Authentication Guide](authentication.md) and [Deployment Guide - Security](deployment/security.md).

---

## Troubleshooting

### Why does "Could not resolve model" error occur?

**Missing API key**:
```bash
export OPENAI_API_KEY=sk-...
```

**Invalid model name**:
```yaml
router:
  default: "openai:gpt-4o-mini"  # Check model exists
```

**Provider not configured**:
```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models: [gpt-4o-mini]  # Must list model
```

See [Troubleshooting Guide](troubleshooting.md).

### Why does WebSocket connection fail?

**Daemon not running**:
```bash
soothed status
soothed start
```

**WebSocket not enabled**:
```yaml
daemon:
  transports:
    websocket:
      enabled: true
```

**Firewall blocking**:
```bash
# Check port is open
netstat -an | grep 8765
```

See [Troubleshooting Guide](troubleshooting.md).

### Why does subagent not work?

**Subagent disabled**:
```yaml
subagents:
  <name>:
    enabled: true  # Must be true
```

**Community subagent not installed**:
```bash
pip install soothe-community
```

**Missing provider key** (for claude/browser_use):
```bash
export ANTHROPIC_API_KEY=sk-ant-...  # For claude
```

See [Troubleshooting Guide](troubleshooting.md).

### How do I debug agent behavior?

**Enable debug mode**:
```bash
soothe --debug "your query"
```

**Enable verbose logging**:
```bash
SOOTHE_LOG_LEVEL=DEBUG soothe "your query"
```

**Check logs**:
```bash
tail -f ~/.soothe/logs/daemon.log
tail -f ~/.soothe/data/threads/<thread-id>/thread.log
```

**Langfuse traces**:
- View LLM calls, prompts, responses
- Track token usage and latency

See [Debug Guide](../howto_debug.md) and [Troubleshooting Guide](troubleshooting.md).

---

## Development

### How do I contribute to Soothe?

See [Contributing Guide](contributing-guide.md) for:
- Development setup
- Code standards
- Pull request process
- Architecture guidelines

**Quick start**:
```bash
git clone https://github.com/mirasoth/soothe.git
cd soothe
make sync
./scripts/verify_finally.sh
```

### How do I run tests?

See [Testing Guide](testing-guide.md).

**Quick commands**:
```bash
# Unit tests
make test-unit

# Integration tests (requires PostgreSQL)
docker compose -f docker-compose.dev.yml up -d
make test-integration

# Full verification
./scripts/verify_finally.sh
```

### How do I create a custom tool?

**Use `@tool` decorator**:

```python
from soothe_sdk.plugin import tool

@tool(name="my_tool", description="Does something")
def my_tool(arg: str) -> str:
    """Custom tool implementation.
    
    Args:
        arg: Input argument.
    
    Returns:
        Tool result.
    """
    return f"Result: {arg}"
```

**Register via plugin**:
```python
from soothe_sdk.plugin import plugin

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_tool", description="Does something")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"
```

See [Channel Plugin Guide](channel-plugin-guide.md).

### How do I create a custom subagent?

**Use `@subagent` decorator**:

```python
from soothe_sdk.plugin import subagent
from deepagents import CompiledSubAgent

@subagent(name="my_agent", description="Custom agent")
async def create_agent(model, config, context):
    """Create custom subagent.
    
    Args:
        model: Chat model instance.
        config: Subagent configuration.
        context: Plugin context.
    
    Returns:
        CompiledSubAgent instance.
    """
    # Build and return CompiledSubAgent
    return CompiledSubAgent(...)
```

See [Channel Plugin Guide](channel-plugin-guide.md).

---

## Architecture

### What is the three-level execution model?

```
┌─────────────────────────────────────┐
│ GoalEngine: Autonomous Goal Mgmt    │  Goal DAGs, multi-goal orchestration
│ Loop: Goal → PLAN → PERFORM → ...   │
└─────────────────────────────────────┘
              ↓ PERFORM
┌─────────────────────────────────────┐
│ AgentLoop: Agentic Goal Execution   │  Plan → Execute iterations
│ Loop: Plan → Execute (max ~8 iter) │
└─────────────────────────────────────┘
              ↓ EXECUTE
┌─────────────────────────────────────┐
│ CoreAgent: Runtime                  │  Model → Tools → Model loop
│ Foundation: create_soothe_agent()   │
└─────────────────────────────────────┘
```

See [Architecture Overview](architecture/README.md).

### What protocols does Soothe use?

**8 runtime-agnostic protocols**:

| Protocol | Purpose |
|----------|---------|
| ContextProtocol | Context injection (KeywordContext, VectorContext) |
| MemoryProtocol | Semantic memory (KeywordMemory, VectorMemory) |
| PlannerProtocol | Planning strategy (Simple, Subagent, model-specific) |
| PolicyProtocol | Security policies (ConfigDrivenPolicy) |
| DurabilityProtocol | Thread lifecycle and checkpoints |
| PersistenceProtocol | Key-value storage (SQLite, PostgreSQL) |
| VectorStoreProtocol | Embedding storage (PGVector, Weaviate) |
| WorkspaceProtocol | Workspace resolution and validation |

See [Architecture Overview - Protocols](architecture/README.md#protocols).

### How does the Plan → Execute loop work?

**AgentLoop** iterates Plan → Execute:

```
User Query → AgentLoop
  ↓
PLAN phase
  - Decompose goal into plan steps
  - Prioritize steps
  ↓
EXECUTE phase
  - Execute steps (tools, subagents)
  - Collect results
  - Check if goal complete
  ↓
If incomplete → PLAN again (adapt plan)
If complete → Return final response
```

**Max iterations**: 10 (configurable)

See [Architecture Overview - AgentLoop](core/agent-loop.md).

---

## Performance

### How do I optimize performance?

**LLM rate limiting**:
```yaml
agent:
  loop:
    limits:
      llm_rpm_limit: 120          # Requests per minute
      llm_concurrent_limit: 10    # Concurrent calls
```

**Context window management** (RFC-224):
```yaml
agent:
  loop:
    context_window_limit: 200000
    context_overflow_threshold_pct: 0.80
    context_compaction_target_pct: 0.60
```

**PostgreSQL optimization**:
```yaml
persistence:
  postgres_pool_min_size: 4
  checkpointer_pool_size: 24
```

**Vector store indexes**:
```yaml
vector_stores:
  - name: pgvector
    provider_type: pgvector
    index_type: hnsw  # Fast approximate search
```

See [Deployment Guide - Scaling](deployment/scaling.md).

### How do I scale Soothe?

**Horizontal scaling** (multi-node):
```
Load Balancer (nginx)
  ↓
Soothe Daemon Node 1
Soothe Daemon Node 2
Soothe Daemon Node 3
  ↓
PostgreSQL Cluster (primary + replicas)
```

**Kubernetes**:
- StatefulSet for PostgreSQL
- Deployment for daemon nodes
- HPA for auto-scaling

See [Deployment Guide - Scaling](deployment/scaling.md).

---

## Integration

### How do I integrate with MCP servers?

MCP (Model Context Protocol) servers provide external tools:

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    defer: true  # Progressive disclosure
```

**Transports**: stdio, sse, streamable_http, websocket

See [Configuration Guide - MCP Servers](configuration-guide/yaml-reference.md#mcp-servers).

### How do I integrate with Langfuse?

Langfuse provides LLM observability:

```yaml
observability:
  langfuse:
    enabled: true
    public_key: "${LANGFUSE_PUBLIC_KEY}"
    secret_key: "${LANGFUSE_SECRET_KEY}"
    host: "https://cloud.langfuse.com"
```

**Local Langfuse** (dev):
```bash
docker compose -f docker-compose.dev.yml up -d
# UI: http://localhost:3300
```

See [Deployment Guide - Monitoring](deployment/monitoring.md#langfuse-integration).

---

## More Questions?

- **Troubleshooting**: [Troubleshooting Guide](troubleshooting.md)
- **Configuration**: [Configuration Guide](configuration-guide/README.md)
- **Architecture**: [Architecture Overview](architecture/README.md)
- **Deployment**: [Deployment Guide](deployment/README.md)
- **Development**: [Contributing Guide](contributing-guide.md)
- **GitHub Issues**: Bug reports and feature requests
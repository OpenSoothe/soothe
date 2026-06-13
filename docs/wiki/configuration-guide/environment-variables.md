# Environment Variables Reference

Complete reference for Soothe environment variables.

## Overview

Soothe uses environment variables for:

1. **Configuration overrides** - `SOOTHE_*` prefix for any config field
2. **Secret injection** - API keys and tokens via standard env vars
3. **Runtime behavior** - Debug flags, logging, paths
4. **Provider keys** - Direct passthrough to LangChain ecosystem

## Environment Variable Prefix

All SootheConfig fields can be set with `SOOTHE_` prefix:

```bash
export SOOTHE_DEBUG=true
export SOOTHE_AGENT_AUTONOMOUS_ENABLED_BY_DEFAULT=true
export SOOTHE_OBSERVABILITY_VERBOSITY=detailed
```

**Naming convention**: `SOOTHE_<SECTION>_<FIELD>` (nested fields use underscores)

## Standard Provider Keys

Set these environment variables for API access:

### OpenAI

```bash
export OPENAI_API_KEY=sk-your-openai-key-here
```

Used by:
- `providers[].api_key` when `"${OPENAI_API_KEY}"` is referenced
- Direct passthrough to LangChain `init_chat_model("openai")`

### Anthropic

```bash
export ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
```

Used by:
- `providers[].api_key` for Anthropic provider
- Direct passthrough to LangChain `init_chat_model("anthropic")`

### Optional Tool Keys

```bash
# Web search
export TAVILY_API_KEY=tvly-your-tavily-key
export SERPER_API_KEY=your-serper-key
export JINA_API_KEY=your-jina-key

# Academic search
export DEEPXIV_API_KEY=your-deepxiv-key
export DEEPXIV_TOKEN=your-deepxiv-token

# Code search
export GITHUB_TOKEN=your-github-token
```

### Langfuse Tracing

```bash
export LANGFUSE_PUBLIC_KEY=pk-your-public-key
export LANGFUSE_SECRET_KEY=sk-your-secret-key
export LANGFUSE_HOST=https://cloud.langfuse.com  # Optional
```

## Soothe Environment Variables

### Configuration File Location

```bash
export SOOTHE_CONFIG_FILE=/path/to/config.yml
```

Priority: `--config` CLI arg > `SOOTHE_CONFIG_FILE` > `~/.soothe/config.yml`

### Home Directory

```bash
export SOOTHE_HOME=~/.soothe  # Default
export SOOTHE_DATA_DIR=~/.soothe/data
export SOOTHE_LOG_DIR=~/.soothe/logs
```

Paths:
- `SOOTHE_HOME`: Base directory (default: `~/.soothe`)
- `SOOTHE_DATA_DIR`: Data directory (default: `$SOOTHE_HOME/data`)
- `SOOTHE_LOG_DIR`: Log directory (default: `$SOOTHE_HOME/logs`)

### Debug & Logging

```bash
export SOOTHE_DEBUG=true  # Enable debug mode
export SOOTHE_LOG_LEVEL=DEBUG  # Set log level
export SOOTHE_TUI_DEBUG=true  # Enable TUI debug mode
```

### Observability

```bash
export SOOTHE_OBSERVABILITY_VERBOSITY=detailed  # minimal | normal | detailed | debug
export SOOTHE_OBSERVABILITY_LOG_FILE_LEVEL=INFO
export SOOTHE_OBSERVABILITY_LOG_FILE_PATH=/path/to/logfile.log
export SOOTHE_OBSERVABILITY_CONSOLE_ENABLED=true
export SOOTHE_OBSERVABILITY_CONSOLE_LEVEL=WARNING
```

### Agent Behavior

```bash
export SOOTHE_AGENT_NAME=Soothe
export SOOTHE_AGENT_AUTONOMOUS_ENABLED_BY_DEFAULT=false
export SOOTHE_AGENT_AUTONOMOUS_MAX_ITERATIONS=10
export SOOTHE_STRANGE_LOOP_MAX_ITERATIONS=10
export SOOTHE_STRANGE_LOOP_CONTEXT_WINDOW_LIMIT=200000
```

### Providers & Router

```bash
export SOOTHE_ROUTER_DEFAULT="openai:gpt-4o-mini"
export SOOTHE_ROUTER_THINK="openai:o3-mini"
export SOOTHE_ROUTER_FAST="openai:gpt-4o-mini"
export SOOTHE_ROUTER_IMAGE="openai:gpt-4o"
export SOOTHE_ROUTER_EMBEDDING="openai:text-embedding-3-small"
export SOOTHE_EMBEDDING_DIMS=1536
```

### Tools

```bash
export SOOTHE_TOOLS_EXECUTION_ENABLED=true
export SOOTHE_TOOLS_FILE_OPS_ENABLED=true
export SOOTHE_TOOLS_WIZSEARCH_ENABLED=true
export SOOTHE_TOOLS_WIZSEARCH_DEFAULT_ENGINES='["tavily","duckduckgo"]'
export SOOTHE_TOOLS_HTTP_REQUESTS_ENABLED=true
export SOOTHE_TOOLS_DEEPXIV_ENABLED=true
export SOOTHE_TOOLS_DEEPXIV_TOKEN=${DEEPXIV_API_KEY}
```

### Subagents

```bash
export SOOTHE_SUBAGENTS_EXPLORE_ENABLED=true
export SOOTHE_SUBAGENTS_PLAN_ENABLED=true
export SOOTHE_SUBAGENTS_TACITUS_ENABLED=true
export SOOTHE_SUBAGENTS_TACITUS_CONFIG_LLM_ROLE=fast
export SOOTHE_SUBAGENTS_TACITUS_CONFIG_EFFORT=normal
```

### Persistence

```bash
export SOOTHE_PERSISTENCE_DEFAULT_BACKEND=sqlite
export SOOTHE_PERSISTENCE_POSTGRES_BASE_DSN="postgresql://user:pass@host:port"
export SOOTHE_PERSISTENCE_CHECKPOINT_SQLITE_PATH=/path/to/checkpoints.db
export SOOTHE_PERSISTENCE_METADATA_SQLITE_PATH=/path/to/metadata.db
```

### Vector Stores

```bash
export SOOTHE_VECTOR_STORE_ROUTER_DEFAULT="sqlite_vec_default:soothe_default"
```

### Security

```bash
export SOOTHE_SECURITY_SANDBOX=false
export SOOTHE_SECURITY_ALLOW_PATHS_OUTSIDE_WORKSPACE=false
export SOOTHE_SECURITY_REQUIRE_APPROVAL_FOR_OUTSIDE_PATHS=true
```

## Nested Field Mapping

Pydantic nested fields map to env vars with underscore path:

```yaml
# YAML
agent:
  autonomous:
    enabled_by_default: false
    max_iterations: 10
```

Maps to:

```bash
# Environment
export SOOTHE_AGENT_AUTONOMOUS_ENABLED_BY_DEFAULT=false
export SOOTHE_AGENT_AUTONOMOUS_MAX_ITERATIONS=10
```

**Rule**: Replace dots and colons with underscores, uppercase, add `SOOTHE_` prefix.

### Complex Examples

```yaml
# YAML
agent:
  loop:
    limits:
      tool_call_limit:
        global_thread_limit: 150
```

Maps to:

```bash
export SOOTHE_STRANGE_LOOP_LIMITS_TOOL_CALL_LIMIT_GLOBAL_THREAD_LIMIT=150
```

```yaml
# YAML
observability:
  langfuse:
    enabled: true
    public_key: ${LANGFUSE_PUBLIC_KEY}
```

Maps to:

```bash
export SOOTHE_OBSERVABILITY_LANGFUSE_ENABLED=true
export SOOTHE_OBSERVABILITY_LANGFUSE_PUBLIC_KEY=pk-xxx
```

## Special Environment Variables

### Provider Configuration

When using `${ENV_VAR}` syntax in YAML:

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}  # Resolves to OPENAI_API_KEY env var
    api_base_url: ${OPENAI_BASE_URL}  # Optional override
```

Set:

```bash
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://custom-openai-endpoint.com/v1  # Optional
```

### DashScope (OpenAI-Compatible)

```bash
export DASHSCOPE_API_KEY=your-dashscope-key
export DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export DASHSCOPE_CP_API_KEY=your-coding-plan-key  # Coding-plan endpoint
export DASHSCOPE_CP_BASE_URL=https://coding-plan-endpoint.com/v1
```

### MCP Server Tokens

```bash
export LINEAR_MCP_TOKEN=your-linear-token
export GITHUB_MCP_TOKEN=your-github-token
```

Used in:

```yaml
mcp_servers:
  - name: linear
    auth:
      headers:
        Authorization: "Bearer ${LINEAR_MCP_TOKEN}"
```

## Environment Variable Interpolation

Soothe supports `${ENV_VAR}` syntax in YAML for secrets:

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}  # ✅ Interpolated

persistence:
  postgres_base_dsn: ${POSTGRES_DSN}  # ✅ Interpolated

observability:
  langfuse:
    public_key: ${LANGFUSE_PUBLIC_KEY}  # ✅ Interpolated
```

**Key features:**

- **Secret injection**: Keep secrets out of config files
- **Fallback**: If env var is unset, YAML value remains as string
- **Nested support**: Works in any string field

### Example

```bash
# Set the environment variable
export OPENAI_API_KEY=sk-prod-key-123

# Config file references it
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

# Runtime resolves to:
providers:
  - name: openai
    api_key: "sk-prod-key-123"  # Resolved value
```

## Docker Environment Variables

When running in Docker, set variables via `docker-compose.yml`:

```yaml
services:
  soothe:
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SOOTHE_OBSERVABILITY_VERBOSITY=detailed
      - SOOTHE_PERSISTENCE_DEFAULT_BACKEND=postgresql
      - SOOTHE_PERSISTENCE_POSTGRES_BASE_DSN=postgresql://postgres:postgres@db:5432
    volumes:
      - ~/.soothe:/root/.soothe
```

## Shell Configuration

Add to your shell profile (`~/.bashrc`, `~/.zshrc`):

```bash
# Soothe configuration
export SOOTHE_HOME=~/.soothe
export SOOTHE_CONFIG_FILE=~/.soothe/config.yml

# Provider keys
export OPENAI_API_KEY=sk-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx

# Optional tools
export TAVILY_API_KEY=tvly-xxx
export DEEPXIV_API_KEY=your-key

# Logging (optional)
export SOOTHE_LOG_LEVEL=INFO
export SOOTHE_OBSERVABILITY_VERBOSITY=normal
```

## Environment Variable Priority

Configuration priority (highest to lowest):

1. **Command-line arguments** - `--config`, `--debug`, etc.
2. **Environment variables** - `SOOTHE_*` variables
3. **YAML configuration file** - `config.yml`
4. **Built-in defaults** - Pydantic model defaults

### Example Override Chain

```bash
# 1. YAML file default
router:
  default: "openai:gpt-4o-mini"

# 2. Environment variable override
export SOOTHE_ROUTER_DEFAULT="openai:gpt-4o"

# 3. CLI argument override (highest priority)
soothe --model openai:o3-mini "your prompt"
```

## Checking Environment Variables

### Verify Variables

```bash
# Check Soothe variables
env | grep SOOTHE

# Check provider keys
env | grep OPENAI
env | grep ANTHROPIC
env | grep TAVILY

# Check config file path
echo $SOOTHE_CONFIG_FILE
```

### Debug Configuration

```bash
# Enable debug mode to see resolved config
soothe --debug "test prompt"

# Or via environment
export SOOTHE_DEBUG=true
soothe "test prompt"
```

## Common Patterns

### Production Setup

```bash
# ~/.bashrc or ~/.zshrc
export SOOTHE_CONFIG_FILE=/etc/soothe/config.yml
export SOOTHE_PERSISTENCE_DEFAULT_BACKEND=postgresql
export SOOTHE_PERSISTENCE_POSTGRES_BASE_DSN=postgresql://user:pass@db:5432

export OPENAI_API_KEY=sk-prod-xxx
export LANGFUSE_PUBLIC_KEY=pk-prod-xxx
export LANGFUSE_SECRET_KEY=sk-prod-xxx
```

### Development Setup

```bash
# ~/.bashrc or ~/.zshrc
export SOOTHE_DEBUG=true
export SOOTHE_OBSERVABILITY_VERBOSITY=detailed
export SOOTHE_CONFIG_FILE=~/.soothe/config.dev.yml

export OPENAI_API_KEY=sk-dev-xxx
export TAVILY_API_KEY=tvly-dev-xxx
export DEEPXIV_API_KEY=dev-xxx
```

### Testing Setup

```bash
# For CI/CD or testing
export SOOTHE_PERSISTENCE_DEFAULT_BACKEND=sqlite
export SOOTHE_AGENT_AUTONOMOUS_ENABLED_BY_DEFAULT=false
export SOOTHE_STRANGE_LOOP_MAX_ITERATIONS=5
export SOOTHE_OBSERVABILITY_LANGFUSE_ENABLED=false

export OPENAI_API_KEY=sk-test-xxx
```

## Environment Variable Reference Table

| Variable | Section | Description |
|----------|---------|-------------|
| `SOOTHE_HOME` | Base | Home directory |
| `SOOTHE_CONFIG_FILE` | Base | Config file path |
| `SOOTHE_DEBUG` | Runtime | Debug mode |
| `SOOTHE_LOG_LEVEL` | Runtime | Log level |
| `OPENAI_API_KEY` | Provider | OpenAI API key |
| `ANTHROPIC_API_KEY` | Provider | Anthropic API key |
| `TAVILY_API_KEY` | Tools | Tavily search |
| `SERPER_API_KEY` | Tools | Google Serper |
| `JINA_API_KEY` | Tools | Jina reader |
| `DEEPXIV_API_KEY` | Tools | DeepXiv academic |
| `GITHUB_TOKEN` | Tools | GitHub search |
| `LANGFUSE_PUBLIC_KEY` | Tracing | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Tracing | Langfuse secret key |
| `DASHSCOPE_API_KEY` | Provider | DashScope key |
| `SOOTHE_ROUTER_DEFAULT` | Model | Default model |
| `SOOTHE_AGENT_NAME` | Agent | Agent name |
| `SOOTHE_OBSERVABILITY_VERBOSITY` | Logging | Verbosity level |

## Troubleshooting

### Variable Not Applied

If env variable doesn't take effect:

1. **Check prefix**: Must start with `SOOTHE_` (except provider keys)
2. **Check spelling**: Match YAML field path exactly
3. **Check priority**: CLI args override env vars
4. **Check shell**: Add to `~/.bashrc` or `~/.zshrc`, reload shell

```bash
# Reload shell configuration
source ~/.bashrc  # or ~/.zshrc

# Or restart shell
exec bash
```

### Config File Interpolation

If `${ENV_VAR}` not resolved:

```bash
# Verify env var is set
echo $OPENAI_API_KEY

# Check YAML syntax (no quotes around ${})
api_key: ${OPENAI_API_KEY}  # ✅ Correct
api_key: "${OPENAI_API_KEY}"  # ❌ Wrong (quotes prevent interpolation)
```

### Docker Missing Variables

In Docker, ensure variables are passed:

```bash
# Check running container variables
docker exec soothe env | grep SOOTHE

# Pass variables in compose
docker-compose up -d
# variables from .env file are auto-loaded
```

---

**See also:**

- [YAML Reference](yaml-reference.md) - Complete YAML schema
- [Common Patterns](common-patterns.md) - Real-world examples
- [Provider Setup](provider-setup.md) - Provider configuration guide
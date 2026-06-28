# Common Configuration Patterns

Real-world configuration examples for typical Soothe use cases.

## Quick Start Patterns

### Minimal Configuration

**Use case**: Quick start with OpenAI

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o-mini

router:
  default: openai:gpt-4o-mini

embedding_dims: 1536
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

### Development Configuration

**Use case**: Local development with debugging

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o-mini
      - gpt-4o

router:
  default: openai:gpt-4o-mini
  think: openai:gpt-4o
  fast: openai:gpt-4o-mini

agent:
  autonomous:
    enabled: false
  loop:
    max_iterations: 10

observability:
  verbosity: debug
  console:
    enabled: true
    level: INFO

debug: true
```

## Production Patterns

### High-Performance Production

**Use case**: Production deployment with PostgreSQL, monitoring

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o
      - gpt-4o-mini
      - o3-mini
      - text-embedding-3-small

router:
  default: openai:gpt-4o-mini
  think: openai:o3-mini
  fast: openai:gpt-4o-mini
  image: openai:gpt-4o
  embedding: openai:text-embedding-3-small

embedding_dims: 1536

agent:
  autonomous:
    enabled: true
    max_iterations: 15
    max_parallel_goals: 5
    max_loops: 8
  loop:
    max_iterations: 20
    context_window_limit: 200000
    concurrency:
      max_parallel_steps: 4
      global_max_llm_calls: 50
    llm_rate_limit:
      concurrent_limit: 20

persistence:
  default_backend: postgresql
  postgres_base_dsn: ${POSTGRES_DSN}
  postgres_pool_min_size: 8
  checkpointer_pool_size: 32
  sloop_pool_size: 32

vector_stores:
  - name: pgvector_prod
    provider_type: pgvector
    dsn: ${POSTGRES_VECTOR_DSN}
    index_type: hnsw

vector_store_router:
  default: pgvector_prod:soothe_production

observability:
  verbosity: normal
  langfuse:
    enabled: true
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
    environment: production
    sample_rate: 0.1

security:
  sandbox: false
  require_approval_for_outside_paths: false
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-prod-xxx
export POSTGRES_DSN=postgresql://user:pass@db-host:5432
export POSTGRES_VECTOR_DSN=postgresql://user:pass@db-host:5432/soothe_vectors
export LANGFUSE_PUBLIC_KEY=pk-prod-xxx
export LANGFUSE_SECRET_KEY=sk-prod-xxx
```

### Kubernetes Deployment

**Use case**: Running in Kubernetes with secrets

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

router:
  default: openai:gpt-4o-mini

persistence:
  default_backend: postgresql
  postgres_base_dsn: ${POSTGRES_DSN}
  postgres_pool_min_size: 4
  checkpointer_pool_size: 16

agent:
  autonomous:
    max_loops: 10

observability:
  verbosity: normal
  langfuse:
    enabled: true
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
```

**Kubernetes secrets**:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: soothe-secrets
type: Opaque
data:
  openai-api-key: <base64-encoded-key>
  postgres-dsn: <base64-encoded-dsn>
  langfuse-public-key: <base64-encoded-key>
  langfuse-secret-key: <base64-encoded-key>
```

## Multi-Provider Patterns

### Multiple LLM Providers

**Use case**: Use different providers for different tasks

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o
      - gpt-4o-mini
      - o3-mini
  
  - name: anthropic
    provider_type: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    models:
      - claude-sonnet-4-20250514
  
  - name: dashscope
    provider_type: openai
    api_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ${DASHSCOPE_API_KEY}
    models:
      - qwen-max

router:
  default: openai:gpt-4o-mini
  think: anthropic:claude-sonnet-4-20250514
  fast: dashscope:qwen-max
  image: openai:gpt-4o
  embedding: openai:text-embedding-3-small
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx
export DASHSCOPE_API_KEY=your-dashscope-key
```

### Local + Cloud Hybrid

**Use case**: Use local models for cheap tasks, cloud for complex reasoning

```yaml
providers:
  - name: ollama
    provider_type: ollama
    models:
      - llama3.1:8b
      - mistral:7b
  
  - name: lmstudio
    provider_type: limited_openai
    api_base_url: http://localhost:1234/v1
    api_key: lmstudio
    models:
      - gemma-2-9b
  
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o
      - o3-mini

router:
  default: lmstudio:gemma-2-9b
  fast: ollama:llama3.1:8b
  think: openai:o3-mini
  image: openai:gpt-4o
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-xxx

# Run local models
ollama serve
ollama pull llama3.1:8b
ollama pull mistral:7b
```

## Tool Configuration Patterns

### Research Agent

**Use case**: Agent focused on web research and academic papers

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o-mini
      - gpt-4o

router:
  default: openai:gpt-4o-mini
  think: openai:gpt-4o

tools:
  execution:
    enabled: false  # Disable shell execution
  file_ops:
    enabled: false  # Disable file operations
  wizsearch:
    enabled: true
    default_engines:
      - tavily
      - duckduckgo
      - brave
    max_results_per_engine: 15
    timeout: 45
  deepxiv:
    enabled: true
    token: ${DEEPXIV_API_KEY}
    timeout: 90
    max_retries: 5

subagents:
  explore:
    enabled: false  # No file exploration
  plan:
    enabled: true
  tacitus:
    enabled: true
    config:
      llm_role: think
      synthesis_role: think
      effort: thorough
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-xxx
export TAVILY_API_KEY=tvly-xxx
export DEEPXIV_API_KEY=your-deepxiv-key
```

### Code Assistant

**Use case**: Agent focused on code generation and analysis

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o
      - gpt-4o-mini

router:
  default: openai:gpt-4o-mini
  think: openai:gpt-4o

tools:
  execution:
    enabled: true
  file_ops:
    enabled: true
  wizsearch:
    enabled: false  # No web search
  http_requests:
    enabled: false  # No HTTP requests

subagents:
  explore:
    enabled: true
    config:
      thoroughness: thorough
      max_iterations:
        thorough: 20
  plan:
    enabled: true
  tacitus:
    enabled: false  # No deep research
```

### Safe Assistant

**Use case**: Agent with strict security policies

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

router:
  default: openai:gpt-4o-mini

security:
  sandbox: true
  allow_paths_outside_workspace: false
  require_approval_for_outside_paths: true
  denied_paths:
    - /etc/**
    - /bin/**
    - ~/.ssh/**
    - ~/.aws/**
    - '**/.env'
    - '**/secrets.json'
  allowed_paths:
    - ~/workspace/**  # Only workspace
  denied_file_types:
    - .exe
    - .sh
  require_approval_for_file_types:
    - .env
    - .pem
    - .key

tools:
  execution:
    enabled: false  # Disable shell execution
  file_ops:
    enabled: true
  http_requests:
    enabled: false  # No external requests
```

## Autonomous Mode Patterns

### Background Task Runner

**Use case**: Autonomous agent running scheduled tasks

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

router:
  default: openai:gpt-4o-mini

agent:
  autonomous:
    enabled: true
    max_iterations: 20
    max_retries: 3
    max_total_goals: 100
    max_goal_depth: 10
    max_parallel_goals: 5
    max_loops: 10
    loop_idle_timeout: 600
    
    dreaming_enabled: true
    dreaming_consolidation_interval: 600
    
    scheduler_enabled: true
    max_scheduled_tasks: 200
    
    webhooks:
      on_goal_completed: ${WEBHOOK_URL}/goal-completed
      on_error: ${WEBHOOK_URL}/error
  
  protocols:
    durability:
      thread_inactivity_timeout_hours: 168  # 7 days

persistence:
  default_backend: postgresql
  postgres_base_dsn: ${POSTGRES_DSN}

observability:
  verbosity: debug
  langfuse:
    enabled: true
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-xxx
export POSTGRES_DSN=postgresql://user:pass@db:5432
export WEBHOOK_URL=https://hooks.example.com/soothe
export LANGFUSE_PUBLIC_KEY=pk-xxx
export LANGFUSE_SECRET_KEY=sk-xxx
```

### Limited Autonomous Mode

**Use case**: Controlled autonomous with strict limits

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

router:
  default: openai:gpt-4o-mini

agent:
  autonomous:
    enabled: false  # Off by default
    max_iterations: 5
    max_retries: 1
    max_total_goals: 10
    max_goal_depth: 3
    max_parallel_goals: 1
    max_loops: 2
    
    dreaming_enabled: false
    scheduler_enabled: false
  
  loop:
    max_iterations: 10
    concurrency:
      max_parallel_steps: 1
      max_parallel_tools: 5
      global_max_llm_calls: 10
    tool_call_limit:
      global_thread_limit: 50
      global_run_limit: 20
```

## Vector Store Patterns

### SQLite Vec (Default)

**Use case**: Lightweight local vector storage

```yaml
vector_stores:
  - name: sqlite_vec_default
    provider_type: sqlite_vec

vector_store_router:
  default: sqlite_vec_default:soothe_default

embedding_dims: 1536
```

### PostgreSQL Vector

**Use case**: Production vector storage with pgvector

```yaml
vector_stores:
  - name: pgvector_main
    provider_type: pgvector
    dsn: ${POSTGRES_VECTOR_DSN}
    pool_size: 10
    index_type: hnsw

vector_store_router:
  default: pgvector_main:soothe_production

embedding_dims: 1536

persistence:
  postgres_base_dsn: ${POSTGRES_DSN}
```

**Environment**:

```bash
export POSTGRES_DSN=postgresql://user:pass@db-host:5432
export POSTGRES_VECTOR_DSN=postgresql://user:pass@db-host:5432/vectors
```

### Weaviate Cloud

**Use case**: Weaviate managed service

```yaml
vector_stores:
  - name: weaviate_cloud
    provider_type: weaviate
    url: ${WEAVIATE_URL}
    api_key: ${WEAVIATE_API_KEY}
    grpc_port: 443

vector_store_router:
  default: weaviate_cloud:soothe_production

embedding_dims: 1536
```

**Environment**:

```bash
export WEAVIATE_URL=https://your-cluster.weaviate.cloud
export WEAVIATE_API_KEY=your-weaviate-key
```

## Daemon Patterns

### Local Development Daemon

**Use case**: Run daemon locally for development

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

router:
  default: openai:gpt-4o-mini

agent:
  autonomous:
    max_loops: 4
    poll_interval: 2

observability:
  verbosity: debug
  console:
    enabled: true
```

**Start daemon**:

```bash
soothe daemon start
soothe status
```

### Remote Daemon

**Use case**: Connect to remote daemon server

```bash
# Set remote daemon address
export SOOTHE_DAEMON_URL=http://daemon-server:8765

# Or use WebSocket
export SOOTHE_DAEMON_URL=ws://daemon-server:8765

# Connect to remote
soothe --remote "your prompt"
```

## Logging Patterns

### Verbose Logging

**Use case**: Maximum logging for debugging

```yaml
observability:
  verbosity: debug
  log_file_level: DEBUG
  log_file_path: ~/.soothe/logs/debug.log
  log_file_max_bytes: 10485760  # 10 MB
  log_file_backup_count: 5
  
  console:
    enabled: true
    level: DEBUG
    stream: stderr
  
  thread_logging_enabled: true
  thread_logging_retention_days: 7

debug: true
```

### Minimal Logging

**Use case**: Production with minimal logs

```yaml
observability:
  verbosity: quiet
  log_file_level: WARNING
  log_file_max_bytes: 5242880  # 5 MB
  log_file_backup_count: 3
  
  console:
    enabled: false
  
  thread_logging_enabled: false

debug: false
```

## MCP Server Patterns

### Multiple MCP Servers

**Use case**: Connect to several MCP servers

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/workspace"
    defer: true
  
  - name: github
    transport: stdio
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
    defer: true
  
  - name: linear
    transport: streamable_http
    url: https://mcp.linear.app/sse
    auth:
      headers:
        Authorization: "Bearer ${LINEAR_MCP_TOKEN}"
    defer: true
```

**Environment**:

```bash
export GITHUB_TOKEN=ghp-xxx
export LINEAR_MCP_TOKEN=your-linear-token
```

## Memory Patterns

### Enhanced Memory

**Use case**: Agent with sophisticated memory capabilities

```yaml
agent:
  protocols:
    memory:
      enabled: true
      persist_dir: ~/.soothe/memory
      llm_chat_role: fast
      llm_embed_role: embedding
      enable_embeddings: true
      enable_auto_categorization: true
      enable_category_summaries: true
      memory_categories:
        - name: personal_info
          description: Personal information and identity
        - name: preferences
          description: User preferences and interests
        - name: knowledge
          description: Facts and learned information
        - name: experiences
          description: Past experiences and events
        - name: goals
          description: Goals and objectives
        - name: projects
          description: Project details and context
        - name: code_patterns
          description: Learned coding patterns and best practices

vector_stores:
  - name: pgvector_memory
    provider_type: pgvector
    dsn: ${POSTGRES_DSN}

vector_store_router:
  default: pgvector_memory:soothe_memory
```

### Minimal Memory

**Use case**: Disable memory for fresh sessions

```yaml
agent:
  protocols:
    memory:
      enabled: false

memory: []  # No AGENTS.md files
```

## Subagent Patterns

### Custom Subagent Models

**Use case**: Use different models for different subagents

```yaml
subagents:
  explore:
    enabled: true
    model: openai:gpt-4o-mini  # Fast exploration
    config:
      thoroughness: medium
  
  plan:
    enabled: true
    model: openai:o3-mini  # Stronger planning
  
  tacitus:
    enabled: true
    model: anthropic:claude-sonnet-4-20250514  # Best for research
    config:
      llm_role: think
      synthesis_role: think
      effort: thorough
```

### Disabled Subagents

**Use case**: Run without subagents (single agent mode)

```yaml
subagents:
  explore:
    enabled: false
  plan:
    enabled: false
  tacitus:
    enabled: false
```

## Testing Patterns

### Unit Testing Configuration

**Use case**: Minimal config for tests

```yaml
providers:
  - name: mock
    provider_type: openai
    api_key: mock-key

router:
  default: mock:gpt-4o-mini

agent:
  autonomous:
    enabled: false
  loop:
    max_iterations: 3

observability:
  verbosity: quiet
  langfuse:
    enabled: false

persistence:
  default_backend: sqlite
  checkpoint_sqlite_path: /tmp/test_checkpoints.db
  metadata_sqlite_path: /tmp/test_metadata.db
```

### Integration Testing

**Use case**: Full stack testing

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_TEST_API_KEY}

router:
  default: openai:gpt-4o-mini

agent:
  autonomous:
    max_iterations: 5
  loop:
    max_iterations: 10
    concurrency:
      global_max_llm_calls: 10

persistence:
  default_backend: sqlite
  checkpoint_sqlite_path: /tmp/integration_checkpoints.db

observability:
  verbosity: debug
  langfuse:
    enabled: true
    environment: testing
```

## Complete Example Configurations

### Full Production Config

See `config/config.template.yml` for the complete production-ready configuration with all options documented.

### Development Config

See `config/develop/config.yml` for development defaults with DashScope/OpenAI examples.

---

**See also:**

- [YAML Reference](yaml-reference.md) - Complete field documentation
- [Environment Variables](environment-variables.md) - Env var reference
- [Provider Setup](provider-setup.md) - Provider configuration guide
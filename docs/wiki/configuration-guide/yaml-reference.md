# YAML Configuration Reference

Complete reference for all YAML configuration options in Soothe.

## Table of Contents

- [Configuration File Structure](#configuration-file-structure)
- [Providers](#providers)
- [Router](#router)
- [Agent](#agent)
- [Tools](#tools)
- [Subagents](#subagents)
- [MCP Servers](#mcp-servers)
- [Plugins & Skills](#plugins--skills)
- [Observability](#observability)
- [Persistence](#persistence)
- [Vector Stores](#vector-stores)
- [Security](#security)

---

## Configuration File Structure

Soothe configuration YAML files follow a hierarchical structure. All fields have sensible defaults in the Pydantic models (`packages/soothe/src/soothe/config/models.py`).

```yaml
providers: [...]
router: {...}
embedding_dims: 1536
agent: {...}
tools: {...}
subagents: {...}
mcp_servers: [...]
observability: {...}
persistence: {...}
vector_stores: [...]
security: {...}
```

**Key features:**

- **Environment variable interpolation**: Use `${ENV_VAR}` syntax for secrets
- **Nested configuration**: Hierarchical sections for logical grouping
- **Pydantic validation**: All fields validated at runtime
- **Progressive disclosure**: Advanced options have sensible defaults

---

## Providers

Configure LLM and embedding model providers.

### Provider Configuration

```yaml
providers:
  - name: openai
    provider_type: openai  # openai | limited_openai | anthropic | ollama
    api_key: ${OPENAI_API_KEY}  # Required, supports ${ENV_VAR}
    api_base_url: null  # Optional, for OpenAI-compatible APIs
    models:
      - gpt-4o
      - gpt-4o-mini
      - o3-mini
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | Required | Provider identifier (used in router) |
| `provider_type` | str | `"openai"` | Provider type for `init_chat_model` |
| `api_key` | str | None | API key, supports `${ENV_VAR}` syntax |
| `api_base_url` | str | None | Base URL for OpenAI-compatible APIs |
| `models` | list[str] | [] | Available model names (documentation) |

**Provider Types:**

- `openai`: Standard OpenAI API (full compatibility)
- `limited_openai`: Limited OpenAI-compatible APIs (LMStudio, MLXServer, certain GLM deployments)
  - Accept json_schema response_format but may return empty content
  - Return structured JSON in reasoning_content field
  - Limited tool_choice support (string values: "none", "auto", "required")
- `anthropic`: Anthropic Claude API
- `ollama`: Ollama local inference

### OpenAI-Compatible Providers

DashScope, OpenRouter, vLLM:

```yaml
providers:
  - name: dashscope
    provider_type: openai
    api_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ${DASHSCOPE_API_KEY}
    models: [qwen-max]
```

### Local Models (LMStudio, Ollama)

```yaml
providers:
  - name: lmstudio
    provider_type: limited_openai
    api_base_url: http://localhost:1234/v1
    api_key: "lmstudio"
    models: [google/gemma-4-26b-a4b]
```

---

## Router

Map purpose-based roles to provider:model pairs.

### Model Router

```yaml
router:
  default: "openai:gpt-4o-mini"
  think: null    # Falls back to default
  fast: null     # Falls back to default
  image: null    # Falls back to default
  embedding: null  # Falls back to default
```

**Roles:**

| Role | Purpose | Default Behavior |
|------|---------|------------------|
| `default` | Main orchestrator reasoning, CoreAgent | `"openai:gpt-4o-mini"` |
| `think` | Planning, complex reasoning | Falls back to `default` |
| `fast` | Classification, routing, subagents | Falls back to `default` |
| `image` | Vision/image understanding | Falls back to `default` |
| `embedding` | Vector operations, semantic memory | Falls back to `default` |

**Format**: `"provider_name:model_name"`

```yaml
router:
  default: "coding-plan:glm-5"
  fast: "coding-plan:kimi-k2.5"
  think: "coding-plan:glm-5"
  image: "coding-plan:qwen3.6-plus"
  embedding: "dashscope:multimodal-embedding-v1"
```

---

## Agent

Unified agent configuration (identity, behavior, autonomous mode, loop, protocols).

### Basic Agent Identity

```yaml
agent:
  name: Soothe
  system_prompt: null  # Custom system prompt override
```

### Autonomous Mode (24/7 Self-Running)

```yaml
agent:
  autonomous:
    enabled_by_default: false
    
    # Goal execution limits
    max_iterations: 10
    max_retries: 2
    max_total_goals: 50
    max_goal_depth: 5
    max_parallel_goals: 3
    enable_dynamic_goals: true
    
    # Orchestration
    max_send_backs: 3
    checkpoint_interval: 10
    
    # Dreaming (background consolidation)
    dreaming_enabled: true
    dreaming_consolidation_interval: 300  # seconds
    dreaming_health_check_interval: 60   # seconds
    
    # Scheduler
    scheduler_enabled: true
    max_scheduled_tasks: 100
    webhooks: {}
    
    # Loop pool (RFC-222)
    max_loops: 4
    loop_idle_timeout: 300
    poll_interval: 5
    dreaming_poll_interval: 60
    
    # Context projection (RFC-222)
    context_projection:
      max_findings: 20
      max_files: 50
      max_plan_steps: 30
      context_retention_hours: 168
    
    # Workspace reservation
    workspace_reservation:
      enabled: true
      strict_overlap: true
```

**Autonomous Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled_by_default` | bool | `false` | Enable autonomous mode for new threads |
| `max_iterations` | int | `10` | Max iterations per autonomous thread |
| `max_retries` | int | `2` | Max retries per goal on failure |
| `max_total_goals` | int | `50` | Maximum goals allowed |
| `max_goal_depth` | int | `5` | Maximum hierarchy depth |
| `max_parallel_goals` | int | `3` | Maximum goals running simultaneously |
| `max_loops` | int | `4` | Maximum concurrent StrangeLoop workers |
| `loop_idle_timeout` | int | `300` | Seconds to keep idle loop |
| `poll_interval` | int | `5` | Autopilot scheduling tick interval |

### Agent Loop (CoreAgent Internal Tuning)

```yaml
agent:
  loop:
    enabled: true
    max_iterations: 10
    max_subagent_tasks_per_wave: 4
    strange_loop_output_contract_enabled: true
    prior_conversation_limit: 10
    context_window_limit: 200000
    
    # Response shape
    goal_completion_mode: llm_only  # llm_only | heuristic_only | hybrid
    final_response: adaptive        # adaptive | always_synthesize
    
    # Context window management (RFC-224)
    context_overflow_threshold_pct: 0.80
    context_compaction_target_pct: 0.60
    step_context_check_enabled: false
    
    # Output streaming (RFC-614)
    output_streaming:
      mode: adaptive  # batch | adaptive | streaming
      streaming_interval_ms: 300
      adaptive_threshold_chars: 500
      adaptive_block_chars: 500
      adaptive_block_interval_ms: 250
      file_output_threshold_chars: 0
      file_output_preview_chars: 500
      file_output_dir: null
      message_coalesce_enabled: true
      tool_batch_enabled: true
      tool_batch_interval_ms: 200
    
    # Working memory
    working_memory:
      enabled: true
      max_inline_chars: 4000
      max_entry_chars_before_spill: 1500
    
    # Goal context
    goal_context:
      plan_limit: 10
      execute_limit: 10
      enabled: true
    
    # Report output
    report_output:
      display_threshold: 20000
      preview_chars: 500
      synthesis_max_chars: 0
    
    # Plan-phase ledger projection caps
    plan_prompt_ledger:
      plan_ledger_max_messages: 0  # 0 = unlimited
      plan_ledger_max_total_chars: 0
      plan_ledger_max_message_chars: 0
    
    # Infrastructure limits
    limits:
      max_parallel_goals: 1
      max_parallel_steps: 2
      max_parallel_subagents: 4
      max_parallel_tools: 15
      global_max_llm_calls: 5
      step_parallelism: dependency  # sequential | dependency | max
      llm_rpm_limit: 120
      llm_concurrent_limit: 10
      llm_call_timeout_seconds: 120
      llm_call_timeout_adaptive: true
      llm_call_timeout_max_seconds: 120
      llm_retry_on_timeout: true
      llm_max_timeout_retries: 2
      llm_timeout_retry_multiplier: 2.0
      recovery:
        progressive_checkpoints: true
        auto_resume_on_start: false
      tool_call_limit:
        global_thread_limit: 150
        global_run_limit: 56
        tool_specific_limits:
          wizsearch_search:
            thread_limit: 5
            run_limit: 3
      tool_retry:
        max_retries: 3
        backoff_factor: 2.0
        initial_delay: 1.0
```

**Loop Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable agent loop mode |
| `max_iterations` | int | `10` | Maximum loop iterations |
| `context_window_limit` | int | `200000` | Token limit for context |
| `goal_completion_mode` | str | `"llm_only"` | Completion detection mode |
| `final_response` | str | `"adaptive"` | Final response synthesis mode |

### Protocols (Backend Selection)

```yaml
agent:
  protocols:
    memory:
      enabled: true
      persist_dir: null
      llm_chat_role: fast
      llm_embed_role: embedding
      enable_embeddings: true
      enable_auto_categorization: true
      enable_category_summaries: true
      memory_categories:
        - name: personal_info
          description: Personal information
        - name: preferences
          description: User preferences
    
    planner:
      model: think  # Use "think" role for complex reasoning
      routing: auto  # auto | always_direct | always_planner
    
    policy:
      profile: standard
    
    durability:
      backend: default
      checkpointer: default
      persist_dir: null
      thread_inactivity_timeout_hours: 72
```

---

## Tools

Configure tool groups available to the agent.

### Tool Groups

```yaml
tools:
  execution:
    enabled: true  # run_command, run_python, run_background
  
  file_ops:
    enabled: true  # ls, read_file, write_file, edit_file, glob, grep
  
  datetime:
    enabled: true  # current_datetime
  
  data:
    enabled: true  # inspect_data, summarize_data, check_data_quality
  
  wizsearch:
    enabled: true
    default_engines:
      - tavily
      - duckduckgo
    max_results_per_engine: 10
    timeout: 30
  
  image:
    enabled: true  # analyze_image, extract_text_from_image
  
  audio:
    enabled: true  # transcribe_audio, audio_qa
  
  video:
    enabled: true  # analyze_video, get_video_info
  
  http_requests:
    enabled: true
    allow_dangerous_requests: true
    headers: {}
    verify_ssl: true
  
  deepxiv:
    enabled: true
    token: null  # Set DEEPXIV_API_KEY or DEEPXIV_TOKEN
    timeout: 60
    max_retries: 3
```

**WebSearchConfig Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable web search tools |
| `default_engines` | list[str] | `["tavily"]` | Default search engines |
| `max_results_per_engine` | int | `10` | Results per engine |
| `timeout` | int | `30` | Request timeout seconds |

---

## Subagents

Configure specialized helper agents.

### Built-in Subagents

```yaml
subagents:
  explore:
    enabled: true
    model: null  # Falls back to fast role
    transport: local  # local | acp | a2a | langgraph
    url: null
    config:
      thoroughness: medium  # quick | medium | thorough
      max_iterations:
        quick: 6
        medium: 10
        thorough: 16
      max_read_lines: 50
      max_matches_returned: 5
      max_history_messages_for_model: 8
      max_tool_output_chars_per_turn: 2000
      early_stop_no_new_findings_turns: 2
      max_findings_for_synthesis: 20
      enable_semantic_similarity: true
      semantic_similarity_timeout_seconds: 10
      synthesis_timeout_seconds: 120
    runtime_dir: ''  # Defaults to SOOTHE_HOME/agents/explore/
  
  plan:
    enabled: true
    model: null
    transport: local
    url: null
    config: {}
    runtime_dir: ''
  
  tacitus:
    enabled: true
    model: null
    transport: local
    url: null
    config:
      llm_role: fast
      synthesis_role: fast  # Use "think" for higher quality
      effort: normal  # minimal | normal | thorough
    runtime_dir: ''
```

**SubagentConfig Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable this subagent |
| `model` | str | None | Override model (falls back to role) |
| `transport` | str | `"local"` | Transport: local/acp/a2a/langgraph |
| `url` | str | None | Remote URL for non-local transport |
| `config` | dict | {} | Subagent-specific configuration |
| `runtime_dir` | str | "" | Runtime directory |

---

## MCP Servers

Configure MCP (Model Context Protocol) servers.

### MCP Server Configuration

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio  # stdio | sse | streamable_http | websocket
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    env: {}
    enabled: true
    defer: true  # Progressive disclosure (default)
    tool_filter: null  # Allowlist glob patterns
    timeout_seconds: 30.0
    request_timeout_seconds: 60.0
    tool_timeout_seconds: 600.0
  
  - name: linear
    transport: streamable_http
    url: https://mcp.linear.app/sse
    auth:
      headers:
        Authorization: "Bearer ${LINEAR_MCP_TOKEN}"
    enabled: true
    defer: true
```

**MCPServerConfig Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | Required | Unique server identifier |
| `transport` | str | `"stdio"` | Transport type |
| `command` | str | None | Command for stdio transport |
| `args` | list[str] | [] | Command arguments |
| `env` | dict | {} | Environment variables |
| `url` | str | None | URL for remote transports |
| `auth` | dict | None | Bearer/header auth |
| `enabled` | bool | `true` | Enable this server |
| `defer` | bool | `true` | Progressive disclosure |

### Progressive MCP Configuration

```yaml
progressive_mcp:
  budget_pct: 0.01  # Fraction of context_window_limit
  max_listing_chars_per_entry: 250
  min_listing_chars_per_entry: 20
```

---

## Plugins & Skills

Configure plugin loading and skill discovery.

### Plugin Configuration

```yaml
plugins:
  - name: my-plugin
    enabled: true
    module: "my_package:MyPlugin"  # Python import path
    config:
      custom_setting: value
```

### Skills Configuration

```yaml
skills:
  - /path/to/skills/directory
  - /path/to/SKILL.md

progressive_skills:
  budget_pct: 0.01
  max_listing_chars_per_entry: 250
  min_listing_chars_per_entry: 20
```

### Memory Configuration

```yaml
memory:
  - /path/to/AGENTS.md
  - /path/to/memory/directory
```

---

## Observability

Configure logging, tracing, and monitoring.

### Logging Configuration

```yaml
observability:
  log_file_level: INFO  # DEBUG | INFO | WARNING | ERROR
  log_file_path: null  # Defaults to ~/.soothe/logs/soothe.log
  log_file_max_bytes: 5242880  # 5 MB
  log_file_backup_count: 3
  
  console:
    enabled: false
    level: WARNING
    stream: stderr  # stdout | stderr
    format: '%(level_short)s %(name)s %(message)s'
  
  global_history:
    enabled: true
    max_size: 5000
    dedup_window: 10
    retention_days: 90
  
  verbosity: normal  # minimal | normal | detailed | debug
  thread_logging_enabled: true
  thread_logging_retention_days: 30
  thread_logging_max_size_mb: 100
```

### Langfuse Tracing

```yaml
observability:
  langfuse:
    enabled: false
    public_key: null  # Set via LANGFUSE_PUBLIC_KEY
    secret_key: null  # Set via LANGFUSE_SECRET_KEY
    host: null  # Defaults to https://cloud.langfuse.com
    environment: null
    release: null
    sample_rate: null
    trace_name: null
    tags: null
    user_id: null
```

**Verbosity Levels:**

| Level | Shows |
|-------|-------|
| `minimal` | Assistant text + errors |
| `normal` | Assistant text + protocol events + errors |
| `detailed` | Adds subagent events + tool activity |
| `debug` | All events (heartbeat/thinking) |

---

## Persistence

Configure storage backends for checkpoints and metadata.

### PostgreSQL Persistence (RFC-802)

```yaml
persistence:
  postgres_base_dsn: null  # Base DSN without database name
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
  soothe_postgres_dsn: postgresql://postgres:postgres@localhost:5432/soothe
  default_backend: sqlite  # sqlite | postgresql
  
  postgres_pool_min_size: 4
  checkpointer_pool_size: 24
  sloop_pool_size: 24
  postgres_pool_max_idle_seconds: 120
  postgres_pool_max_lifetime_seconds: 1800
  postgres_pool_acquire_timeout_seconds: 30
  
  metadata_sqlite_path: null  # Defaults to ~/.soothe/data/metadata.db
  checkpoint_sqlite_path: null  # Defaults to ~/.soothe/data/soothe_checkpoints.db
```

**PersistenceConfig Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `postgres_base_dsn` | str | None | Base DSN without database |
| `default_backend` | str | `"sqlite"` | Default backend type |
| `postgres_pool_min_size` | int | `4` | Min pool connections |
| `checkpointer_pool_size` | int | `24` | LangGraph pool size |
| `thread_inactivity_timeout_hours` | int | `72` | Thread timeout |

---

## Vector Stores

Configure vector storage for semantic search.

### Vector Store Providers

```yaml
vector_stores:
  - name: sqlite_vec_default
    provider_type: sqlite_vec  # pgvector | weaviate | in_memory | sqlite_vec
    
    # pgvector options
    dsn: null
    pool_size: 5
    index_type: hnsw  # hnsw | ivfflat | none
    
    # weaviate options
    url: null
    api_key: null
    grpc_port: 50051

vector_store_router:
  default: sqlite_vec_default:soothe_default
```

**VectorStoreProviderConfig Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | Required | Provider identifier |
| `provider_type` | str | `"sqlite_vec"` | Backend type |
| `dsn` | str | None | PostgreSQL DSN (pgvector) |
| `index_type` | str | `"hnsw"` | Index type (pgvector) |
| `url` | str | None | Weaviate server URL |

---

## Security

Configure security policies and sandboxing.

### Security Configuration

```yaml
security:
  sandbox: false
  allow_paths_outside_workspace: false
  require_approval_for_outside_paths: true
  
  denied_paths:
    - /etc/**
    - /bin/**
    - /sbin/**
    - /usr/**
    - /System/**
    - /Library/**
    - ~/.ssh/**
    - ~/.gnupg/**
    - ~/.aws/**
    - '**/.env'
    - '**/credentials.json'
  
  allowed_paths:
    - '**'
  
  denied_file_types: []
  require_approval_for_file_types:
    - .env
    - .pem
    - .key
```

**SecurityConfig Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sandbox` | bool | `false` | Enable sandbox mode |
| `allow_paths_outside_workspace` | bool | `false` | Allow external paths |
| `require_approval_for_outside_paths` | bool | `true` | Require approval |
| `denied_paths` | list[str] | [...] | Denied path globs |
| `allowed_paths` | list[str] | `["**"]` | Allowed path globs |

---

## UI & CLI

Configure UI preferences and CLI behavior.

### UI Configuration

```yaml
ui:
  theme: null  # Theme name for TUI

debug: false
activity_max_lines: 300
tui_debug: false

update:
  check: true  # Check for updates on startup
  auto_update: true  # Auto-update when available
```

---

## Embedding Dimensions

Configure embedding vector dimensions.

```yaml
embedding_dims: 1536  # Must match embedding model output
```

Common values:
- OpenAI `text-embedding-3-small`: 1536
- OpenAI `text-embedding-3-large`: 3072
- DashScope `multimodal-embedding-v1`: 1024

---

## Quick Reference

### Minimal Production Config

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o-mini]

router:
  default: openai:gpt-4o-mini

embedding_dims: 1536
```

### Development Config

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o-mini, gpt-4o]

router:
  default: openai:gpt-4o-mini
  think: openai:gpt-4o
  fast: openai:gpt-4o-mini

agent:
  autonomous:
    enabled_by_default: true
    max_iterations: 5
  loop:
    max_iterations: 10

observability:
  verbosity: detailed
  langfuse:
    enabled: true
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
```

See [Common Patterns](common-patterns.md) for more examples.
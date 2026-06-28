# Provider Setup Guide

Complete guide for configuring LLM providers, vector stores, and persistence backends.

## Overview

Soothe supports multiple provider types:

- **LLM Providers**: OpenAI, Anthropic, OpenAI-compatible APIs, Ollama
- **Embedding Providers**: OpenAI, DashScope, custom embedding models
- **Vector Stores**: SQLite Vec, PostgreSQL pgvector, Weaviate, in-memory
- **Persistence**: SQLite, PostgreSQL

## LLM Provider Configuration

### Provider Types

| Type | Description | Compatibility |
|------|-------------|---------------|
| `openai` | Standard OpenAI API | Full tool calling, JSON mode, streaming |
| `limited_openai` | OpenAI-compatible APIs with limitations | Limited tool_choice, structured output in reasoning_content |
| `anthropic` | Anthropic Claude API | Native Claude tool calling |
| `ollama` | Ollama local inference | Basic tool calling support |

### OpenAI Provider

**Full OpenAI API compatibility**:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    api_base_url: null  # Optional: custom endpoint
    models:
      - gpt-4o          # Latest GPT-4 with vision
      - gpt-4o-mini     # Fast, cheap GPT-4
      - o3-mini         # Reasoning model
```

**Environment**:

```bash
export OPENAI_API_KEY=sk-proj-your-key-here
```

**Features supported**:
- Full tool calling with `tool_choice` (object, string values)
- JSON schema response format
- Streaming
- Vision capabilities
- Function calling

### OpenAI-Compatible Providers (Limited)

**For APIs that mimic OpenAI but have limitations** (LMStudio, MLXServer, certain GLM deployments):

```yaml
providers:
  - name: lmstudio
    provider_type: limited_openai
    api_base_url: http://localhost:1234/v1
    api_key: lmstudio  # Dummy key
    models:
      - google/gemma-4-26b-a4b
      - meta-llama-3.1-8b-instruct
```

**Limitations handled**:
- Accept json_schema response_format but return empty content
- Return structured JSON in reasoning_content field (thinking tokens)
- Limited tool_choice support (string values only: "none", "auto", "required")
- No object-level tool_choice

**Common compatible APIs**:
- LMStudio (`http://localhost:1234/v1`)
- MLXServer
- vLLM endpoints
- Certain GLM/Qwen deployments with OpenAI compatibility

### DashScope (Alibaba Cloud)

**DashScope with OpenAI compatibility**:

```yaml
providers:
  - name: dashscope
    provider_type: openai
    api_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ${DASHSCOPE_API_KEY}
    models:
      - qwen-max           # Strong reasoning
      - qwen3.7-plus       # Fast model
      - qwen3.6-plus       # Balanced, coding-optimized
      - MiniMax-M2.5       # Alternative
      - kimi-k2.5          # Moonshot
```

**Environment**:

```bash
export DASHSCOPE_API_KEY=sk-your-dashscope-key
```

**DashScope API keys**: Get from https://dashscope.console.aliyun.com/

### Anthropic Provider

**Anthropic Claude API**:

```yaml
providers:
  - name: anthropic
    provider_type: anthropic
    api_key: ${ANTHROPIC_API_KEY}
    models:
      - claude-sonnet-4-20250514  # Claude 4 Sonnet
      - claude-3-5-sonnet-20241022  # Claude 3.5 Sonnet
      - claude-3-opus-20240229    # Claude 3 Opus
```

**Environment**:

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

**Anthropic API keys**: Get from https://console.anthropic.com/

### Ollama Local Models

**Ollama for local inference**:

```yaml
providers:
  - name: ollama
    provider_type: ollama
    api_base_url: http://localhost:11434  # Default Ollama port
    models:
      - llama3.1:8b
      - mistral:7b
      - codellama:7b
      - gemma2:9b
```

**Setup**:

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama server
ollama serve

# Pull models
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama pull codellama:7b
```

**Ollama models**: Browse at https://ollama.com/models

### OpenRouter

**OpenRouter for multiple providers**:

```yaml
providers:
  - name: openrouter
    provider_type: openai
    api_base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    models:
      - openai/gpt-4o
      - anthropic/claude-3.5-sonnet
      - google/gemini-pro-1.5
      - meta-llama/llama-3.1-405b-instruct
```

**Environment**:

```bash
export OPENROUTER_API_KEY=sk-or-your-key
```

**OpenRouter**: Get API key from https://openrouter.ai/

### vLLM Server

**Self-hosted vLLM inference server**:

```yaml
providers:
  - name: vllm
    provider_type: openai
    api_base_url: http://your-vllm-server:8000/v1
    api_key: dummy  # vLLM doesn't require auth by default
    models:
      - your-model-name
```

**Setup vLLM**:

```bash
pip install vllm

# Start server
vllm serve your-model-name --host 0.0.0.0 --port 8000
```

## Model Router Configuration

### Role-Based Routing

Soothe uses purpose-based roles to select models:

```yaml
router:
  default: "provider:model"     # Main orchestrator
  think: "provider:model"       # Complex reasoning
  fast: "provider:model"        # Quick operations
  image: "provider:model"       # Vision tasks
  embedding: "provider:model"   # Vector embeddings
```

**Role purposes**:

| Role | Usage | Typical Model |
|------|-------|---------------|
| `default` | CoreAgent, orchestrator reasoning | gpt-4o-mini |
| `think` | Planning, consensus, backoff reasoning | o3-mini, claude-sonnet |
| `fast` | Classification, routing, subagents | gpt-4o-mini, qwen3.7-plus |
| `image` | Vision, image analysis | gpt-4o, gemini-pro-vision |
| `embedding` | Vector search, semantic memory | text-embedding-3-small |

### Router Examples

**Single provider**:

```yaml
router:
  default: openai:gpt-4o-mini
  think: openai:o3-mini
  fast: openai:gpt-4o-mini
  image: openai:gpt-4o
  embedding: openai:text-embedding-3-small
```

**Multi-provider**:

```yaml
router:
  default: openai:gpt-4o-mini
  think: anthropic:claude-sonnet-4-20250514
  fast: dashscope:qwen3.7-plus
  image: openai:gpt-4o
  embedding: dashscope:multimodal-embedding-v1
```

**Local + cloud hybrid**:

```yaml
router:
  default: ollama:llama3.1:8b
  fast: lmstudio:gemma-2-9b
  think: openai:o3-mini        # Complex tasks → cloud
  image: openai:gpt-4o         # Vision → cloud
```

### Fallback Behavior

Unset roles fall back to `default`:

```yaml
router:
  default: openai:gpt-4o-mini
  think: null   # Falls back to default
  fast: null    # Falls back to default
```

## Embedding Configuration

### OpenAI Embeddings

```yaml
router:
  embedding: openai:text-embedding-3-small

embedding_dims: 1536  # text-embedding-3-small
# or
embedding_dims: 3072  # text-embedding-3-large
```

**OpenAI embedding models**:

| Model | Dimensions | Cost |
|-------|------------|------|
| `text-embedding-3-small` | 1536 | Cheapest |
| `text-embedding-3-large` | 3072 | Higher quality |
| `text-embedding-ada-002` | 1536 | Legacy |

### DashScope Embeddings

```yaml
router:
  embedding: dashscope:multimodal-embedding-v1

embedding_dims: 1024  # DashScope default
```

### Local Embeddings (Ollama)

```yaml
router:
  embedding: ollama:nomic-embed-text

embedding_dims: 768  # nomic-embed-text
```

**Setup**:

```bash
ollama pull nomic-embed-text
```

## Vector Store Configuration

### SQLite Vec (Default)

**Lightweight embedded vector storage**:

```yaml
vector_stores:
  - name: sqlite_vec_default
    provider_type: sqlite_vec

vector_store_router:
  default: sqlite_vec_default:soothe_default

embedding_dims: 1536
```

**Features**:
- No external dependencies
- File-based storage (portable)
- Suitable for development and small deployments
- Auto-creates database files under `~/.soothe/data/`

### PostgreSQL pgvector

**Production vector storage**:

```yaml
vector_stores:
  - name: pgvector_main
    provider_type: pgvector
    dsn: ${POSTGRES_VECTOR_DSN}
    pool_size: 10
    index_type: hnsw  # hnsw | ivfflat | none

vector_store_router:
  default: pgvector_main:soothe_production

embedding_dims: 1536
```

**Environment**:

```bash
export POSTGRES_VECTOR_DSN=postgresql://user:pass@db-host:5432/vectors
```

**PostgreSQL setup**:

```sql
-- Enable pgvector extension
CREATE EXTENSION vector;

-- Create database
CREATE DATABASE soothe_vectors;
```

**Index types**:

| Type | Description | When to Use |
|------|-------------|-------------|
| `hnsw` | Hierarchical navigable small world | Production, fast queries |
| `ivfflat` | Inverted file flat | Large datasets, batch queries |
| `none` | No index | Development, small data |

### Weaviate

**Managed Weaviate service**:

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

**Weaviate Cloud**: https://weaviate.io/

### In-Memory (Testing)

**Transient in-memory vector store**:

```yaml
vector_stores:
  - name: in_memory_test
    provider_type: in_memory

vector_store_router:
  default: in_memory_test:test_collection
```

**Use case**: Testing, ephemeral sessions, no persistence needed.

## Persistence Configuration

### SQLite Persistence (Default)

**File-based persistence**:

```yaml
persistence:
  default_backend: sqlite
  metadata_sqlite_path: ~/.soothe/data/metadata.db
  checkpoint_sqlite_path: ~/.soothe/data/soothe_checkpoints.db
```

**Default paths**:
- Metadata: `~/.soothe/data/metadata.db`
- Checkpoints: `~/.soothe/data/soothe_checkpoints.db`

**Features**:
- No external dependencies
- Portable file storage
- Suitable for development and small deployments

### PostgreSQL Persistence

**Production persistence** (RFC-802 multi-database):

```yaml
persistence:
  default_backend: postgresql
  postgres_base_dsn: ${POSTGRES_DSN}
  postgres_databases:
    checkpoints: soothe_checkpoints
    metadata: soothe_metadata
    vectors: soothe_vectors
    memory: soothe_memory
  
  postgres_pool_min_size: 8
  checkpointer_pool_size: 32
  sloop_pool_size: 32
  postgres_pool_max_idle_seconds: 120
  postgres_pool_max_lifetime_seconds: 1800
```

**Environment**:

```bash
export POSTGRES_DSN=postgresql://user:pass@db-host:5432
```

**PostgreSQL setup**:

```sql
-- Create databases
CREATE DATABASE soothe_checkpoints;
CREATE DATABASE soothe_metadata;
CREATE DATABASE soothe_vectors;
CREATE DATABASE soothe_memory;

-- Enable pgvector (for vectors database)
\c soothe_vectors
CREATE EXTENSION vector;
```

**Pool sizing**:

| Field | Default | Description |
|-------|---------|-------------|
| `postgres_pool_min_size` | 4 | Min connections per pool |
| `checkpointer_pool_size` | 24 | LangGraph checkpoint pool |
| `sloop_pool_size` | 24 | StrangeLoop pool |
| `postgres_pool_max_idle_seconds` | 120 | Idle connection timeout |
| `postgres_pool_max_lifetime_seconds` | 1800 | Connection lifetime |

## Provider-Specific Considerations

### Rate Limits

Configure rate limits for provider APIs:

```yaml
agent:
  loop:
    llm_rate_limit:
      rpm_limit: 120           # Requests per minute
      concurrent_limit: 10     # Concurrent requests
```

**Provider-specific limits**:

| Provider | Default RPM Limit | Concurrent Limit |
|----------|------------------|------------------|
| OpenAI | 500 (tier-dependent) | 10-100 |
| Anthropic | 60 | 5-10 |
| DashScope | 60 | 5 |
| Local (Ollama) | Unlimited | Hardware-dependent |

### Timeout Configuration

```yaml
agent:
  loop:
    llm_rate_limit:
      call_timeout_seconds: 600
      call_timeout_max_seconds: 900
      retry_on_timeout: true
      max_timeout_retries: 10
      timeout_retry_multiplier: 1.2
```

**Timeout fields**:

| Field | Default | Description |
|-------|---------|-------------|
| `call_timeout_seconds` | 600 | Base timeout per call |
| `call_timeout_max_seconds` | 900 | Timeout ceiling for retries |
| `retry_on_timeout` | true | Retry with timeout escalation |
| `max_timeout_retries` | 10 | Max retry attempts after timeout |

### Cost Optimization

**Use cheaper models for simple tasks**:

```yaml
router:
  default: openai:gpt-4o-mini     # Cheap for orchestrator
  think: openai:o3-mini           # Strong reasoning when needed
  fast: openai:gpt-4o-mini        # Fast classification
```

**Or use local models**:

```yaml
router:
  default: ollama:llama3.1:8b     # Free local model
  think: openai:o3-mini           # Pay for complex reasoning
```

## Environment Variable Best Practices

### Secret Management

**Don't hardcode API keys in config files**:

```yaml
# ✅ Good: Use environment variable interpolation
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}

# ❌ Bad: Hardcoded key (security risk)
providers:
  - name: openai
    api_key: sk-xxx
```

### Shell Profile Setup

Add to `~/.bashrc` or `~/.zshrc`:

```bash
# Provider keys
export OPENAI_API_KEY=sk-xxx
export ANTHROPIC_API_KEY=sk-ant-xxx
export DASHSCOPE_API_KEY=your-key

# Optional tools
export TAVILY_API_KEY=tvly-xxx
export DEEPXIV_API_KEY=your-key

# Config file location
export SOOTHE_CONFIG_FILE=~/.soothe/config/config.yml
```

### Docker Secrets

Use Docker secrets or environment files:

```yaml
# docker-compose.yml
services:
  soothe:
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    secrets:
      - openai_api_key

secrets:
  openai_api_key:
    file: ./secrets/openai_api_key.txt
```

### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: soothe-provider-keys
type: Opaque
stringData:
  openai-api-key: sk-xxx
  anthropic-api-key: sk-ant-xxx
```

## Testing Provider Configuration

### Verify Provider Setup

```bash
# Test provider connection
soothe --debug "test prompt"

# Check resolved config
soothed doctor

# View model resolution
export SOOTHE_DEBUG=true
soothe "simple test" | grep -i model
```

### Test Specific Model

```bash
# Test with specific model via CLI override
soothe --model openai:gpt-4o "test prompt"

# Test embedding model
soothe "embed this text" --debug
# Check logs for embedding model usage
```

### Validate Configuration

```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('config.yml'))"

# Validate Soothe config
python -c "from soothe.config import SootheConfig; cfg = SootheConfig.from_yaml_file('config.yml'); print(cfg)"
```

## Troubleshooting

### Provider Not Found

**Error**: `Provider 'xxx' not found`

**Solution**: Ensure provider name matches router configuration:

```yaml
providers:
  - name: openai  # This name
    api_key: ${OPENAI_API_KEY}

router:
  default: openai:gpt-4o-mini  # Must match provider name
```

### API Key Invalid

**Error**: `Invalid API key`

**Solution**:

1. Check environment variable is set: `echo $OPENAI_API_KEY`
2. Verify key format matches provider requirements
3. Test key with provider's API directly

### Rate Limit Exceeded

**Error**: `Rate limit exceeded`

**Solution**: Reduce `rpm_limit` or `concurrent_limit`:

```yaml
agent:
  loop:
    llm_rate_limit:
      rpm_limit: 60            # Lower RPM
      concurrent_limit: 5      # Lower concurrency
```

### Timeout Errors

**Error**: `Timeout waiting for LLM response`

**Solution**: Increase timeout:

```yaml
agent:
  loop:
    llm_rate_limit:
      call_timeout_seconds: 300  # Increase timeout
      call_timeout_max_seconds: 600
```

### Model Not Available

**Error**: `Model 'xxx' not available from provider 'yyy'`

**Solution**:

1. Check model name spelling
2. Verify model is supported by provider
3. Ensure model is listed in `providers[].models`

---

**See also:**

- [YAML Reference](yaml-reference.md) - Complete field documentation
- [Environment Variables](environment-variables.md) - Env var reference
- [Common Patterns](common-patterns.md) - Real-world configuration examples
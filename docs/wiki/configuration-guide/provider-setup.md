---
title: "Provider Setup"
parent: Configuration Guide
grand_parent: Wiki
nav_order: 4
description: Choosing and configuring LLM providers, embedding models, vector stores, and persistence backends.
---

# Provider Setup

Choosing and configuring LLM providers, embedding models, vector stores, and persistence backends — with the decision criteria the schema alone won't tell you.

## Provider Selection Criteria

Soothe supports three `provider_type` values. The choice is driven by **API compatibility**, not brand:

| `provider_type` | When to use | Key limitation |
|-----------------|-------------|----------------|
| `openai` | OpenAI itself, or any OpenAI-compatible endpoint (OpenRouter, vLLM, local oMLX/LMStudio) | None for official OpenAI; local endpoints auto-receive compatibility wrappers (see below) |
| `anthropic` | Anthropic Claude API | Native Claude tool calling |
| `ollama` | Local Ollama inference | Basic tool calling; depends on model support |

**Custom `api_base_url` on `openai` providers.** When the URL is not `https://api.openai.com`, Soothe automatically applies compatibility wrappers for local servers (oMLX, LMStudio, vLLM) that return structured JSON in `reasoning_content` or only accept string `tool_choice` values. Use `provider_type: openai` plus your local `api_base_url` — no separate provider type is required.

**OpenAI-compatible cloud providers** (Qwen, OpenRouter) all use `provider_type: openai` plus a custom `api_base_url` and an interpolated `api_key`:

```yaml
providers:
  - name: openai-custom
    provider_type: openai
    api_base_url: https://your-provider-endpoint/v1
    api_key: ${OPENAI_API_KEY}
    models: [qwen-max]
```

Self-hosted vLLM is identical — just point `api_base_url` at your server and set a dummy `api_key`.

## Model Routing: Roles, Not Models

Soothe never asks for a model by name at runtime. It asks for a **role**, and the router maps roles to `provider:model` pairs. This indirection is the whole point: swap models without touching agent code.

```yaml
router_profiles:
  - name: default
    router:
      default: openai:gpt-4o-mini
      think: openai:o3-mini
active_router_profile: default
embedding_profile:
  - model_role: openai:text-embedding-3-small
    embedding_dims: 1536
```

Chat/image roles live under `router_profiles[].router` (`default`, `think`, `fast`, `image`, `ocr`), while embedding is configured once in `embedding_profile`.

The five roles and their typical cost/quality profile:

| Role | Used for | Cheap model OK? |
|------|----------|-----------------|
| `default` | CoreAgent reasoning, failure analysis | Yes — it runs most often |
| `fast` | Classification, subagents, memory | Yes — latency-sensitive |
| `think` | Planning, consensus validation | No — quality matters |
| `image` | Vision tasks | Must be vision-capable |
| `embedding_profile.model_role` | Vector search, semantic memory | Must match `embedding_profile.embedding_dims` |

**Fallback rule:** unset chat/image/ocr roles inherit `default`. So you can start with only `default` configured and add `think`/`image` as needed. But beware: if `default` is your most expensive model, leaving `fast` unset makes every cheap operation expensive.

**Cost strategy:** set `default` and `fast` to a cheap model, reserve `think` for a strong one. The local+cloud hybrid pushes this further — local model for `default`/`fast`, cloud only for `think`/`image` (e.g. `default: ollama:llama3.1:8b`, `think: openai:o3-mini`).

## Embeddings

`embedding_profile.model_role` and `embedding_profile.embedding_dims` are coupled — the dimension *must* match the model's output vector size or inserts fail silently or noisily.

| Model | Dimensions |
|-------|------------|
| OpenAI `text-embedding-3-small` | 1536 |
| OpenAI `text-embedding-3-large` | 3072 |
| Qwen `text-embedding-v3` | 1024 |
| Ollama `nomic-embed-text` | 768 |

**Mistake to avoid:** changing `embedding_profile.model_role` without updating `embedding_profile.embedding_dims` (or vice versa) corrupts the vector store — existing vectors have the old dimensionality and queries fail. When migrating, drop and re-index the collection.

## Vector Stores

| Backend | When | Notes |
|---------|------|-------|
| `sqlite_vec` (default) | Dev, single-user, <100k vectors | Zero deps, file-based under `~/.soothe/data/` |
| `pgvector` | Production, shared with Postgres persistence | `hnsw` for speed, `ivfflat` for huge static sets |
| `weaviate` | Managed vector DB decoupled from Postgres | Cloud or self-hosted |
| `in_memory` | Tests, ephemeral sessions | Lost on restart |

The router format is `provider_name:collection_name`. Unset roles fall back to `default` — same pattern as the model router. If you use pgvector, Soothe can auto-resolve the vectors database from `persistence.postgres_base_dsn` (RFC-802) when no explicit `dsn` is set.

## Persistence Backends

| Backend | When | Concurrency |
|---------|------|-------------|
| `sqlite` (default) | Dev, testing, single-process | WAL mode helps, but writers still serialize |
| `postgresql` | Production, parallel autonomous goals, multi-worker | Pool-based, handles concurrent writers |

**RFC-802 multi-database architecture:** when `postgres_base_dsn` is set, Soothe splits state across four databases (checkpoints, metadata, vectors, memory) for lifecycle isolation and backup granularity. Define them in the `postgres_databases` map. If `postgres_base_dsn` is unset, it falls back to a single `soothe_postgres_dsn` database. The multi-database layout is strongly recommended for production — it lets you back up/restore components independently.

**Pool sizing (from source docstrings):**
- `postgres_pool_min_size` (default 4): warm connections kept ready.
- `checkpointer_pool_size` (default 24): LangGraph checkpoint pool. In thread-pool mode it's a daemon-level singleton shared across threads; in worker-pool mode each worker gets its own (so `workers × pool_size` total connections — lower it).
- `sloop_pool_size` (default 24): StrangeLoop pool, same sharing semantics.

Rule of thumb: for thread-pool mode keep defaults; for worker-pool mode divide by your worker count to avoid exhausting Postgres `max_connections`.

## Rate Limits & Timeouts

Provider APIs have their own limits; Soothe's `agent.loop.llm_rate_limit` keeps you under them with retry/backoff. Set `rpm_limit` and `concurrent_limit` on that block; `retry_on_timeout` and `retry_on_rate_limit` default to `true`.

| Provider | Typical RPM | Concurrency |
|----------|-------------|-------------|
| OpenAI | 500 (tier 2+) | 10–100 |
| Anthropic | 60 | 5–10 |
| OpenAI-compatible | Varies | Varies |
| Ollama (local) | Unlimited | GPU-bound |

Set `rpm_limit` *below* your tier's ceiling. On 429, Soothe retries with exponential backoff (base 2s, max 60s) and respects `Retry-After` headers. On timeout, it escalates the timeout by `timeout_retry_multiplier` (1.2×) up to `call_timeout_max_seconds`. These defaults (600s base, 10 retries) are tuned for robust step execution — lower them only if you're confident your provider is fast.

## Secret Management

**Always interpolate, never hardcode.** Use `api_key: ${OPENAI_API_KEY}` — a literal key (`sk-proj-xxx`) leaks into version control and is the single most common security mistake. For Docker, use `secrets:` in compose or env files. For Kubernetes, mount `Secret` resources as env vars. See [Environment Variables](environment-variables.md) for the full interpolation guide.

## Verifying Your Setup

Run `soothed doctor` to validate config and connectivity, `soothe --debug "test"` to print the resolved config and model routing, and `soothe --model openai:gpt-4o "test"` to override a role for one run. Validate YAML syntax before debugging Soothe: `python -c "import yaml; yaml.safe_load(open('config.yml'))"`.

## Troubleshooting Guide

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Provider 'xxx' not found` | Provider `name` in `providers[]` doesn't match the router's prefix | Ensure `router.default: <name>:<model>` uses the exact `name` |
| `Invalid API key` | Env var unset or wrong format | `echo $OPENAI_API_KEY`; verify key prefix matches provider |
| `Rate limit exceeded` | `rpm_limit` above provider tier, or too much concurrency | Lower `rpm_limit` and `concurrent_limit` |
| `Timeout waiting for LLM response` | Provider slow or down | Raise `call_timeout_seconds`; check provider status |
| `Model 'xxx' not available` | Model not listed in `providers[].models` or misspelled | Add it to the `models` list; check provider's model catalog |
| Empty tool calls on local server | Missing `api_base_url` or wrapper not applied | Ensure `provider_type: openai` with explicit local `api_base_url`; restart daemon after config change |
| Vector insert errors | `embedding_profile.embedding_dims` ≠ model output | Align the two; re-index existing collections |

## See Also

- [YAML Reference](yaml-reference.md) — full field schema
- [Environment Variables](environment-variables.md) — `${VAR}` interpolation and `SOOTHE_*` mapping
- [Common Patterns](common-patterns.md) — multi-provider and hybrid routing recipes
- Source: `packages/soothe/src/soothe/config/models.py` (`ModelProviderConfig`, `PersistenceConfig`, `VectorStoreProviderConfig`)

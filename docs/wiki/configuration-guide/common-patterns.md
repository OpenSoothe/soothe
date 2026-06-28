# Common Configuration Patterns

Real-world Soothe recipes — and the reasoning behind each one. Use these as starting points, not gospel; the goal is to understand *why* a config looks the way it does so you can adapt it.

## How to Think About Config

Soothe config has three axes you tune independently:

- **Capability** — which providers, tools, and subagents are available.
- **Behavior** — how the agent loops, when it stops, how it parallelizes.
- **Environment** — where state lives (SQLite vs Postgres), where logs go, how secrets enter.

Most patterns below change only one axis. The minimal config changes *capability* (add a provider) and relies on defaults for the other two. Production configs change all three deliberately.

## Minimal to Development

The jump from "it runs" to "it's pleasant to develop with" is small: add a second model for reasoning, bump verbosity, and bound the loop so a runaway agent doesn't burn tokens.

```yaml
router:
  default: openai:gpt-4o-mini
  think: openai:gpt-4o        # reasoning tasks use the bigger model

agent:
  loop:
    max_iterations: 10        # hard stop during dev

observability:
  verbosity: debug
  console:
    enabled: true
```

`debug: true` at the top level enables LangGraph debug tracing — useful when a loop behaves unexpectedly, noisy otherwise.

## Production Mindset

Production configs differ from dev configs in three ways: state becomes durable (Postgres), cost is bounded (rate limits, cheaper default model), and observability is structured (Langfuse, not console). The essential moves: set `persistence.default_backend: postgresql` with a `postgres_base_dsn`; add `agent.loop.llm_rate_limit.rpm_limit` / `concurrent_limit`; and switch observability from `console` to `langfuse` with `${LANGFUSE_*}` keys.

**Decision points:** Use Postgres when you need thread durability across restarts or multiple workers — SQLite locks under concurrent writers (WAL mode helps but doesn't eliminate it). Set `rpm_limit` below your provider's tier ceiling; Soothe retries on 429 with exponential backoff, but staying under the limit avoids the latency hit.

## Multi-Provider & Hybrid Routing

The router's role-based design exists precisely so you can mix providers without rewriting agent logic. Define an `ollama` provider (local) and an `openai` provider (cloud), then route `default` to the local model and `think`/`image` to cloud models.

**Routing logic:** unset roles fall back to `default`. So a hybrid config can set only `default` (local) and `think` (cloud) — everything else reuses the local model. This is cheaper than it looks: classification, routing, and memory extraction use the `fast` role, which inherits `default`, so they all run locally.

**Gotcha:** `provider_type: openai` with a custom `api_base_url` works for any OpenAI-compatible API (DashScope, OpenRouter, vLLM). Use `limited_openai` only when the endpoint mishandles `tool_choice` or returns structured output in `reasoning_content` — LMStudio and some GLM deployments need it.

## Tool Scoping by Use Case

The `tools` section is where you shape *what the agent can do*. Disabling tools is a security and cost measure, not just a preference.

| Use case | Disable | Enable |
|----------|---------|--------|
| Research agent | `execution`, `file_ops` | `wizsearch`, `deepxiv` |
| Code assistant | `wizsearch`, `http_requests` | `execution`, `file_ops`, `explore` subagent |
| Safe assistant | `execution`, `http_requests` | `file_ops` (with path policy) |

Each tool group is a block with an `enabled: bool`; set the ones you want off to `false` and configure the ones you keep (e.g. `wizsearch.default_engines: [tavily, duckduckgo]`).

**Why disable rather than restrict:** a disabled tool never enters the model's tool array, so the model never wastes tokens considering it. Path policies (see [Security](security-config.md)) are a *second* layer for tools you keep enabled.

## Autonomous Mode Tradeoffs

Autonomous mode turns Soothe into a 24/7 goal-runner. The knobs are all ceilings — they exist to prevent runaway cost and infinite loops, not to enable features. Set `enabled: true`, then bound `max_iterations` (per goal), `max_parallel_goals`, and `max_loops` (loop pool size). Enable `dreaming_enabled` for long-running agents that should consolidate memory when idle; leave it off for short-lived ones. Raise `protocols.durability.thread_inactivity_timeout_hours` (e.g. 168 for a week) so threads survive between runs.

**Key decisions:**
- `max_parallel_goals` × `max_iterations` ≈ your worst-case concurrent LLM load. Size `checkpointer_pool_size` accordingly.
- `dreaming_enabled` runs memory consolidation when goals complete — useful for long-running agents, pure overhead for short-lived ones.
- Autonomous mode *requires* durable persistence (Postgres). SQLite will bottleneck under parallel goals.

For a "controlled" variant, lower every ceiling and disable dreaming/scheduling — this gives you autonomous *capability* with manual *cadence*.

## Vector Stores by Scale

For pgvector, define a `pgvector` provider with a `dsn` and `index_type: hnsw`, then route via `vector_store_router.default: <name>:<collection>`. See [Provider Setup](provider-setup.md) for the snippet.

**Selection guide:**
- **SQLite Vec (default):** zero deps, fine for single-user dev and <100k vectors.
- **pgvector:** production. Use `hnsw` for low-latency queries, `ivfflat` for very large static datasets, `none` only during development.
- **Weaviate Cloud:** when you want managed vector storage decoupled from your Postgres.
- **in_memory:** tests and ephemeral sessions only — data is lost on restart.

`embedding_dims` **must** match your embedding model's output (1536 for `text-embedding-3-small`, 3072 for `-large`, 1024 for DashScope). A mismatch causes silent corruption or errors at insert time.

## Subagent Model Assignment

Subagents inherit the `fast` router role by default. Override per-subagent when a role needs different strength:

```yaml
subagents:
  explore:
    model: openai:gpt-4o-mini
  tacitus:
    model: anthropic:claude-sonnet-4-20250514
    config:
      effort: thorough
```

**Rule of thumb:** `explore` wants speed (cheap model, medium thoroughness); `tacitus` wants quality (strong model, thorough effort); `plan` wants reasoning (use the `think` role). Disabling all three puts you in single-agent mode — simpler but no parallelism or specialized planning.

## MCP Servers

A stdio MCP server entry needs a `name`, `command`, `args`, and (for servers needing auth) an `env` map with `${VAR}`-interpolated tokens. Set `defer: true` (the default) on every entry unless you have a specific reason to eagerly load tools.

`defer` keeps MCP tools out of the model's default tool array — they're loaded on demand. This matters because a server exposing 50 tools would otherwise consume context budget on every turn. Use `tool_filter` (glob allowlist) to further trim noisy servers. See [YAML Reference](yaml-reference.md) for the field list.

## Logging Levels

| Setting | When to use |
|---------|-------------|
| `verbosity: debug` + `debug: true` | Tracing a misbehaving loop |
| `verbosity: normal` | Everyday use |
| `verbosity: quiet` | Production / headless automation |
| `thread_logging_enabled: true` | Multi-thread debugging (off in prod to save disk) |

Rotate logs with `log_file_max_bytes` / `log_file_backup_count`; defaults (5 MB, 3 backups) are reasonable for dev, increase retention for production auditing.

## Testing Configs

For unit tests, use a mock provider (`provider_type: openai`, `api_key: mock-key`), route to `mock:gpt-4o-mini`, and point SQLite checkpoints at a `/tmp` path. No network, no real keys.

For integration tests, point at a real provider but cap `global_max_llm_calls` to bound cost, and set `langfuse.environment: testing` to keep traces out of production dashboards.

## Common Mistakes

- **Mismatched `embedding_dims`** — the most common silent failure. Verify against your embedding model's spec.
- **Forgetting `think`/`fast`** — leaving them null makes *everything* use `default`, which is often the most expensive model.
- **SQLite under parallel autonomous goals** — works for one goal, deadlocks under concurrency. Switch to Postgres.
- **Hardcoding keys in YAML** — use `${VAR}`. See [Environment Variables](environment-variables.md).
- **Setting `rpm_limit` above provider tier** — you'll hit 429s; Soothe retries, but latency compounds.

## See Also

- [YAML Reference](yaml-reference.md) — condensed schema
- [Environment Variables](environment-variables.md) — interpolation and `SOOTHE_*` mapping
- [Provider Setup](provider-setup.md) — provider selection and routing detail

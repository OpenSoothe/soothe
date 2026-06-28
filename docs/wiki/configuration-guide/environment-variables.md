# Environment Variables

How Soothe consumes environment variables — the two distinct mechanisms, their gotchas, and how to manage secrets safely.

## Two Mechanisms, Not One

Soothe reads the environment in two completely separate ways, and confusing them is the most common config mistake:

1. **`SOOTHE_*` field mapping** — Pydantic's `BaseSettings` with `env_prefix="SOOTHE_"` maps env vars directly onto config fields. This is for *overrides*: set `SOOTHE_ROUTER_DEFAULT` and it replaces `router.default` from your YAML.

2. **`${VAR}` interpolation** — before Pydantic ever sees the YAML, a recursive pass (`_expand_env_in_config` in `config/env.py`) replaces every `${VAR}` token in every string field with the env var's value. This is for *secrets*: write `api_key: ${OPENAI_API_KEY}` in YAML and the key never touches the file.

The difference matters because they fail differently: a `SOOTHE_*` override silently uses the YAML default if the var is unset; an unresolved `${VAR}` is left as the literal string `${OPENAI_API_KEY}` and usually fails Pydantic validation or warns at runtime.

## `SOOTHE_*` Field Mapping

Every field on `SootheConfig` and its nested models can be set via env var. The rule is mechanical:

> Take the YAML path, replace dots/colons with underscores, uppercase, prepend `SOOTHE_`.

| YAML path | Env var |
|-----------|---------|
| `debug` | `SOOTHE_DEBUG` |
| `router.default` | `SOOTHE_ROUTER_DEFAULT` |
| `agent.loop.max_iterations` | `SOOTHE_AGENT_LOOP_MAX_ITERATIONS` |
| `observability.langfuse.enabled` | `SOOTHE_OBSERVABILITY_LANGFUSE_ENABLED` |

```bash
export SOOTHE_DEBUG=true
export SOOTHE_ROUTER_DEFAULT=openai:gpt-4o
export SOOTHE_AGENT_LOOP_MAX_ITERATIONS=10
```

**Gotchas:**
- List/dict fields need JSON encoding: `SOOTHE_TOOLS_WIZSEARCH_DEFAULT_ENGINES='["tavily","duckduckgo"]'`.
- The prefix is exactly `SOOTHE_` — `SOOTHED_*` or `Soothe_*` won't match.
- Nested model fields use the full path; `SOOTHE_AUTONOMOUS_ENABLED` does nothing — it must be `SOOTHE_AGENT_AUTONOMOUS_ENABLED`.

## `${VAR}` Interpolation

Write the placeholder in YAML; Soothe resolves it at load time:

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
persistence:
  postgres_base_dsn: ${POSTGRES_DSN}
```

The resolver (`_resolve_env`) walks dicts, lists, and strings recursively. Key behaviors drawn from the source:

- **Works anywhere in a string:** `${HOME}/workspaces` and `${VAR1}/${VAR2}` both resolve.
- **Unresolved vars are left as-is:** `${MISSING}` stays the literal string. For provider fields specifically, an unresolved `${...}` triggers a warning and the provider is skipped (`_resolve_provider_env` returns `None`).
- **Only `\$\{WORD\}` matches:** the regex is `\$\{(\w+)\}` — word characters only, no nested expansion, no `$VAR` POSIX form.
- **Scalars pass through:** ints, bools, and `None` are never interpolated, so `embedding_dims: 1536` is safe.

**Quoting:** all three forms work because YAML quotes are delimiters, not part of the value:
```yaml
api_key: ${OPENAI_API_KEY}      # fine
api_key: "${OPENAI_API_KEY}"    # fine
api_key: '${OPENAI_API_KEY}'    # fine
```

## Provider & Tool Keys (No Prefix)

These are *not* `SOOTHE_*` vars — they're consumed by `${VAR}` interpolation in YAML or passed through to the LangChain ecosystem directly:

| Variable | Used for |
|----------|----------|
| `OPENAI_API_KEY` | OpenAI provider `api_key` |
| `ANTHROPIC_API_KEY` | Anthropic provider `api_key` |
| `DASHSCOPE_API_KEY` | DashScope (OpenAI-compatible) |
| `OPENROUTER_API_KEY` | OpenRouter |
| `TAVILY_API_KEY`, `SERPER_API_KEY`, `JINA_API_KEY` | Web search engines |
| `DEEPXIV_API_KEY`, `DEEPXIV_TOKEN` | Academic search |
| `GITHUB_TOKEN`, `GITHUB_MCP_TOKEN`, `LINEAR_MCP_TOKEN` | MCP server auth |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Tracing |
| `POSTGRES_DSN`, `POSTGRES_VECTOR_DSN`, `WEAVIATE_URL`, `WEAVIATE_API_KEY` | Storage backends |

Set these in your shell profile or secret manager; reference them via `${...}` in YAML.

## Path & Runtime Vars

| Variable | Purpose |
|----------|---------|
| `SOOTHE_HOME` | Base directory (default `~/.soothe`). Logs, data, and agent runtime dirs live under here. |
| `SOOTHE_CONFIG_FILE` | Override config file path (searched after `--config`, before user dir). |

## Priority & Override Chains

Resolution order, highest to lowest:

1. **CLI args** (`--config`, `--debug`, `--model`)
2. **`SOOTHE_*` env vars**
3. **YAML file** (with `${VAR}` already interpolated)
4. **Pydantic model defaults**

```bash
# YAML says router.default = openai:gpt-4o-mini
# Env overrides it:
export SOOTHE_ROUTER_DEFAULT=openai:gpt-4o
# CLI wins over both:
soothe --model openai:o3-mini "prompt"
```

## Per-Environment Setup

A practical split: keep *structure* in YAML files, keep *secrets and per-env values* in env vars.

**Development** (`~/.zshrc`):
```bash
export SOOTHE_DEBUG=true
export SOOTHE_OBSERVABILITY_VERBOSITY=debug
export SOOTHE_CONFIG_FILE=~/.soothe/config.dev.yml
export OPENAI_API_KEY=sk-dev-xxx
```

**Production / CI:** set `SOOTHE_PERSISTENCE_DEFAULT_BACKEND=postgresql`, the Postgres DSN, provider keys, and Langfuse keys via your secret manager (Vault, AWS Secrets Manager, Kubernetes Secrets). Keep `SOOTHE_DEBUG` unset.

**Testing:** force SQLite and disable tracing to keep tests hermetic:
```bash
export SOOTHE_PERSISTENCE_DEFAULT_BACKEND=sqlite
export SOOTHE_OBSERVABILITY_LANGFUSE_ENABLED=false
export SOOTHE_AGENT_LOOP_MAX_ITERATIONS=5
```

## Docker & Kubernetes

In Docker Compose, pass vars through from the host `.env` file:
```yaml
services:
  soothe:
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SOOTHE_PERSISTENCE_DEFAULT_BACKEND=postgresql
      - SOOTHE_PERSISTENCE_POSTGRES_BASE_DSN=postgresql://postgres:postgres@db:5432
```

For Kubernetes, use `Secret` resources mounted as env vars — never put keys in `ConfigMap` or image layers. Verify inside a running container with `docker exec soothe env | grep SOOTHE`.

## Secret Hygiene

- **Never commit `${VAR}`-resolved values.** The point of interpolation is that the YAML is safe to commit; the secret stays in the environment.
- **Don't hardcode keys as fallbacks.** `api_key: ${OPENAI_API_KEY} # sk-xxx` in a comment still leaks the key in version control.
- **Rotate via the environment, not the config.** Because interpolation happens at load time, updating the env var and restarting picks up the new key — no config edit needed.
- **Check what's actually set:** `env | grep SOOTHE`, `env | grep OPENAI`, `echo $SOOTHE_CONFIG_FILE`.

## Troubleshooting

**Variable not applied?** Check, in order: (1) it starts with `SOOTHE_` (unless it's a provider key); (2) the path matches the YAML nesting exactly; (3) no CLI arg is overriding it; (4) your shell actually exported it — `source ~/.zshrc` or `exec bash` after editing.

**`${VAR}` not resolved?** `echo $VAR` in the *same shell* that runs Soothe. Remember unresolved placeholders stay literal — if you see `${OPENAI_API_KEY}` in a debug log, the env var was unset at load time, not a syntax error.

**Debug the resolved config:**
```bash
soothe --debug "test"     # prints resolved config on startup
soothed doctor            # validates config and connectivity
```

## See Also

- [YAML Reference](yaml-reference.md) — field schema
- [Common Patterns](common-patterns.md) — recipes using these vars
- [Provider Setup](provider-setup.md) — provider-specific key guidance
- Source: `packages/soothe/src/soothe/config/env.py` for the interpolation implementation

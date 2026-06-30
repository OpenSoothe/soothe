# Config Zero-Bootstrap & Slim Template

**Status:** Draft  
**Date:** 2026-06-30  
**Scope:** Env-first provider bootstrap + code defaults for vector stores; slim `config.template.yml` to Tier A/B only.

---

## Problem

`config/config.template.yml` is ~580 lines. Most keys duplicate Pydantic defaults already enforced by `test_config_template_matches_pydantic_defaults`. New users copy the full file and believe they must configure internal tuning (`agent.loop.*`, `optimization.*`, pool sizes, security deny lists, etc.).

The desired experience:

```bash
export OPENAI_API_KEY=sk-...
soothe          # no --config, no ~/.soothe/config/config.yml required
```

Today, bare `SootheConfig()` loads but `providers: []` — LLM calls fail until YAML is copied.

---

## Goals

1. **Zero-config happy path** for standard OpenAI (and optionally Anthropic) when env vars are set.
2. **Slim template** (~40–60 lines): providers/router examples + Tier B mode switches + pointer to `models.py`.
3. **No behavior change** for existing YAML configs (explicit config wins over auto-bootstrap).
4. **Single source of truth** remains Pydantic models in `packages/soothe/src/soothe/config/models.py`.

## Non-Goals

- Auto-detecting arbitrary OpenAI-compatible endpoints (DashScope, LMStudio, etc.) — those stay explicit YAML.
- Generating template from Pydantic at build time (future enhancement).
- Changing daemon config (`daemon.yml`) in this pass.

---

## Design

### 1. Config tiers (unchanged taxonomy)

| Tier | User-facing? | Examples |
|------|--------------|----------|
| **A — Must configure** | Yes (or env bootstrap) | providers, router_profiles |
| **B — Mode / deployment** | Yes, when non-default | `agent.autonomous.enabled`, `persistence.default_backend`, `tools.*.enabled` |
| **C — Internal tuning** | No — code only | `agent.loop.*`, `optimization.*`, `progressive_*`, pool sizes |

Tier C stays in Pydantic defaults only. Template removes all Tier C blocks.

### 2. Env-first provider bootstrap

Add a `@model_validator(mode="after")` on `SootheConfig` — `_bootstrap_providers_from_env` — that runs **after** YAML/env parsing, **only when** `providers` is empty.

**Bootstrap rules (conservative, ordered):**

| Priority | Env var(s) | Synthetic provider | Router implication |
|----------|------------|--------------------|--------------------|
| 1 | `OPENAI_API_KEY` (non-empty) | `{name: openai, provider_type: openai, api_key: <value>}` | Existing `default_router_profiles()` already maps `openai:gpt-4o-mini` |
| 2 | `ANTHROPIC_API_KEY` | `{name: anthropic, provider_type: anthropic, api_key: <value>}` | If no OpenAI, extend default profile router to `anthropic:claude-sonnet-4-20250514` (or keep gpt-4o-mini string and fail fast at runtime — **prefer updating default profile when only Anthropic is present**) |
| 3 | None | Leave `providers: []` | Unchanged; clear startup message elsewhere |

**Optional env overrides (no YAML):**

| Env var | Effect |
|---------|--------|
| `OPENAI_API_KEY` | Bootstrap OpenAI provider |
| `OPENAI_BASE_URL` | Set on bootstrapped OpenAI provider's `api_base_url` |
| `ANTHROPIC_API_KEY` | Bootstrap Anthropic provider |
| `SOOTHE_ACTIVE_ROUTER_PROFILE` | Already supported |

**Precedence (highest wins):**

```
Explicit YAML providers  >  env-bootstrapped providers  >  empty (no LLM)
```

If YAML lists `providers: []` explicitly vs omits the key — both are empty list; bootstrap applies. If YAML lists any provider (even with unresolved `${VAR}`), **do not bootstrap** — preserve current warning/skip behavior.

**Logging:** One INFO line when bootstrap activates: `"No providers in config; using OPENAI_API_KEY from environment."` No secrets in logs.

### 3. Default vector stores in code

Mirror `default_router_profiles()`:

```python
def default_vector_stores() -> list[VectorStoreProviderConfig]:
    return [VectorStoreProviderConfig(name="sqlite_vec_default", provider_type="sqlite_vec")]

def default_vector_store_router() -> VectorStoreRouter:
    return VectorStoreRouter(default="sqlite_vec_default:soothe_default")
```

Wire into `SootheConfig`:

```python
vector_stores: list[VectorStoreProviderConfig] = Field(default_factory=default_vector_stores)
vector_store_router: VectorStoreRouter = Field(default_factory=default_vector_store_router)
```

Bare `SootheConfig()` then resolves vector roles without YAML — matches dev wiki claim of "SQLite Vec zero deps."

Production pgvector configs continue to override via YAML.

### 4. Slim `config.template.yml`

Target structure (~50 lines):

```yaml
# Soothe — minimal config template
# Defaults: packages/soothe/src/soothe/config/models.py
# Zero-config: export OPENAI_API_KEY=... and run (no file required)

providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o, gpt-4o-mini]

router_profiles:
  - name: default
    router:
      default: openai:gpt-4o-mini
    embedding_dims: 1536

active_router_profile: default

# --- Optional overrides (uncomment as needed) ---
# agent:
#   autonomous:
#     enabled: true
# tools:
#   deepxiv:
#     enabled: true
# persistence:
#   default_backend: postgresql
#   postgres_base_dsn: ${DATABASE_URL}
# observability:
#   langfuse:
#     enabled: true
#     public_key: ${LANGFUSE_PUBLIC_KEY}
```

**Removed from template:** all Tier C sections, full subagent blocks, security lists, loop tuning, optimization, progressive_*, filesystem_middleware, vector_stores (now code default), misplaced `agent.cron` (bug fix — cron is top-level `cron:` in schema).

**Commented examples** stay inline for multi-provider, MCP, plugins — as YAML comments only, not active keys.

### 5. `config/develop/config.yml`

Unchanged philosophy: only overrides from Pydantic defaults. After slim template, develop config remains the team’s local profile (DashScope + local-omlx). Sync rule: if template structure changes, ensure develop still validates.

### 6. Documentation updates

| File | Change |
|------|--------|
| `README.md` | Getting Started: env-only path first; `cp config.template.yml` optional |
| `docs/wiki/configuration-guide/yaml-reference.md` | Document zero-config bootstrap + tier model |
| `docs/wiki/configuration-guide/common-patterns.md` | Minimal section references env-only path |

### 7. Tests

| Test | Purpose |
|------|---------|
| `test_bootstrap_openai_provider_from_env` | Empty config + `OPENAI_API_KEY` → one provider, router resolves |
| `test_bootstrap_skipped_when_yaml_providers_present` | YAML provider blocks env bootstrap |
| `test_default_vector_store_without_yaml` | Bare `SootheConfig()` has sqlite_vec router |
| Update `test_config_template_matches_pydantic_defaults` | Remove vector_stores/router from normalize pop list (they match code defaults now) |
| `test_config_template_matches_pydantic_defaults` | Template still loads and matches except provider example |

---

## Error handling

- **No providers, no env keys:** Keep current behavior — fail at first LLM call with actionable message suggesting `export OPENAI_API_KEY` or `--config`.
- **Bootstrap + wrong router model string:** Same as today — model resolution error names missing provider.
- **Anthropic-only bootstrap:** Default router profile must use anthropic model string when OpenAI key absent (small addition to `default_router_profiles()` or post-bootstrap profile patch).

---

## Migration / compatibility

- Existing full YAML configs: **no change** — bootstrap only when `providers` empty.
- Users who copied old 580-line template: still valid; no migration required.
- `test_config_template_matches_pydantic_defaults` becomes stricter alignment test (template ≈ defaults + provider comment block).

---

## Implementation order

1. `default_vector_stores()` + router factory (low risk, isolated)
2. `_bootstrap_providers_from_env` validator + tests
3. Slim template + sync `config/develop/config.yml` structure comment
4. README + wiki docs
5. Run `./scripts/verify_finally.sh`

---

## Open questions (deferred)

- Bootstrap `TAVILY_API_KEY` for wizsearch? **No** — search keys are tool-level, not provider bootstrap.
- Support `SOOTHE_CONFIG` pointing to missing file vs empty file? Treat missing as `{}` if we add that path later.
- Generate annotated reference from Pydantic JSON schema? Future RFC.

---

## Success criteria

- [ ] `OPENAI_API_KEY=... soothe` works with no config file
- [ ] `config.template.yml` < 80 lines
- [ ] All existing config unit tests pass
- [ ] `develop/config.yml` unchanged in behavior

---
title: Configuration Guide
parent: Wiki
has_children: true
nav_order: 5
description: >-
  YAML reference, environment variables, providers, and common patterns.
permalink: /wiki/configuration-guide/
canonical: configuration-guide/index.md
---

# Configuration Guide

How to configure Soothe — YAML settings, environment variables, and the design decisions behind them.

## Configuration Philosophy

Soothe is built around **progressive disclosure**: a minimal config is enough to run, and advanced knobs only appear when you need them. Three layers stack on top of sane Pydantic-model defaults:

1. **YAML file** — the source of truth for structured, version-controllable config.
2. **Environment variables** — secrets and per-deployment overrides. Two distinct mechanisms: `SOOTHE_*` vars map onto config fields, while `${VAR}` interpolation injects secrets *into* the YAML.
3. **CLI arguments** — one-off runtime overrides (highest priority).

**Priority (highest wins):** CLI args > `SOOTHE_*` env vars > YAML file > built-in defaults.

This layering means you should keep *structure* in YAML and *secrets/ephemeral values* in the environment. Never hardcode API keys in config files — use `${VAR}` interpolation (see [Environment Variables](environment-variables.md)).

## File Discovery Order

Soothe resolves the active config file by searching in this order:

1. `--config PATH` — explicit CLI flag
2. `SOOTHE_CONFIG_FILE` — environment variable
3. `~/.soothe/config/config.yml` — user directory
4. `config/develop/config.yml` — repository development default
5. Built-in `SootheConfig` Pydantic defaults

The first match wins. This lets CI pin a config via env var while letting local dev fall back to the user directory.

## Minimal Working Config

**Zero-config (no file):**

```bash
export OPENAI_API_KEY=sk-...
soothed start && soothe "Analyze this codebase"
```

**Minimal YAML** (multi-model routing or non-env secrets):

```yaml
providers:
  - name: openai
    api_key: ${OPENAI_API_KEY}
    models: [gpt-4o-mini]

router_profiles:
  - name: default
    router:
      default: openai:gpt-4o-mini
    embedding_dims: 1536

active_router_profile: default
```

Top-level `router:` was removed — use `router_profiles` + `active_router_profile`. Env-only model changes: `SOOTHE_ROUTER_PROFILES` (JSON) or `SOOTHE_ACTIVE_ROUTER_PROFILE`; see [Environment Variables](environment-variables.md).

A template with every option documented ships at `config/config.template.yml` — copy it rather than writing from scratch.

## Documentation Map

| Article | What you'll learn |
|---------|-------------------|
| [Common Patterns](common-patterns.md) | Real-world recipes and the reasoning behind each one |
| [Environment Variables](environment-variables.md) | `SOOTHE_*` mapping, `${VAR}` interpolation gotchas, secret hygiene |
| [Provider Setup](provider-setup.md) | Choosing LLM/embedding providers, model routing, persistence & vector stores |
| [YAML Reference](yaml-reference.md) | Condensed schema quick-reference (full schema lives in source) |
| [Autonomous Mode](../autonomous-mode.md) | 24/7 self-running agent tuning |
| [Daemon Setup](../daemon-management.md) | Multi-transport server configuration |
| [Security](../deployment/security.md) | Sandboxing, path policies, approval flows |

## Method Comparison

| Method | Best for | Mutability |
|--------|----------|------------|
| YAML file | Complete, version-controlled config | Low |
| Env vars | Secrets, CI/CD, per-host overrides | Medium |
| CLI args | One-off overrides, testing | High |

## Where the Schema Lives

The full, authoritative schema is defined in Pydantic models — not in these docs. When in doubt about a field's type, default, or constraints, read the source:

- `packages/soothe/src/soothe/config/models.py` — all nested config models (`ModelProviderConfig`, `AgentConfig`, `PersistenceConfig`, `SecurityConfig`, etc.)
- `packages/soothe/src/soothe/config/settings.py` — top-level `SootheConfig` (env prefix, YAML loading, model validators)
- `packages/soothe/src/soothe/config/env.py` — `${VAR}` interpolation implementation

These wiki articles capture *knowledge* — design intent, decision guides, and pitfalls — that the source alone doesn't surface. Treat them as a companion to, not a replacement for, the schema.

## Next Steps

- **New here:** start with [Common Patterns](common-patterns.md) for copy-paste recipes.
- **Picking a provider:** read [Provider Setup](provider-setup.md).
- **Need a specific field:** jump to [YAML Reference](yaml-reference.md).
- **Managing secrets:** see [Environment Variables](environment-variables.md).
- **Quick reference:** the legacy [Configuration (Quick Reference)](../configuration.md) page retains a minimal config snippet.

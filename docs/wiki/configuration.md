---
title: Configuration (Quick Reference)
parent: Wiki
nav_order: 21
description: >-
  Minimal config snippet. For the full reference, see the Configuration Guide.
permalink: /wiki/configuration/
canonical: configuration-guide/index.md
---

# Configuration — Quick Reference

> **Full reference:** **[Configuration Guide](configuration-guide/index.md)**
> (YAML schema, environment variables, provider setup, common patterns).

## Minimal `nano.yml`

```yaml
# ~/.soothe/config/nano.yml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"

router:
  default: "openai:gpt-4o-mini"
  fast: "openai:gpt-4o-mini"
  think: "openai:o3"

workspace:
  root: "."

persistence:
  default_backend: sqlite  # or postgresql
```

## Next Steps

- **[YAML Reference](configuration-guide/yaml-reference.md)** — Every config key
- **[Environment Variables](configuration-guide/environment-variables.md)** — `SOOTHE_*` vars
- **[Provider Setup](configuration-guide/provider-setup.md)** — LLM providers, vector stores
- **[Common Patterns](configuration-guide/common-patterns.md)** — Real-world examples

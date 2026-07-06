---
title: "Configuration (Quick Reference)"
parent: Wiki
nav_order: 4.1
description: >-
  Quick configuration overview — this page has been consolidated into the Configuration Guide for the complete reference.
---

# Configuration Guide

> **This page has been consolidated.** For the complete, up-to-date configuration reference, see the **[Configuration Guide](configuration-guide/index.md)**.

The configuration system has been reorganized into a dedicated guide with detailed sub-pages:

- **[Configuration Guide README](configuration-guide/index.md)** — Overview, quick start, and file locations
- **[YAML Reference](configuration-guide/yaml-reference.md)** — Complete YAML schema with all options
- **[Environment Variables](configuration-guide/environment-variables.md)** — All `SOOTHE_*` environment variables
- **[Common Patterns](configuration-guide/common-patterns.md)** — Real-world configuration examples
- **[Provider Setup](configuration-guide/provider-setup.md)** — LLM providers, vector stores, and persistence backends

## Quick Reference

**Default config path**: `~/.soothe/config/config.yml`

**Minimal configuration**:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o-mini

router_profiles:
  - name: default
    router:
      default: openai:gpt-4o-mini
active_router_profile: default
```

**Priority**: Command-line args (`--config`) > Environment variables (`SOOTHE_*`) > YAML file > Built-in defaults

See the [full configuration guide](configuration-guide/index.md) for complete details.

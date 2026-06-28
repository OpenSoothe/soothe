# Configuration Guide

Complete configuration reference for Soothe - YAML settings, environment variables, and common patterns.

## Overview

Soothe uses a **layered configuration system** with three methods:

1. **Environment Variables** - Quick setup, ideal for secrets and overrides
2. **YAML Configuration File** - Full control, structured settings
3. **Command-Line Arguments** - Runtime overrides

**Priority**: Command-line args > Environment variables > YAML file > Defaults

## Quick Start

### Minimal Configuration

Create `~/.soothe/config/config.yml`:

```yaml
providers:
  - name: openai
    provider_type: openai
    api_key: ${OPENAI_API_KEY}
    models:
      - gpt-4o-mini

router:
  default: openai:gpt-4o-mini
```

Set your API key:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

Run Soothe:

```bash
soothe "Analyze this codebase"
```

### Using the Template

Start from the complete template:

```bash
cp config/config.template.yml ~/.soothe/config/config.yml
# Edit the file, set your API keys
soothe --config ~/.soothe/config/config.yml
```

## Documentation Sections

### Core References
- **[YAML Reference](yaml-reference.md)** - Complete YAML schema with all options
- **[Environment Variables](environment-variables.md)** - SOOTHE_* variables reference

### Configuration Patterns
- **[Common Patterns](common-patterns.md)** - Real-world configuration examples
- **[Provider Setup](provider-setup.md)** - LLM providers, vector stores, persistence

### Feature-Specific
- **[Autonomous Mode](autonomous-config.md)** - 24/7 self-running agent configuration
- **[Daemon Setup](daemon-config.md)** - Multi-transport server configuration
- **[Security](security-config.md)** - Sandboxing, path restrictions, approval flows

## Configuration File Locations

Soothe looks for configuration in this order:

1. `--config PATH` - Explicit command-line path
2. `SOOTHE_CONFIG_FILE` - Environment variable path
3. `~/.soothe/config/config.yml` - User directory
4. `config/develop/config.yml` - Repository default (development)
5. Built-in defaults (from `SootheConfig` Pydantic model)

## Configuration Methods Comparison

| Method | Best For | Priority |
|--------|----------|----------|
| YAML File | Complete configuration, version control | Low |
| Environment Variables | Secrets, CI/CD, quick overrides | Medium |
| CLI Arguments | One-off overrides, testing | High |

## Next Steps

- **New users**: Start with [Common Patterns](common-patterns.md)
- **Setting up providers**: See [Provider Setup](provider-setup.md)
- **Full schema reference**: Use [YAML Reference](yaml-reference.md)
- **Environment variables**: Check [Environment Variables](environment-variables.md)
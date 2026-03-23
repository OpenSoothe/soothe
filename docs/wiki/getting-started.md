# Getting Started with Soothe

Get up and running with Soothe in minutes using the default configuration.

## Quick Start

The fastest way to start using Soothe:

```bash
# 1. Install Soothe
pip install soothe

# 2. Initialize default configuration
soothe config init

# 3. Set your API key
export OPENAI_API_KEY=sk-your-key-here

# 4. Launch Soothe
soothe
```

That's it! Soothe is now ready to use with sensible defaults.

## What `soothe config init` Does

The initialization command creates:

```
~/.soothe/                    # SOOTHE_HOME (default location)
├── config/
│   └── config.yml            # Default configuration file
├── runs/                     # Thread execution data
├── generated_agents/         # Weaver-generated agents
└── logs/                     # Daemon and thread logs
```

The default `config.yml` includes:
- OpenAI provider configuration
- Model routing (gpt-4o-mini for general tasks)
- All built-in subagents enabled
- Recommended settings for most use cases

## Configuration Setup

### View Your Configuration

Check your current configuration:

```bash
# Summary view
soothe config show

# Detailed JSON view
soothe config show --format json

# Include sensitive values (API keys)
soothe config show --show-sensitive
```

### Edit Configuration

Edit the default configuration:

```bash
# Open in your editor
vim ~/.soothe/config/config.yml

# Or use your preferred editor
code ~/.soothe/config/config.yml
```

### Minimal Custom Configuration

If you prefer to create a custom config from scratch:

```yaml
# ~/.soothe/config/config.yml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"

router:
  default: "openai:gpt-4o-mini"
```

### Recommended Configuration

For a more complete setup, add these sections:

```yaml
# ~/.soothe/config/config.yml
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models:
      - gpt-4o-mini
      - gpt-4o
      - o3-mini

# Model routing by purpose
router:
  default: "openai:gpt-4o-mini"     # General tasks
  think: "openai:o3-mini"            # Complex reasoning
  fast: "openai:gpt-4o-mini"         # Quick tasks
  embedding: "openai:text-embedding-3-small"

# Agent behavior
workspace_dir: "."
progress_verbosity: normal

# Subagents
subagents:
  browser:
    enabled: true
  claude:
    enabled: false
```

## Configuration Locations

Soothe looks for configuration files in this order:

1. `--config <file>` (CLI argument)
2. `~/.soothe/config/config.yml` (default location, created by `soothe config init`)
3. `./soothe.yml` (current directory, if default doesn't exist)
4. Built-in defaults (if no config file found)

**Recommended**: Use the default `~/.soothe/config/config.yml` for consistency.

## Environment Variables

Store sensitive information in environment variables:

```bash
# API keys
export OPENAI_API_KEY=sk-your-key-here
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# Optional: Override SOOTHE_HOME
export SOOTHE_HOME=/custom/path

# Optional: Soothe settings
export SOOTHE_DEBUG=false
export SOOTHE_PROGRESS_VERBOSITY=normal
```

Add these to your `~/.bashrc` or `~/.zshrc` for persistence.

### Using .env Files

For project-specific settings, create a `.env` file:

```bash
# .env file in your project directory
OPENAI_API_KEY=sk-your-key-here
SOOTHE_PROGRESS_VERBOSITY=detailed
```

## First Run

### Interactive TUI Mode

Launch the interactive terminal interface:

```bash
# Uses ~/.soothe/config/config.yml automatically
soothe
```

The TUI provides:
- Real-time progress visualization
- Task decomposition and planning
- Subagent activity tracking
- Slash commands for quick actions

Just type your request and press Enter.

### Headless Mode

Run a single prompt and exit:

```bash
soothe "Analyze the codebase structure"
```

Perfect for:
- Quick one-off queries
- Scripts and automation
- CI/CD pipelines
- Background jobs

### Resume Previous Session

Continue from where you left off:

```bash
# List threads
soothe thread list

# Resume specific thread
soothe thread continue abc123
```

## Optional Extras

Install additional capabilities as needed:

```bash
# Browser automation
pip install soothe[browser]

# Claude agent
pip install soothe[claude]

# Vector stores
pip install soothe[pgvector]

# Local models with Ollama
pip install soothe[ollama]

# Everything
pip install soothe[all]
```

## Verify Installation

Check that everything is working:

```bash
# Validate configuration
soothe config validate

# Show configuration summary
soothe config show

# Test with a simple query
soothe "What is 2 + 2?"
```

## Configuration Management

### Reinitialize Configuration

Reset to defaults (with backup):

```bash
# Backup existing config
cp ~/.soothe/config/config.yml ~/.soothe/config/config.yml.backup

# Reinitialize
soothe config init --force
```

### Validate Configuration

Check for configuration errors:

```bash
# Validate default config
soothe config validate

# Validate custom config
soothe config validate --config custom.yml
```

## Next Steps

- [CLI Reference](cli-reference.md) - Learn all available commands
- [TUI Guide](tui-guide.md) - Master the terminal interface
- [Configuration Guide](configuration.md) - Advanced configuration options
- [Subagents Guide](subagents.md) - Enable specialized agents

## Getting Help

- Use `/help` in the TUI for available commands
- Check the [Troubleshooting Guide](troubleshooting.md) for common issues
- Review logs at `~/.soothe/logs/daemon.log`
- Browse the [documentation](../) for detailed guides
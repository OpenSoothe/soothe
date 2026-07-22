---
title: "Installation"
parent: Getting Started
grand_parent: Wiki
nav_order: 1
description: >-
  Complete installation guide for Soothe, covering system requirements, installation methods, and troubleshooting.
---

# Installation

Complete installation guide for Soothe.

---

## System Requirements

### Prerequisites

- **Python**: 3.11 or higher
- **Operating System**: macOS, Linux, Windows (WSL2)
- **API Keys**: OpenAI API key (required) or other LLM provider keys

### Verify Python Version

```bash
python --version
# Should show Python 3.11.x or higher
```

---

## Installation Methods

### Option 1: Full Installation (Recommended)

Install the complete Soothe stack for everyday use:

```bash
pip install -U soothe soothe-cli soothe-daemon
```

This includes:
- **soothe**: Core runtime with data tools (CSV/Excel/PDF/DOCX), research, browser-use, and PostgreSQL drivers
- **soothe-cli**: Interactive TUI and command-line interface
- **soothe-daemon**: Background daemon (WebSocket)

### Option 2: Minimal Installation

Install the core framework and CLI only:

```bash
pip install -U soothe soothe-cli
```

The base `soothe` package includes all built-in tool dependencies (tabular data, document parsing, web research, browser subagent, PostgreSQL).

### Option 3: Using uv (Fast Alternative)

If you use [uv](https://docs.astral.sh/uv/):

```bash
uv pip install soothe soothe-cli soothe-daemon
```

### Option 4: From Source

For development or latest changes:

```bash
# Clone repository
git clone https://github.com/mirasoth/soothe.git
cd soothe

# Install with development dependencies
pip install -e '.[dev]' soothe-cli soothe-daemon

# Or use the provided script
make install-dev
```

---

## Package Overview

Soothe is organized as a monorepo with multiple packages:

| Package | PyPI Name | Purpose | Required? |
|---------|-----------|---------|------------|
| **soothe** | `soothe` | Core agent runtime, protocols, backends, tools | Yes |
| **soothe-cli** | `soothe-cli` | `soothe` command (TUI, one-shot prompts) | Recommended |
| **soothe-daemon** | `soothe-daemon` | `soothed` command (background daemon) | Optional |
| **soothe-sdk** | `soothe-sdk` | Shared protocol types, decorators | Auto-installed |
| **soothe-plugins** | `soothe-plugins` | Community plugins | Optional |

### Built-in Capabilities

The `soothe` package includes research (Tavily, Arxiv, Wizsearch), data tools
(CSV/Excel/Parquet, PDF/DOCX), browser-use, PostgreSQL drivers, and OpenAI-compatible
provider support out of the box.

**GitHub integration** uses the `gh` CLI (builtin skill) or the GitHub MCP server
(`mcp_builtins: [github]` with Node.js/npx) — not a Python extra.

**Langfuse tracing** is optional: `pip install langfuse` or install soothe from
source with dev dependencies (`pip install -e '.[dev]'`).

---

## API Key Setup

### OpenAI (Required)

```bash
# Set in shell
export OPENAI_API_KEY=sk-your-key-here

# Add to ~/.bashrc or ~/.zshrc for persistence
echo 'export OPENAI_API_KEY=sk-your-key-here' >> ~/.bashrc
```

### Other Providers (Optional)

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# Google Gemini
export GOOGLE_API_KEY=your-google-api-key

# OpenAI-Compatible Providers (e.g., Qwen, OpenRouter, local vLLM)
export OPENAI_API_KEY=your-openai-compatible-key
export OPENAI_BASE_URL=https://your-provider-endpoint/v1  # Optional

# Web search (Tavily)
export TAVILY_API_KEY=tvly-your-key
```

---

## Configuration Setup

### Auto-Created Directory Structure

Starting the daemon (`soothed start`) automatically creates the `~/.soothe/` directory tree on first run. No manual initialization is needed.

This creates:
```
~/.soothe/                    # SOOTHE_HOME (default location)
├── config/
│   ├── nano.yml              # Nano-owned agent configuration
│   └── daemon.yml            # Default daemon configuration
├── runs/                     # Thread execution data
└── logs/                     # Daemon and thread logs
```

### Verify Installation

```bash
# Check version
soothe --version

# Verify configuration exists
ls ~/.soothe/config/nano.yml

# Test with simple query
soothe -p "Hello, are you working?"
```

---

## Verify Installation

### Quick Health Check

```bash
# Run diagnostic tests
soothed doctor
```

This checks:
- ✅ Configuration validity
- ✅ API key accessibility
- ✅ Required packages
- ✅ Protocol backends
- ✅ Daemon connectivity (if running)

### Manual Verification

```bash
# 1. Verify packages are installed
python -c "import soothe; print(f'Soothe {soothe.__version__}')"
python -c "import soothe_cli; print('CLI installed')"
python -c "import soothe_daemon; print('Daemon installed')"

# 2. Test basic functionality
soothe -p "What is 2 + 2?"

# 3. Start daemon (optional)
soothed start
soothed doctor
```

---

## Platform-Specific Notes

### macOS

No special requirements. Works out of the box.

### Linux

Install system dependencies for optional features:

```bash
# Ubuntu/Debian
sudo apt-get install -y python3-dev build-essential

# Fedora
sudo dnf install -y python3-devel gcc
```

### Windows

Use **Windows Subsystem for Linux 2 (WSL2)**:

```powershell
# Install WSL2
wsl --install

# Then follow Linux instructions inside WSL2
```

---

## Troubleshooting

### Installation Issues

**Problem**: `pip install` fails with compilation errors

**Solution**: Install build dependencies:
```bash
# macOS
xcode-select --install

# Ubuntu/Debian
sudo apt-get install -y python3-dev build-essential

# Then retry installation
pip install -U soothe soothe-cli soothe-daemon
```

**Problem**: `ModuleNotFoundError: No module named 'soothe'`

**Solution**: Ensure you're using the correct Python environment:
```bash
# Check which Python
which python
which pip

# Use python -m pip for clarity
python -m pip install -U soothe soothe-cli soothe-daemon
```

**Problem**: Version conflicts with existing packages

**Solution**: Use a virtual environment:
```bash
python -m venv soothe-env
source soothe-env/bin/activate  # On Windows: soothe-env\Scripts\activate
pip install -U soothe soothe-cli soothe-daemon
```

### Configuration Issues

**Problem**: `Config file not found`

**Solution**: The daemon auto-creates a default configuration on first start. Simply launch `soothed` and it will bootstrap `~/.soothe/config/nano.yml` automatically:
```bash
soothed  # Auto-creates config on first run
```

**Problem**: `OPENAI_API_KEY not set`

**Solution**: Set the environment variable:
```bash
export OPENAI_API_KEY=sk-your-key-here
# Or add to nano.yml:
# providers:
#   - name: openai
#     api_key: "sk-your-key-here"
```

### Runtime Issues

**Problem**: `soothe: command not found`

**Solution**: Ensure `soothe-cli` is installed and `pip` bin directory is in PATH:
```bash
pip install -U soothe-cli
echo $PATH  # Should include ~/.local/bin or similar
```

**Problem**: Permission errors on `~/.soothe`

**Solution**: Fix permissions:
```bash
chmod -R u+rw ~/.soothe
```

---

## Next Steps

After successful installation:

1. **[Quick-Start Guide](Quick-Start.md)** - Run your first autonomous session
2. **[Configuration Guide](../configuration.md)** - Customize for your needs
3. **[Basic Concepts](Basic-Concepts.md)** - Understand Soothe's architecture

---

## Upgrading

### Update to Latest Version

```bash
pip install -U soothe soothe-cli soothe-daemon
```

### Check Version

```bash
soothe --version
```

### Migration Notes

Check the [CHANGELOG](https://github.com/mirasoth/soothe/releases) for breaking changes between versions.

---

## Uninstalling

```bash
# Remove all packages
pip uninstall soothe soothe-cli soothe-daemon soothe-sdk

# Remove configuration (optional)
rm -rf ~/.soothe
```
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
pip install -U 'soothe[all]' soothe-cli soothe-daemon
```

This includes:
- **soothe[all]**: Core runtime, all tool groups, research capabilities
- **soothe-cli**: Interactive TUI and command-line interface
- **soothe-daemon**: Background daemon (WebSocket, HTTP REST)

### Option 2: Core Installation

Install the core framework only:

```bash
pip install -U soothe soothe-cli
```

Add optional capability groups as needed:

```bash
# Research tools (web search, academic papers)
pip install -U 'soothe[research]'

# Document processing (PDF, DOCX, etc.)
pip install -U 'soothe[document]'

# GitHub integration
pip install -U 'soothe[github]'

# Multiple groups
pip install -U 'soothe[research,document,github]'
```

### Option 3: Using uv (Fast Alternative)

If you use [uv](https://docs.astral.sh/uv/):

```bash
uv pip install 'soothe[all]' soothe-cli soothe-daemon
```

### Option 4: From Source

For development or latest changes:

```bash
# Clone repository
git clone https://github.com/mirasoth/soothe.git
cd soothe

# Install with development dependencies
pip install -e '.[all,dev]' soothe-cli soothe-daemon

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

### Capability Groups

The `soothe[all]` extra includes all capability groups:

| Group | Tools Included |
|-------|----------------|
| `research` | Web search, academic papers (arXiv, DeepXiv), research synthesis |
| `document` | PDF, DOCX, TXT, Markdown processing |
| `tabular` | CSV, Excel, Parquet, data analysis |
| `github` | GitHub API integration |
| `langfuse` | LLM tracing and observability |
| `dashscope` | Alibaba Cloud LLM models |
| `semantic` | Embedding models for vector search |
| `claude` | Anthropic Claude models and agent SDK |

Install specific groups:

```bash
pip install -U 'soothe[research,document]'
```

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

# Alibaba DashScope
export DASHSCOPE_API_KEY=your-dashscope-key

# Web search (Tavily)
export TAVILY_API_KEY=tvly-your-key
```

---

## Configuration Setup

### Initialize Default Configuration

```bash
soothe config init
```

This creates:
```
~/.soothe/                    # SOOTHE_HOME (default location)
├── config/
│   └── config.yml            # Default configuration
├── runs/                     # Thread execution data
├── generated_agents/         # Weaver-generated agents
└── logs/                     # Daemon and thread logs
```

### Verify Installation

```bash
# Check version
soothe --version

# Verify configuration
soothe config show

# Test with simple query
soothe -p "Hello, are you working?"
```

---

## Verify Installation

### Quick Health Check

```bash
# Run diagnostic tests
soothe doctor
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
soothe doctor
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
pip install -U 'soothe[all]' soothe-cli soothe-daemon
```

**Problem**: `ModuleNotFoundError: No module named 'soothe'`

**Solution**: Ensure you're using the correct Python environment:
```bash
# Check which Python
which python
which pip

# Use python -m pip for clarity
python -m pip install -U 'soothe[all]' soothe-cli soothe-daemon
```

**Problem**: Version conflicts with existing packages

**Solution**: Use a virtual environment:
```bash
python -m venv soothe-env
source soothe-env/bin/activate  # On Windows: soothe-env\Scripts\activate
pip install -U 'soothe[all]' soothe-cli soothe-daemon
```

### Configuration Issues

**Problem**: `Config file not found`

**Solution**: Initialize configuration:
```bash
soothe config init
```

**Problem**: `OPENAI_API_KEY not set`

**Solution**: Set the environment variable:
```bash
export OPENAI_API_KEY=sk-your-key-here
# Or add to config.yml:
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
pip install -U 'soothe[all]' soothe-cli soothe-daemon
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
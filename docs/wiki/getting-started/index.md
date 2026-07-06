---
title: Getting Started
nav_order: 1
description: >-
  Installation, quick start, and basic concepts for new Soothe users.
permalink: /wiki/getting-started/
---

# Getting Started with Soothe

Welcome to Soothe! This section guides you from installation to your first autonomous agent session.

---

## 📋 Learning Path

Follow these guides in order:

### 1. [Installation](Installation.md)
- System requirements
- Installation methods (pip, uv, from source)
- Package overview
- Troubleshooting installation issues

### 2. [Quick-Start Guide](Quick-Start.md)
- Your first Soothe session
- Basic usage patterns
- Common workflows
- Next steps

### 3. [Basic Concepts](Basic-Concepts.md)
- Core architecture
- Goals and threads
- Subagents and tools
- Memory and context

---

## 🚀 30-Second Quick Start

If you just want to try Soothe right now:

```bash
# Install
pip install -U 'soothe[all]' soothe-cli soothe-daemon

# Set API key
export OPENAI_API_KEY=sk-your-key-here

# Run your first query
soothe -p "List all Python files in the current directory and count lines of code"
```

For detailed setup, continue with the guides above.

---

## 📚 Additional Resources

- **[Configuration Guide](../configuration.md)** - Customize Soothe for your needs
- **[CLI Reference](../cli-reference.md)** - Complete command documentation
- **[TUI Guide](../tui-guide.md)** - Terminal UI usage
- **[Troubleshooting](../troubleshooting.md)** - Solve common issues

---

## 🆘 Getting Help

- **Documentation**: Browse the [wiki](../index.md)
- **Issues**: Check [troubleshooting](../troubleshooting.md) first
- **Architecture**: See [architecture overview](../architecture/index.md)
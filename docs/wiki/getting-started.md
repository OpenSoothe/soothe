---
title: "Getting Started (Legacy)"
parent: Wiki
nav_order: 1
description: Legacy getting started page that redirects to the comprehensive Getting Started section.
---

# Getting Started

> **New Documentation Structure**: This page now redirects to our comprehensive Getting Started section.

---

## 📚 Getting Started Guides

For the complete getting started experience, visit:

### **[Getting Started Hub](getting-started/index.md)** 🚀

The hub provides:

- **[Installation Guide](getting-started/Installation.md)** - Complete installation instructions
- **[Quick-Start Guide](getting-started/Quick-Start.md)** - Your first session and common workflows
- **[Basic Concepts](getting-started/Basic-Concepts.md)** - Core architecture and concepts

---

## ⚡ Quick Start (30 Seconds)

If you just want to try Soothe right now:

```bash
# Install
pip install -U 'soothe[all]' soothe-cli soothe-daemon

# Set API key
export OPENAI_API_KEY=sk-your-key-here

# Start the daemon (auto-creates ~/.soothe/ directory structure)
soothed start

# Run your first query
soothe -p "List all Python files in the current directory and count lines of code"
```

---

## 📖 What's in the New Structure?

### Installation Guide

- System requirements and prerequisites
- Multiple installation methods (pip, uv, from source)
- Package overview and capability groups
- API key setup
- Configuration auto-created on first daemon startup
- Platform-specific notes
- Troubleshooting installation issues

### Quick-Start Guide

- Your first Soothe session
- Interactive TUI mode
- One-shot prompt mode
- Basic usage patterns
- Using subagents
- Slash commands
- Configuration quick reference
- Common workflows
- Using the daemon
- Tips for success

### Basic Concepts

- Core architecture
- Three-level execution model
- Goals and threads
- Subagents
- Tools
- Memory and context
- Protocols and backends
- Security model
- Daemon architecture
- Event system
- Planning and execution
- Configuration hierarchy

---

## 🔗 Quick Links

- **[Installation →](getting-started/Installation.md)**
- **[Quick-Start →](getting-started/Quick-Start.md)**
- **[Basic Concepts →](getting-started/Basic-Concepts.md)**

---

## 🆘 Need Help?

- **Troubleshooting**: See the [Troubleshooting Guide](troubleshooting.md)
- **Configuration**: See the [Configuration Guide](configuration.md)
- **Architecture**: See the [Architecture Overview](architecture/index.md)
---
title: Home
layout: default
nav_order: 1
description: >-
  Soothe — goal-driven orchestration framework for 24/7 autonomous agents.
permalink: /
---

# Soothe Documentation

> **Goal-driven orchestration framework for building 24/7 long-running autonomous agents**

Soothe is an agent-harnessing framework — an *Agentic OS* that pushes humans
**out of the execution loop**. Built on LangChain / DeepAgents, it adds a
persistent **agentic loop** and **goal engine** that maintains context across
sessions, sustains long-running goals, coordinates multiple objectives, and
autonomously steers complex tasks.

---

## Quick Start

```bash
# Install the complete stack
pip install -U 'soothe[all]' soothe-cli soothe-daemon

# Set your API key
export OPENAI_API_KEY=sk-...

# Initialize configuration
soothe config init

# Run your first query
soothe -p "List all Python files in the current directory and count lines of code"
```

---

## Documentation

Browse the full documentation in the [Soothe Wiki](wiki/):

| Section | What you'll find |
|---------|------------------|
| [Getting Started](wiki/getting-started/) | Installation, quick start, basic concepts |
| [Architecture](wiki/architecture/) | System design, three-level execution model |
| [Core Modules](wiki/core/) | Agent factory, runner, strange loop, goal engine |
| [Configuration](wiki/configuration-guide/) | YAML reference, environment variables, providers |
| [Backends](wiki/backends/) | Memory, durability, vector store, persistence |
| [Capabilities](wiki/capabilities/) | Subagents, tools, MCP integration |
| [Protocols](wiki/protocols/) | Protocol definitions and taxonomy |
| [Deployment](wiki/deployment/) | Production setup, monitoring, security, scaling |
| [API Reference](wiki/api-reference/) | Core, daemon, and SDK package APIs |
| [Troubleshooting](wiki/troubleshooting) | Common issues and solutions |
| [FAQ](wiki/faq) | Frequently asked questions |
| [Changelog](wiki/changelog) | Version history and release notes |

---

## Resources

- **[GitHub](https://github.com/mirasoth/soothe)** — Source code and issues
- **[PyPI](https://pypi.org/project/soothe/)** — Python package index
- **[RFC Specifications](specs/)** — Design documents for each component

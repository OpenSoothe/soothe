# Soothe User Guide

## Introduction

Soothe is a Goal-driven orchestration framework for building 24/7 long-running autonomous agents. It extends deepagents with planning, context engineering, security policy, durability, and remote agent interoperability while remaining langchain-ecosystem-friendly.

Soothe can work autonomously on complex tasks, maintain context across long conversations, and leverage specialized subagents for different types of work including filesystem search, planning, research synthesis, browser automation, and verification. It also supports MCP (Model Context Protocol) servers for extending capabilities with external tools and services.

## Quick Start

Get started with Soothe in minutes:

```bash
# 1. Install Soothe (complete stack)
pip install -U 'soothe[all]' soothe-cli soothe-daemon

# 2. Start the daemon (auto-creates ~/.soothe/ directory)
soothed start

# 3. Set your API key
export OPENAI_API_KEY=sk-your-key-here

# 4. Launch Soothe
soothe
```

For detailed setup instructions, see the [Getting Started Guide](getting-started/index.md).

---

## 📦 Monorepo Structure

Soothe is organized as a monorepo with multiple packages:

```
packages/
├── soothe/              # Agent core (library)
├── soothe-cli/          # CLI client (Typer CLI + Textual TUI)
├── soothe-daemon/       # Daemon-specific components
├── soothe-sdk/          # Shared SDK (WebSocket client, protocol, types)
└── soothe-plugins/      # Optional delegated agents and community plugins
```

| Package | Purpose |
|---------|---------|
| `soothe` | Agent core (library) with agent runtime, protocols, and backends |
| `soothe-cli` | Command-line interface and terminal UI for interacting with the daemon |
| `soothe-daemon` | Daemon lifecycle management and server components |
| `soothe-sdk` | Shared SDK for building clients and plugins (WebSocket client, protocol definitions, types, decorators) |
| `soothe-plugins` | Optional delegated agents and community plugins (separate repo) |

---

## 🧭 Wiki Navigation

Browse the complete Soothe documentation organized by user journey.

### 🚀 Getting Started

- [Getting Started Hub](getting-started/index.md) - Installation, configuration, first run
  - [Installation Guide](getting-started/Installation.md) - System requirements and setup
  - [Quick-Start Guide](getting-started/Quick-Start.md) - Your first session and workflows
  - [Basic Concepts](getting-started/Basic-Concepts.md) - Core architecture and concepts
- [CLI Reference](cli-reference.md) - Complete command-line interface documentation
- [TUI Guide](tui-guide.md) - Terminal UI usage, slash commands, and keyboard shortcuts

### 📖 User Guides

- [Specialized Subagents](subagents.md) - Core plan, tacitus, browser_use, skillify, and veritas; optional agents from soothe-plugins
- [Autonomous Mode](autonomous-mode.md) - Enable autonomous iteration for complex tasks
- [Thread Management](thread-management.md) - Work with conversation threads and maintain context
- [MCP Servers](capabilities/mcp.md) - Extend capabilities with Model Context Protocol servers

### 🔧 Configuration & Management

- [Configuration Guide](configuration-guide/index.md) - Environment variables, YAML config, and model routing
- [Daemon Management](daemon-management.md) - Manage the Soothe daemon lifecycle
- [Transport Setup](multi-transport.md) - Configure WebSocket
- [Authentication](authentication.md) - API keys, JWT, and security model

### 🛠️ Troubleshooting & Advanced

- [Debug Guide](howto_debug.md) - Enable debug logs, diagnose issues, log locations
- [Troubleshooting Guide](troubleshooting.md) - Common issues and solutions

---

## 👨‍💻 Developer Resources

Technical documentation for developers and system architects.

### Design Specifications

| RFC | Title |
|-----|-------|
| [RFC-000](../specs/RFC-000-system-conceptual-design.md) | System Conceptual Design |
| [RFC-001](../specs/RFC-001-core-modules-architecture.md) | Core Modules Architecture |
| [RFC-100](../specs/RFC-100-coreagent-runtime.md) | CoreAgent Runtime |
| [RFC-101](../specs/RFC-101-tool-interface.md) | Tool Interface |
| [RFC-102](../specs/RFC-102-security-filesystem-policy.md) | Security Filesystem Policy |
| [RFC-200](../specs/archive/RFC-200-autonomous-goal-management.md) | Autonomous Goal Management (archived) |
| [RFC-201](../specs/RFC-201-strangeloop-plan-execute-loop.md) | StrangeLoop Plan-Execute Loop |
| [RFC-300](../specs/archive/RFC-300-context-memory-protocols.md) | Context and Memory Protocols (archived) |
| [RFC-302](../specs/RFC-302-context-protocol-architecture.md) | Context Protocol Architecture |
| [RFC-401](../specs/RFC-401-event-processing.md) | Event Processing |
| [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) | Daemon Communication Protocol |
| [RFC-500](../specs/RFC-500-cli-tui-architecture.md) | CLI TUI Architecture |
| [RFC-600](../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](../specs/RFC-601-built-in-agents.md) | Built-in Agents |

### Implementation Guides

> Earlier implementation guides (IG-351 through IG-437) were superseded by the
> current series starting at IG-501. Only IG-501+ files exist in `docs/impl/`.

| Guide | Title |
|-------|-------|
| [IG-501](../impl/IG-501-dynamic-rate-limit-adjustment.md) | Dynamic LLM Rate Limit Adjustment |
| [IG-502](../impl/IG-502-cron-service-implementation.md) | Cron Service Implementation |
| [IG-503](../impl/IG-503-file-descriptor-leak-and-network-resilience-fixes.md) | File Descriptor Leak and Network Resilience Fixes |
| [IG-504](../impl/IG-504-remove-http-rest-channel.md) | Remove HTTP REST Channel |
| [IG-505](../impl/IG-505-identity-service-implementation.md) | Identity Service Implementation |
| [IG-506](../impl/IG-506-coreagent-cold-start-and-code-interpreter-prep.md) | CoreAgent Cold Start and Code Interpreter Prep |
| [IG-507](../impl/IG-507-loop-3328-log-analysis-fixes.md) | Loop 3328 Log Analysis Fixes |
| [IG-508](../impl/IG-508-step-full-description.md) | Step Full Description for Enhanced Execution Context |
| [IG-509](../impl/IG-509-loop-7cba-hang-analysis.md) | Loop 7cba Hang Analysis |
| [IG-510](../impl/IG-510-grep-fallback-hang-recovery.md) | Grep Fallback Hang Recovery |
| [IG-511](../impl/IG-511-tool-timeout-analysis.md) | Tool Timeout Architecture Analysis |
| [IG-512](../impl/IG-512-step-card-display-refactor.md) | Step Card Display Refactor (RFC-628) |
| [IG-513](../impl/IG-513-subagent-card.md) | SubAgent Card — Flattened Display (RFC-628 Part II) |
| [IG-514](../impl/IG-514-execute-namespace-tool-stamping-fix.md) | Execute Namespace Tool Stamping Fix |
| [IG-515](../impl/IG-515-step-subagent-card-footer-and-lifecycle-fixes.md) | Step / SubAgent Card Footer & Lifecycle Fixes (RFC-628) |

---

## Getting Help

- Use `/help` in the TUI to see available commands
- Check the [Troubleshooting Guide](troubleshooting.md) for common issues
- Review daemon logs at `~/.soothe/logs/soothed.log`
- Browse the [RFC specifications](../specs/) for design details
- Check the [implementation guides](../impl/) for technical documentation
- See the [Event Catalog](../specs/event-catalog.md) for all event types and their schemas
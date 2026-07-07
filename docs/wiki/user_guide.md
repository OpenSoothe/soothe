---
title: "User Guide (Legacy)"
parent: Wiki
nav_order: 2.1
description: >-
  Legacy comprehensive user guide — the canonical User Guides hub lives at user-guides/index.md.
redirect_to: user-guides/index.md
canonical: user-guides/index.md
---

# Soothe User Guide

> **This page is a legacy comprehensive guide.** The canonical User Guides hub is
> at **[User Guides](user-guides/index.md)**, which links to focused per-topic
> guides. This page is retained for its consolidated RFC and IG reference tables
> below.

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

- [Specialized Subagents](subagents.md) - Core planner, deep_research, academic_research, browser_use, and veritas; optional agents from soothe-plugins. Semantic skill search via `search_skills` / `skillify:` config.
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
- [Troubleshooting Guide](troubleshooting/index.md) - Common issues and solutions

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
| [RFC-624](../specs/RFC-624-context-engine.md) | Context Engine (Autonomous Goal Management) |
| [RFC-200](../specs/archive/RFC-200-autonomous-goal-management.md) | Autonomous Goal Management (archived, superseded by RFC-624) |
| [RFC-201](../specs/RFC-201-strangeloop-plan-execute-loop.md) | StrangeLoop Plan-Execute Loop |
| [RFC-302](../specs/RFC-302-context-protocol-architecture.md) | Context Protocol Architecture |
| [RFC-300](../specs/archive/RFC-300-context-memory-protocols.md) | Context and Memory Protocols (archived, superseded by RFC-302) |
| [RFC-401](../specs/RFC-401-event-processing.md) | Event Processing |
| [RFC-450](../specs/RFC-450-daemon-communication-protocol.md) | Daemon Communication Protocol |
| [RFC-500](../specs/RFC-500-cli-tui-architecture.md) | CLI TUI Architecture |
| [RFC-600](../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](../specs/RFC-601-built-in-agents.md) | Built-in Agents |

### Implementation Guides

> Current implementation guides (IG-531 through IG-557). Earlier IG series (IG-351–437, IG-501–515) were superseded.

| Guide | Title |
|-------|-------|
| [IG-531](../impl/IG-531-typescript-client-appkit.md) | TypeScript Client Core Upgrade and Appkit |
| [IG-532](../impl/IG-532-daemon-intent-hint-direct-model-turns.md) | Daemon `intent_hint` Direct Model Turns |
| [IG-533](../impl/IG-533-goal-completion-tui-worker-lifecycle-fixes.md) | Goal-Completion TUI & Worker Lifecycle Fixes |
| [IG-534](../impl/IG-534-daemon-tui-performance-isolation.md) | Daemon ↔ TUI Performance Isolation |
| [IG-535](../impl/IG-535-phase4-hidden-bottleneck-optimizations.md) | Phase 4 Hidden Bottleneck Optimizations |
| [IG-536](../impl/IG-536-plan-generation-benchmark.md) | Plan Generation Benchmark |
| [IG-537](../impl/IG-537-context-loop-planning-consolidation.md) | Context vs Loop Planning Consolidation |
| [IG-538](../impl/IG-538-unified-planner-prompt-assembly.md) | Unified Planner Prompt Assembly |
| [IG-539](../impl/IG-539-cross-wave-step-dag-planning.md) | Cross-Wave Step DAG Planning |
| [IG-540](../impl/IG-540-intent-classify-prompt-ledger-optimization.md) | Intent-Classify Prompt & Ledger Optimization |
| [IG-541](../impl/IG-541-tui-markdown-theme-registry.md) | TUI Markdown Theme Registry |
| [IG-542](../impl/IG-542-execute-step-ledger-projection.md) | Execute-Step Ledger Projection |
| [IG-543](../impl/IG-543-skill-runtime-discovery.md) | Skill Runtime Discovery |
| [IG-544](../impl/IG-544-tui-step-flow-and-plan-quick-view.md) | TUI Step Flow & Plan Quick View |
| [IG-545](../impl/IG-545-coreagent-role-routing-middleware.md) | CoreAgent Role Routing Middleware |
| [IG-546](../impl/IG-546-loop-tui-event-throughput.md) | Loop TUI Event Throughput |
| [IG-547](../impl/IG-547-remove-explore-subagent.md) | Remove `explore` Subagent |
| [IG-548](../impl/IG-548-goal-display-snapshots.md) | Goal-Bound Display Snapshots |
| [IG-549](../impl/IG-549-loop-worker-goal-boundary-hardening.md) | Loop Worker Goal-Boundary Hardening |
| [IG-550](../impl/IG-550-high-performance-persistence.md) | High-Performance Persistence Optimization |
| [IG-551](../impl/IG-551-mid-loop-continuation-planning-coordination.md) | Mid-Loop Continuation Planning Coordination |
| [IG-552](../impl/IG-552-goal-completion-report-cli-format.md) | Goal Completion Report CLI Format |
| [IG-553](../impl/IG-553-soothe-log-stability-fixes.md) | soothe.log Stability Fixes |
| [IG-554](../impl/IG-554-two-pass-intake-classification-implementation.md) | Two-Pass Intake Classification |
| [IG-555](../impl/IG-555-plan-assess-prior-goal-completion-bias-mitigation.md) | Plan-Assess Goal Completion Bias Mitigation |
| [IG-556](../impl/IG-556-stream-termination-unification.md) | Stream Termination Unification |
| [IG-557](../impl/IG-557-mid-goal-plan-assess-accuracy.md) | Mid-Goal Plan-Assess Accuracy |
| [IG-XXX](../impl/IG-XXX-ledger-context-bounds.md) | Ledger Context Bounds for Multi-Goal Loops |

---

## Getting Help

- Use `/help` in the TUI to see available commands
- Check the [Troubleshooting Guide](troubleshooting/index.md) for common issues
- Review daemon logs at `~/.soothe/logs/soothed.log`
- Browse the [RFC specifications](../specs/) for design details
- Check the [implementation guides](../impl/) for technical documentation
- See the [Event Catalog](../specs/event-catalog.md) for all event types and their schemas
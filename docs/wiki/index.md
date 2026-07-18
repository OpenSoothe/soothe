---
title: Wiki
layout: default
nav_order: 2
has_children: true
description: >-
  Soothe documentation wiki — comprehensive guides for users, developers, and operators.
permalink: /wiki/
---

# Soothe Wiki

> **Goal-driven orchestration framework for building 24/7 long-running autonomous agents**

Welcome to the Soothe documentation. This wiki provides comprehensive guides for users, developers, and operators.

---

## 🚀 Quick Start

**New to Soothe?** Start with **[Quick Start](getting-started/Quick-Start.md)** — install CLI, start the daemon (Docker or local), run your first prompt. Then browse [Getting Started](getting-started/index.md) for installation details and core concepts.

---

## 📖 Documentation Index

### 🚀 Getting Started

- **[Getting Started Hub](getting-started/index.md)** - Start here!
  - **[Installation](getting-started/Installation.md)** - System requirements, installation methods, troubleshooting
  - **[Quick Start](getting-started/Quick-Start.md)** - Install, daemon, first prompt, production
  - **[Basic Concepts](getting-started/Basic-Concepts.md)** - Core architecture and concepts
- **[Language Clients](clients.md)** - Python / TypeScript / Go / Rust WebSocket SDKs
- **[CLI Reference](cli-reference.md)** - Complete CLI documentation with examples
- **[TUI Guide](tui-guide.md)** - Terminal UI, slash commands, keyboard shortcuts
- **[Architecture Overview](architecture/index.md)** ⭐ - System design and concepts

### 🤖 Core Capabilities

- **[Autonomous Mode](autonomous-mode.md)** - Multi-step autonomous task execution
- **[Subagents](subagents.md)** - Specialized subagents (planner, deep_research, academic_research, veritas, etc.)
- **[Thread Management](thread-management.md)** - Conversation threads and session resumption

### 🔧 Configuration & Management

- **[Configuration Guide](configuration-guide/index.md)** ⭐ - Complete configuration reference
  - **[YAML Reference](configuration-guide/yaml-reference.md)** - Full YAML schema with all options
  - **[Environment Variables](configuration-guide/environment-variables.md)** - SOOTHE_* variables reference
  - **[Common Patterns](configuration-guide/common-patterns.md)** - Real-world configuration examples
  - **[Provider Setup](configuration-guide/provider-setup.md)** - LLM providers, vector stores, persistence
- **[Configuration (Quick Reference)](configuration.md)** - Quick config overview
- **[Daemon Management](daemon-management.md)** - Daemon lifecycle (start, stop, attach)
- **[Transport Setup](multi-transport.md)** - WebSocket transport configuration
- **[Authentication](authentication.md)** - External authentication with reverse proxies

### 🚀 Deployment & Operations

- **[Deployment Guide](deployment/index.md)** ⭐ - Production deployment patterns
  - **[Production Setup](deployment/production-setup.md)** - Docker Compose, systemd, Kubernetes
  - **[Monitoring & Observability](deployment/monitoring.md)** - Langfuse, logs, health checks
  - **[Security Hardening](deployment/security.md)** - Reverse proxy, TLS, access control
  - **[Scaling Strategies](deployment/scaling.md)** - Horizontal scaling, Kubernetes, performance tuning
  - **[Backup & Recovery](deployment/backup-recovery.md)** - PostgreSQL backup, disaster recovery

### 🏗️ Architecture & Core Modules

- **[Core Modules Overview](core/index.md)** ⭐ - Core framework architecture
  - **[Agent Factory](core/agent-factory.md)** - CoreAgent construction and runtime
  - **[SootheRunner](core/runner.md)** - Protocol-orchestrated execution
  - **[StrangeLoop](core/strangeloop.md)** - Plan-Execute loop for single goals
  - **[ContextEngine](core/goal-engine.md)** - Autonomous goal management
  - **[Event System](core/events.md)** - Event infrastructure and registration
  - **[Protocol Resolver](core/resolver.md)** - Protocol wiring from config
  - **[Workspace Management](core/workspace.md)** - Workspace resolution and validation
- **[Architecture Overview](architecture/index.md)** - System design and concepts

### 🔧 Backend Implementations

- **[Backends Overview](backends/index.md)** ⭐ - Protocol implementations
  - **[Memory Backends](backends/memory-backends.md)** - MemU semantic memory
  - **[Durability Backends](backends/durability-backends.md)** - SQLite, PostgreSQL thread storage
  - **[Persistence Backends](backends/persistence-backends.md)** - Key-value storage
  - **[Vector Store Backends](backends/vector-store-backends.md)** - PGVector, SQLiteVec, Weaviate
  - **[Policy Backends](backends/policy-backends.md)** - Config-driven security policies

### 🛠️ Troubleshooting

- **[Troubleshooting](troubleshooting.md)** - Common issues, error messages, and solutions
- **[Query Processing Flow](query-processing-flow.md)** - How queries flow through the system

### 📚 Reference & Community

- **[FAQ](faq.md)** ⭐ - Frequently asked questions organized by topic
- **[Changelog](changelog.md)** - Version history and release notes
- **[Testing Guide](testing-guide.md)** - Comprehensive testing workflow
- **[Contributing Guide](contributing-guide.md)** - Development workflow and code standards

---

## 🏗️ Architecture

### Three-Level Execution Model

```
┌─────────────────────────────────────────────────────────────┐
│ ContextEngine: Autonomous Goal Management (RFC-624)        │
│ • Manages goal DAGs, delegates single goals to StrangeLoop   │
│ • Loop: Goal/Goals → PLAN → PERFORM → REFLECT → Update     │
└─────────────────────────────────────────────────────────────┘
                          ↓ PERFORM (full delegation)
┌─────────────────────────────────────────────────────────────┐
│ StrangeLoop: Agentic Goal Execution (RFC-201)                 │
│ • Executes single goals through Plan → Execute iterations   │
│ • Loop: Plan → Execute (max ~8 iterations)                 │
└─────────────────────────────────────────────────────────────┘
                          ↓ EXECUTE (step execution)
┌─────────────────────────────────────────────────────────────┐
│ CoreAgent: Runtime (RFC-100)                                │
│ • Model → Tools → Model loop (LangGraph native)            │
│ • Foundation: create_soothe_agent() → CompiledStateGraph    │
└─────────────────────────────────────────────────────────────┘
```

**Key Principles:**
- **Protocol-first design** - All modules defined as protocols with pluggable implementations
- **Durable by default** - Agent state persists and recovers from crashes
- **Plan-driven execution** - Complex goals decomposed into plans with steps
- **Least-privilege delegation** - Fine-grained permissions for tools and subagents

**Learn more:** [Architecture Overview](architecture/index.md) | [RFC-000](../specs/RFC-000-system-conceptual-design.md)

### Framework Stack

```
+------------------------------------------------------+
|  Soothe (orchestration framework)                    |
|  - ContextEngine: Autonomous Goal Management         |
|  - StrangeLoop: Agentic Goal Execution                 |
|  - CoreAgent: Runtime                                |
|  - MemoryProtocol, PlannerProtocol,                 |
|    PolicyProtocol, DurabilityProtocol               |
+------------------------------------------------------+
|  deepagents (agent framework)                        |
|  - BackendProtocol, AgentMiddleware,                 |
|    SubAgent/CompiledSubAgent, SummarizationMiddleware|
+------------------------------------------------------+
|  langchain / langgraph (runtime layer)               |
|  - BaseChatModel, BaseTool, StateGraph,              |
|    Checkpointer, BaseStore, RemoteGraph              |
+------------------------------------------------------+
```

### Plan → Execute Loop

```
User Query
    ↓
PLAN (LLM plans, assesses progress, decides steps)
    ↓
EXECUTE (execute tools, collect results)
    ↓
Assess Progress → More steps needed? → PLAN
                  ↓
              Complete → Return Result
```

**Benefits:**
- Automatic strategy adjustment
- Structured tool outputs for reliable evaluation
- Sub-second responses for simple queries
- Intelligent iteration for complex tasks

---

## 🔌 Plugin System

Extend Soothe with custom tools and subagents:

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_tool", description="Custom tool")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"
```

**Learn more:** [RFC-600: Plugin Extension System](../specs/RFC-600-plugin-extension-system.md)

---

## 📚 Additional Resources

- **[Architecture Overview](architecture/index.md)** - Detailed system design
- **[RFC Index](../specs/rfc-index.md)** - All specifications (73 RFCs)
- **[Implementation Guides](../impl/)** - Implementation tracking
- **[Debugging Guide](howto_debug.md)** - Debug and diagnostics
- **[User Guides](user-guides/index.md)** - Comprehensive user documentation

---

## 🆘 Getting Help

- **Documentation**: You're here! Browse the guides above.
- **Troubleshooting**: See [Troubleshooting Guide](troubleshooting.md)
- **Issues**: Report bugs on GitHub Issues
- **Community**: Join discussions on GitHub Discussions

---

## Feature Status

| Feature | Status | Documentation |
|---------|--------|---------------|
| **Intelligent Execution Loop** | ✅ Production Ready | [RFC-201](../specs/RFC-201-strangeloop-plan-execute-loop.md) |
| **Research Subagent** | ✅ Production Ready | [Subagents Guide](subagents.md#research-subagent) |
| **Plugin System** | ✅ Production Ready | [RFC-600](../specs/RFC-600-plugin-extension-system.md) |
| **Multi-Transport Daemon** | ✅ Production Ready | [Multi-Transport Setup](multi-transport.md) |
| **Thread Management** | ✅ Production Ready | [Thread Management](thread-management.md) |
| **Security Policies** | ✅ Production Ready | [RFC-102](../specs/RFC-102-security-filesystem-policy.md) |
| **Autonomous Mode** | 🚧 Experimental | [Autonomous Mode](autonomous-mode.md) |

---

## Additional Resources

### 📖 Extended Documentation

- **[User Guides](user-guides/index.md)** - Comprehensive usage guide with detailed examples
- **[RFCs & Specifications](../specs/)** - Technical architecture and design documents
- **[Implementation Guides](../impl/)** - Development documentation

### 🔗 External Links

- **[PyPI Package](https://pypi.org/project/soothe/)** - Install the latest version
- **[GitHub Repository](https://github.com/mirasoth/soothe)** - Source code and issues
- **[DeepWiki](https://deepwiki.com/mirasoth/soothe)** - AI-powered documentation search

---

## Getting Help

### Common Issues

- **API key errors**: See [Configuration](configuration.md#api-keys)
- **Connection errors**: See [Troubleshooting](troubleshooting.md#connection-errors)
- **Performance issues**: See [Troubleshooting](troubleshooting.md#performance)

### Community

- **Report issues**: [GitHub Issues](https://github.com/mirasoth/soothe/issues)
- **Ask questions**: Use GitHub Discussions or check the Troubleshooting guide

---

## Contributing

Interested in contributing to Soothe? See:

- **[AGENTS.md](../../AGENTS.md)** - Development guide for AI agents
- **[RFCs](../specs/)** - Architecture design documents
- **[Implementation Guides](../impl/)** - Development documentation
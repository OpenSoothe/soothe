# Soothe User Guide

## Introduction

Soothe is a protocol-driven orchestration framework for building 24/7 long-running autonomous agents. It extends deepagents with planning, context engineering, security policy, durability, and remote agent interoperability while remaining langchain-ecosystem-friendly.

Soothe can work autonomously on complex tasks, maintain context across long conversations, and leverage specialized subagents for different types of work including web browsing, complex reasoning, skill retrieval, and agent generation.

## Quick Start

Get started with Soothe in minutes:

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

For detailed setup instructions, see the [Getting Started Guide](wiki/getting-started.md).

---

## 🧭 Wiki Navigation

Browse the complete Soothe documentation organized by user journey.

### 🚀 Getting Started

- [Getting Started Guide](wiki/getting-started.md) - Install, configure, and run your first session
- [CLI Reference](wiki/cli-reference.md) - Complete command-line interface documentation
- [TUI Guide](wiki/tui-guide.md) - Terminal UI usage, slash commands, and keyboard shortcuts

### 📖 User Guides

- [Specialized Subagents](wiki/subagents.md) - Overview of Browser, Claude, Skillify, and Weaver subagents
- [Autonomous Mode](wiki/autonomous-mode.md) - Enable autonomous iteration for complex tasks
- [Thread Management](wiki/thread-management.md) - Work with conversation threads and maintain context

### 🔧 Configuration & Management

- [Configuration Guide](wiki/configuration.md) - Environment variables, YAML config, and model routing
- [Daemon Management](wiki/daemon-management.md) - Manage the Soothe daemon lifecycle
- [Multi-Transport Setup](wiki/multi-transport.md) - Configure Unix Socket, WebSocket, and HTTP REST
- [Authentication](wiki/authentication.md) - API keys, JWT, and security model

### 🛠️ Troubleshooting & Advanced

- [Troubleshooting Guide](wiki/troubleshooting.md) - Common issues and solutions

---

## 👨‍💻 Developer Resources

Technical documentation for developers and system architects.

### Design Specifications

| RFC | Title |
|-----|-------|
| [RFC-0001](specs/RFC-0001.md) | System Conceptual Design |
| [RFC-0002](specs/RFC-0002.md) | Core Modules Architecture |
| [RFC-0003](specs/RFC-0003.md) | CLI TUI Architecture |
| [RFC-0004](specs/RFC-0004.md) | Skillify Agent Architecture |
| [RFC-0005](specs/RFC-0005.md) | Weaver Agent Architecture |
| [RFC-0006](specs/RFC-0006.md) | Context and Memory Architecture |
| [RFC-0007](specs/RFC-0007.md) | Autonomous Iteration Loop |
| [RFC-0008](specs/RFC-0008.md) | Protocol Specification |
| [RFC-0009](specs/RFC-0009.md) | DAG-Based Execution and Unified Concurrency |
| [RFC-0010](specs/RFC-0010.md) | Failure Recovery, Progressive Persistence, and Artifact Storage |
| [RFC-0011](specs/RFC-0011.md) | Unified Planning Architecture |
| [RFC-0012](specs/RFC-0012.md) | Unified Complexity Classification |
| [RFC-0013](specs/RFC-0013.md) | Unified Daemon Communication Protocol |
| [RFC-0015](specs/RFC-0015.md) | Progress Event Protocol |
| [RFC-0015](specs/RFC-0015.md) | Authentication and Security Model |
| [RFC-0016](specs/RFC-0016.md) | HTTP REST API Specification |

### Implementation Guides

| Guide | Title |
|-------|-------|
| [IG-001](impl/001-soothe-setup-migration.md) | Soothe Setup and Migration |
| [IG-002](impl/002-soothe-polish.md) | Soothe Polish |
| [IG-003](impl/003-streaming-examples.md) | Streaming Examples |
| [IG-004](impl/004-ecosystem-capability-analysis.md) | Ecosystem Capability Analysis |
| [IG-005](impl/005-core-protocols-implementation.md) | Core Protocols Implementation |
| [IG-006](impl/006-vectorstore-router-persistence.md) | VectorStore, Router, Persistence |
| [IG-007](impl/007-cli-tui-implementation.md) | CLI TUI Implementation |
| [IG-008](impl/008-config-docs-revision.md) | Config and Docs Revision |
| [IG-009](impl/009-ollama-provider.md) | Ollama Provider |
| [IG-010](impl/010-tui-layout-history-refresh.md) | TUI Layout, History, Refresh |
| [IG-011](impl/011-skillify-agent-implementation.md) | Skillify Agent Implementation |
| [IG-012](impl/012-weaver-agent-implementation.md) | Weaver Agent Implementation |
| [IG-013](impl/013-soothe-polish-pass.md) | Soothe Polish Pass |
| [IG-014](impl/014-code-structure-revision.md) | Code Structure Revision |
| [IG-015](impl/015-rfc-gap-closure-and-compat-hard-cut.md) | RFC Gap Closure and Compatibility |
| [IG-016](impl/016-agent-optimization-pass.md) | Agent Optimization Pass |
| [IG-017](impl/017-progress-events-tools-polish.md) | Progress Events and Tools Polish |
| [IG-018](impl/018-autonomous-iteration-loop.md) | Autonomous Iteration Loop |
| [IG-019](impl/019-soothe-tools-enhancement.md) | Soothe Tools Enhancement |
| [IG-020](impl/020-detached-daemon-autonomous-capability.md) | Detached Daemon Autonomous Capability |
| [IG-021](impl/021-daemon-lifecycle-fixes.md) | Daemon Lifecycle Fixes |
| [IG-022](impl/022-unified-persistence-storage.md) | Unified Persistence Storage |
| [IG-023](impl/023-failure-recovery-progressive-persistence.md) | Failure Recovery, Progressive Persistence |
| [IG-024](impl/024-existing-browser-connection.md) | Existing Browser Connection |
| [IG-025](impl/025-subagent-progress-visibility.md) | Subagent Progress Visibility |
| [IG-026](impl/026-rfc0009-logging-enhancements.md) | RFC-0009 Logging Enhancements |
| [IG-027](impl/027-final-report-cli-output.md) | Final Report CLI Output |
| [IG-028](impl/028-direct-to-simple-planner-renaming.md) | Direct to Simple Planner Renaming |
| [IG-029](impl/029-planner-refactoring.md) | Planner Refactoring |
| [IG-032](impl/032-unified-complexity-classification.md) | Unified Complexity Classification |
| [IG-033](impl/033-secure-filesystem-path-handling.md) | Secure Filesystem Path Handling |
| [IG-034](impl/034-cli-modularization.md) | CLI Modularization |
| [IG-035](impl/035-scout-then-plan-implementation.md) | Scout-Then-Plan Implementation |
| [IG-036](impl/036-planning-workflow-refactoring.md) | Planning Workflow Refactoring |
| [IG-037](impl/037-unified-classifier-refactoring.md) | Unified Classifier Refactoring |
| [IG-038](impl/038-code-structure-refactoring.md) | Code Structure Refactoring |
| [IG-039](impl/039-capability-abstraction-tool-consolidation.md) | Capability Abstraction and Tool Consolidation |
| [IG-040](impl/040-tool-optimization-complete.md) | Tool Optimization Complete |
| [IG-041](impl/041-cli-polish.md) | CLI Polish |
| [IG-042](impl/042-tool-events-polish.md) | Tool Events Polish |
| [IG-043](impl/043-unified-planning-complete.md) | Unified Planning Complete |
| [IG-044](impl/044-unified-planning-final-report.md) | Unified Planning Final Report |
| [IG-045](impl/045-agentic-loop-implementation.md) | Agentic Loop Implementation |
| [IG-046](impl/046-unified-daemon-protocol.md) | Unified Daemon Protocol |

---

## Getting Help

- Use `/help` in the TUI to see available commands
- Check the [Troubleshooting Guide](wiki/troubleshooting.md) for common issues
- Review daemon logs at `~/.soothe/logs/daemon.log`
- Browse the [RFC specifications](specs/) for design details
- Check the [implementation guides](impl/) for technical documentation
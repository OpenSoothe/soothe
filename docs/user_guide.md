# Soothe User Guide

## Introduction

Soothe is a Goal-driven orchestration framework for building 24/7 long-running autonomous agents. It extends deepagents with planning, context engineering, security policy, durability, and remote agent interoperability while remaining langchain-ecosystem-friendly.

Soothe can work autonomously on complex tasks, maintain context across long conversations, and leverage specialized subagents for different types of work including filesystem search, planning, research synthesis, skill retrieval, and agent generation. It also supports MCP (Model Context Protocol) servers for extending capabilities with external tools and services.

## Quick Start

Get started with Soothe in minutes:

```bash
# 1. Install Soothe (complete stack)
pip install -U 'soothe[all]' soothe-cli soothe-daemon

# 2. Initialize default configuration
soothe config init

# 3. Set your API key
export OPENAI_API_KEY=sk-your-key-here

# 4. Launch Soothe
soothe
```

For detailed setup instructions, see the [Getting Started Guide](wiki/getting-started/README.md).

---

## 📦 Monorepo Structure

Soothe is organized as a monorepo with multiple packages:

```
packages/
├── soothe/              # Main daemon server package
├── soothe-cli/          # CLI client (Typer CLI + Textual TUI)
├── soothe-daemon/       # Daemon-specific components
└── soothe-sdk/          # Shared SDK (WebSocket client, protocol, types)
```

| Package | Purpose |
|---------|---------|
| `soothe` | Core daemon server with agent runtime, protocols, and backends |
| `soothe-cli` | Command-line interface and terminal UI for interacting with the daemon |
| `soothe-daemon` | Daemon lifecycle management and server components |
| `soothe-sdk` | Shared SDK for building clients and plugins (WebSocket client, protocol definitions, types, decorators) |

---

## 🧭 Wiki Navigation

Browse the complete Soothe documentation organized by user journey.

### 🚀 Getting Started

- [Getting Started Hub](wiki/getting-started/README.md) - Installation, configuration, first run
  - [Installation Guide](wiki/getting-started/Installation.md) - System requirements and setup
  - [Quick-Start Guide](wiki/getting-started/Quick-Start.md) - Your first session and workflows
  - [Basic Concepts](wiki/getting-started/Basic-Concepts.md) - Core architecture and concepts
- [CLI Reference](wiki/cli-reference.md) - Complete command-line interface documentation
- [TUI Guide](wiki/tui-guide.md) - Terminal UI usage, slash commands, and keyboard shortcuts

### 📖 User Guides

- [Specialized Subagents](wiki/subagents.md) - Core explore, plan, and research; optional agents from soothe-plugins
- [Autonomous Mode](wiki/autonomous-mode.md) - Enable autonomous iteration for complex tasks
- [Thread Management](wiki/thread-management.md) - Work with conversation threads and maintain context
- [MCP Servers](wiki/mcp-servers.md) - Extend capabilities with Model Context Protocol servers

### 🔧 Configuration & Management

- [Configuration Guide](wiki/configuration.md) - Environment variables, YAML config, and model routing
- [Daemon Management](wiki/daemon-management.md) - Manage the Soothe daemon lifecycle
- [Multi-Transport Setup](wiki/multi-transport.md) - Configure Unix Socket, WebSocket, and HTTP REST
- [Authentication](wiki/authentication.md) - API keys, JWT, and security model

### 🛠️ Troubleshooting & Advanced

- [Debug Guide](howto_debug.md) - Enable debug logs, diagnose issues, log locations
- [Troubleshooting Guide](wiki/troubleshooting.md) - Common issues and solutions

---

## 👨‍💻 Developer Resources

Technical documentation for developers and system architects.

### Design Specifications

| RFC | Title |
|-----|-------|
| [RFC-000](specs/RFC-000-system-conceptual-design.md) | System Conceptual Design |
| [RFC-001](specs/RFC-001-core-modules-architecture.md) | Core Modules Architecture |
| [RFC-100](specs/RFC-100-coreagent-runtime.md) | CoreAgent Runtime |
| [RFC-101](specs/RFC-101-tool-interface.md) | Tool Interface |
| [RFC-102](specs/RFC-102-security-filesystem-policy.md) | Security Filesystem Policy |
| [RFC-200](specs/RFC-200-autonomous-goal-management.md) | Autonomous Goal Management |
| [RFC-201](specs/RFC-201-agentloop-plan-execute-loop.md) | AgentLoop Plan-Execute Loop |
| [RFC-300](specs/RFC-300-context-memory-protocols.md) | Context and Memory Protocols |
| [RFC-400](specs/RFC-400-context-protocol-architecture.md) | Context Protocol Architecture |
| [RFC-401](specs/RFC-401-event-processing.md) | Event Processing |
| [RFC-450](specs/RFC-450-daemon-communication-protocol.md) | Daemon Communication Protocol |
| [RFC-500](specs/RFC-500-cli-tui-architecture.md) | CLI TUI Architecture |
| [RFC-600](specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](specs/RFC-601-built-in-agents.md) | Built-in Agents |

### Implementation Guides

| Guide | Title |
|-------|-------|
| [IG-351](impl/IG-351-cli-shared-reorganization.md) | CLI Shared Reorganization |
| [IG-352](impl/IG-352-subagent-delegation-goal-loop-evidence.md) | Subagent Delegation and Goal Loop Evidence |
| [IG-353](impl/IG-353-planner-performance-prototype.md) | Planner Performance Prototype |
| [IG-355](impl/IG-355-subagent-completion-wire.md) | Subagent Completion Wire |
| [IG-356](impl/IG-356-subagent-gap-closure.md) | Subagent Gap Closure |
| [IG-357](impl/IG-357-act-wave-finalize-polish.md) | Act Wave Finalize and Polish |
| [IG-358](impl/IG-358-replan-step-id-collision.md) | Replan Step ID Collision |
| [IG-359](impl/IG-359-compact-log-level-format.md) | Compact Log Level Format |
| [IG-360](impl/IG-360-compact-logger-module-names.md) | Compact Logger Module Names |
| [IG-361](impl/IG-361-loop-input-content-coercion.md) | Loop Input Content Coercion |
| [IG-362](impl/IG-362-daemon-input-loop-input-queue-parity.md) | Daemon Input Loop Input Queue Parity |
| [IG-363](impl/IG-363-intent-classification-prompt-xml.md) | Intent Classification Prompt XML |
| [IG-364](impl/IG-364-planning-intent-prompt-layout-xml.md) | Planning Intent Prompt Layout XML |
| [IG-365](impl/IG-365-merge-cognition-into-core.md) | Merge Cognition into Core |
| [IG-366](impl/IG-366-policy-virtual-path-glob-root.md) | Policy Virtual Path Glob Root |
| [IG-367](impl/IG-367-langfuse-observability.md) | Langfuse Observability |
| [IG-368](impl/IG-368-remove-detailed-evidence-string.md) | Remove Detailed Evidence String |
| [IG-369](impl/IG-369-langfuse-agentloop-langchain-fix.md) | Langfuse AgentLoop LangChain Fix |
| [IG-370](impl/IG-370-agentloop-evidence-dedup.md) | AgentLoop Evidence Deduplication |
| [IG-371](impl/IG-371-plan-human-omit-working-memory.md) | Plan Human Omit Working Memory |
| [IG-372](impl/IG-372-plan-phase-split-prompts.md) | Plan Phase Split Prompts |
| [IG-374](impl/IG-374-parallel-execute-ledger-for-plan-assess.md) | Parallel Execute Ledger for Plan Assess |
| [IG-375](impl/IG-375-remove-langsmith-tracing.md) | Remove LangSmith Tracing |
| [IG-376](impl/IG-376-plan-assess-human-and-llm-progress.md) | Plan Assess Human and LLM Progress |
| [IG-377](impl/IG-377-plan-human-trim-and-langfuse-execute-step.md) | Plan Human Trim and Langfuse Execute Step |
| [IG-378](impl/IG-378-plan-generate-goal-progress-system.md) | Plan Generate Goal Progress System |
| [IG-379](impl/IG-379-langfuse-cost-dashboard-bridge.md) | Langfuse Cost Dashboard Bridge |
| [IG-380](impl/IG-380-agentloop-plan-ledger-explore-messages.md) | AgentLoop Plan Ledger Explore Messages |
| [IG-381](impl/IG-381-plan-generate-progressive-evidence-explore-bundle.md) | Plan Generate Progressive Evidence Explore Bundle |
| [IG-382](impl/IG-382-remove-stepaction-tools-hint.md) | Remove StepAction Tools Hint |
| [IG-383](impl/IG-383-routing-classification-rename-git-status-trim.md) | Routing Classification Rename Git Status Trim |
| [IG-384](impl/IG-384-system-prompt-merge-and-fallback.md) | System Prompt Merge and Fallback |
| [IG-386](impl/IG-386-agentloop-step-subagent-coreagent-enforcement.md) | AgentLoop Step Subagent CoreAgent Enforcement |
| [IG-387](impl/IG-387-drop-agentloop-tool-result-cache.md) | Drop AgentLoop Tool Result Cache |
| [IG-388](impl/IG-388-plan-generate-sequential-step-ids.md) | Plan Generate Sequential Step IDs |
| [IG-390](impl/IG-390-explore-migrate-create-agent.md) | Explore Migrate Create Agent |
| [IG-391](impl/IG-391-explore-execute-readonly-prompt.md) | Explore Execute Readonly Prompt |
| [IG-392](impl/IG-392-event-bus-drop-log-throttle.md) | Event Bus Drop Log Throttle |
| [IG-393](impl/IG-393-explore-max-iterations-defaults.md) | Explore Max Iterations Defaults |
| [IG-394](impl/IG-394-langgraph-agent-loop-orchestrator.md) | LangGraph Agent Loop Orchestrator |
| [IG-395](impl/IG-395-langfuse-trace-goal-io.md) | Langfuse Trace Goal IO |
| [IG-396](impl/IG-396-rfc-220-loop-graph-topology-langfuse.md) | RFC-220 Loop Graph Topology Langfuse |
| [IG-397](impl/IG-397-agentloop-graph-intent-and-assess-bypass.md) | AgentLoop Graph Intent and Assess Bypass |
| [IG-398](impl/IG-398-cancellation-propagation-agentloop.md) | Cancellation Propagation AgentLoop |
| [IG-399](impl/IG-399-plan-pre-generate-evidence-and-flat-generation.md) | Plan Pre-generate Evidence and Flat Generation |
| [IG-400](impl/IG-400-planmanager-plandag-architecture.md) | PlanManager PlanDAG Architecture |
| [IG-401](impl/IG-401-plan-generation-optimization.md) | Plan Generation Optimization |
| [IG-402](impl/IG-402-step-card-tool-aggregator.md) | Step Card Tool Aggregator |
| [IG-403](impl/IG-403-event-size-distribution-stats.md) | Event Size Distribution Stats |
| [IG-404](impl/IG-404-tui-card-display-fixes.md) | TUI Card Display Fixes |
| [IG-405](impl/IG-405-virtual-file-system-backend-integration.md) | Virtual File System Backend Integration |
| [IG-406](impl/IG-406-headless-and-tui-goal-completion-output.md) | Headless and TUI Goal Completion Output |
| [IG-407](impl/IG-407-config-unification-agentic-execution.md) | Config Unification Agentic Execution |
| [IG-408](impl/IG-408-loop-client-isolation.md) | Loop Client Isolation |
| [IG-409](impl/IG-409-loop-new-client-workspace.md) | Loop New Client Workspace |
| [IG-410](impl/IG-410-loop-runner-protocol-and-subprocess-isolation.md) | Loop Runner Protocol and Subprocess Isolation |
| [IG-411](impl/IG-411-worker-pool-robustness.md) | Worker Pool Robustness |
| [IG-412](impl/IG-412-tui-coreagent-hitl.md) | CoreAgent interrupt auto-resume (legacy HITL removed) |
| [IG-413](impl/IG-413-plan-subagent-rfc-618.md) | Plan Subagent RFC-618 |
| [IG-414](impl/IG-414-soothe-daemon-package-split.md) | Soothe Daemon Package Split |
| [IG-415](impl/IG-415-optional-community-subagents.md) | Optional Community Subagents |
| [IG-416](impl/IG-416-tool-call-realtime-display.md) | Tool Call Realtime Display |
| [IG-418](impl/IG-418-remove-legacy-tool-call-id.md) | Remove Legacy Tool Call ID |
| [IG-419](impl/IG-419-direct-llm-structured-output.md) | Direct LLM Structured Output |
| [IG-420](impl/IG-420-goal-engine-agentloop-autopilot-integration.md) | Goal Engine AgentLoop Autopilot Integration |
| [IG-421](impl/IG-421-step-card-tool-stats-display.md) | Step Card Tool Stats Display |
| [IG-422](impl/IG-422-cli-runtime-module.md) | CLI Runtime Module |
| [IG-425](impl/IG-425-tacitus-subagent.md) | Tacitus Subagent |
| [IG-426](impl/IG-426-tui-streaming-event-reduction.md) | TUI Streaming Event Reduction |
| [IG-427](impl/IG-427-stream-event-volume-fifo-latency.md) | Stream Event Volume FIFO Latency |
| [IG-428](impl/IG-428-step-card-tool-activity-preview.md) | Step Card Tool Activity Preview |
| [IG-437](impl/IG-437-deepxiv-integration.md) | DeepXiv Integration |

---

## Getting Help

- Use `/help` in the TUI to see available commands
- Check the [Troubleshooting Guide](wiki/troubleshooting.md) for common issues
- Review daemon logs at `~/.soothe/logs/daemon.log`
- Browse the [RFC specifications](specs/) for design details
- Check the [implementation guides](impl/) for technical documentation
- See the [Event Catalog](specs/event-catalog.md) for all event types and their schemas
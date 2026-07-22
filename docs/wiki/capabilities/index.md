---
title: Capabilities
parent: Wiki
has_children: true
nav_order: 7
description: >-
  Subagents, tools, MCP integration, and the plugin system.
permalink: /wiki/capabilities/
---

# Capabilities Layer

The **Capabilities Layer** is Soothe's extensibility framework for adding specialized behaviors through subagents, tools, and MCP integration. It sits between the protocol layer and the backend implementations, providing concrete capabilities that the agent can invoke during execution.

## Architectural Role

Soothe's core agent loop (ContextEngine → StrangeLoop → CoreAgent) is intentionally agnostic about *what* the agent can do. The Capabilities Layer plugs concrete abilities into that loop: single-shot utilities (tools), multi-step workflows (subagents), and externally-sourced capabilities (MCP). All three share the same plugin-based registration and policy-gated execution infrastructure.

The key architectural insight is the **capability spectrum**: tools are stateless and immediate, subagents are stateful and long-running, and MCP bridges to external systems. Choosing the right capability type for a given task is the primary design decision — see the comparison below.

## The Three Capabilities

### Subagents — Multi-Step Workflows

Subagents are specialized autonomous agents that perform multi-step, stateful workflows lasting seconds to minutes. They use the LLM as an orchestrator, can call tools or even other subagents, and return comprehensive structured reports. Each subagent is a compiled LangGraph `StateGraph` with its own state schema, nodes, and flow control.

**Built-in subagents** include:
- **planner** (RFC-618): Structured planning with iterative refinement
- **deep_research** (RFC-619): Public web research with crawl-on-discovery
- **academic_research** (RFC-619): Academic literature research (DeepXiv)
- **browser_use**: Browser automation (included in base dependencies)
- **SkillifyService** (`skillify:` config): Semantic skill retrieval via `search_skills`
- **veritas** (RFC-622): Intent-grounded clarification auto-answerer

→ See [Subagents Architecture](subagents.md) for design philosophy and extension patterns.

### Tools — Single-Purpose Utilities

Tools are stateless, single-shot utilities the agent invokes for immediate operations. Soothe follows the **single-purpose tool design pattern** (RFC-101): one tool performs exactly one operation, named with `{verb}_{noun}` convention, with no mode/action parameters. This eliminates the cognitive load that unified dispatch tools create for the LLM.

Tools are organized into domain-specific **toolkits**: execution, file operations, web search, academic search, media analysis, data inspection, HTTP requests, and datetime. The philosophy is to reuse the langchain ecosystem wherever possible and only build custom tools when no equivalent exists.

→ See [Tools System](tools.md) for design rationale and extension patterns.

### MCP Integration — External Capabilities

MCP (Model Context Protocol) integration provides standardized access to external tools, prompts, and resources. Soothe implements a daemon-singleton MCP subsystem (RFC-412) that wraps `langchain_mcp_adapters.MultiServerMCPClient` with three key additions not found in the base library:

1. **Progressive disclosure** — deferred tools are surfaced via search rather than loaded all at once, avoiding context bloat when MCP servers expose hundreds of tools.
2. **Policy gating** — every MCP operation passes through PolicyProtocol for permission checks.
3. **Reconnect scheduling** — remote transports auto-reconnect with exponential backoff.

→ See [MCP Integration](mcp.md) for architecture and configuration patterns.

## Plugin System

All three capability types are extended through the same **Plugin System** (RFC-600), a decorator-based API:

- `@plugin` marks a class as a plugin with a manifest (name, version, dependencies, trust level)
- `@tool` registers methods as tools
- `@subagent` registers methods as subagent factories
- `@tool_group` marks a class as a collection of related tools

Plugins are discovered through three mechanisms: Python entry points (highest priority), config-declared modules, and filesystem plugins in `~/.soothe/plugins/`. Built-in plugins always win and cannot be overridden.

Trust levels (`built-in`, `trusted`, `standard`, `untrusted`) create security boundaries — a plugin's trust level determines what permissions it can request.

→ See [Extension Patterns](extension-patterns.md) for the full plugin development guide.

## Cross-Cutting Concerns

### Protocol Integration

Every capability is mediated by the protocol layer:

| Capability | Protocol Gate |
|------------|--------------|
| Subagents | PolicyProtocol checks before execution (`subagent:invoke:<name>`) |
| Tools | OperationSecurityProtocol for workspace boundaries |
| MCP | PolicyProtocol gates every tool/resource/prompt call |

### Event System

Capabilities emit domain-specific wire events (RFC-403) following namespaced conventions: `soothe.subagent.<name>.*`, `soothe.tool.<component>.*`, and `soothe.mcp.*`. Events are registered via `register_event()` at module load time and provide observability for the daemon's event stream.

### Configuration

All capabilities are configured via `nano.yml`. Subagents and MCP servers have their own top-level config sections; plugins are declared with module paths and plugin-specific config dicts. Environment variable interpolation (`${ENV_VAR}`) is supported throughout for secrets.

## Key RFCs

| RFC | Title |
|-----|-------|
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](../../specs/RFC-601-built-in-agents.md) | Built-in Plugin Agents |
| [RFC-618](../../specs/RFC-618-plan-subagent-delegation.md) | Plan Subagent |
| [RFC-619](../../specs/RFC-619-deep-research-subagent.md) | Deep Research Subagent |
| [RFC-622](../../specs/RFC-622-veritas-auto-clarification.md) | Veritas Auto-Clarification |
| [RFC-101](../../specs/RFC-101-tool-interface.md) | Tool Interface (single-purpose design) |
| [RFC-412](../../specs/RFC-412-mcp-management.md) | MCP Management |

## Decision Guide: When to Use What

| You need to... | Use |
|----------------|-----|
| Perform a single, immediate operation | A **tool** |
| Run a multi-step workflow with LLM orchestration | A **subagent** |
| Integrate an external service that speaks MCP | An **MCP server** |
| Add a capability not available in langchain | A custom **tool** via plugin |
| Compose multiple searches into a research flow | A **subagent** (e.g., `deep_research` or `academic_research`) |

The golden rule: **check the langchain ecosystem first**. If langchain or deepagents already provides a tool or agent for your need, use it rather than building a custom one.

---

**Next**: [Subagents Architecture](subagents.md) | [Tools System](tools.md) | [MCP Integration](mcp.md) | [Extension Patterns](extension-patterns.md)

# Capabilities Layer

The **Capabilities Layer** is Soothe's extensibility framework for adding specialized behaviors through subagents, tools, and MCP integration. It sits between the protocol layer and the backend implementations, providing concrete capabilities that the agent can invoke during execution.

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Core Agent Loop                                                    │
│  (GoalEngine → StrangeLoop → CoreAgent)                               │
└────────────────────────┬───────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Capabilities Layer                                                 │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  Subagents   │  │    Tools     │  │       MCP                │  │
│  │              │  │              │  │                          │  │
│  │ - explore    │  │ - execution  │  │ - MCPRegistry            │  │
│  │ - plan       │  │ - file_ops   │  │ - Progressive disclosure │  │
│  │ - tacitus    │  │ - wizsearch  │  │ - Prompts as slash cmds  │  │
│  │ - browser_use│  │ - deepxiv    │  │ - Resources as @server   │  │
│  │ - claude     │  │ - audio/vid  │  │ - Policy-gated access    │  │
│  │              │  │ - data/http  │  │                          │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Plugin System (RFC-600)                                      │  │
│  │  - @plugin decorator                                          │  │
│  │  - @tool decorator                                            │  │
│  │  - @subagent decorator                                        │  │
│  │  - Discovery: entry points, config, filesystem               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  Protocol Layer                                                     │
│  (OperationSecurity, Policy, Context, Memory, etc.)                │
└────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Subagents

**Subagents** are specialized autonomous agents that perform multi-step workflows. They differ from tools in several key ways:

| Characteristic | Tool | Subagent |
|----------------|------|----------|
| **Operations** | Single-shot | Multi-step workflows |
| **State** | Stateless | Stateful execution |
| **Duration** | Immediate | Seconds to minutes |
| **Complexity** | Simple | Complex orchestration |
| **Results** | Direct output | Comprehensive reports |

**Built-in Subagents**:
- **explore** (RFC-613): LLM-orchestrated filesystem search
- **plan** (RFC-618): Structured planning with explore delegation
- **tacitus** (RFC-619): Public-domain research (web, academic, URLs)
- **browser_use**: Browser automation (opt-in via `soothe[browser_use]`)
- **claude**: Claude Code agent (opt-in via `soothe[claude]`)

See [Subagents Architecture](subagents.md) for detailed documentation.

### 2. Tools

**Tools** are single-purpose utilities that the agent invokes directly. Soothe follows the **single-purpose tool design pattern** (RFC-101):

- One tool = one operation
- Naming convention: `{verb}_{noun}`
- No mode/action parameters
- Clear descriptions with type hints

**Toolkits** (organized by domain):
- **execution**: `run_command`, `run_python`, `run_background`, `kill_process`
- **file_ops**: `read_file`, `write_file`, `delete_file`, `glob`, `grep`, `ls`
- **wizsearch**: Multi-engine web search
- **deepxiv**: Academic paper search (arXiv, bioRxiv, medRxiv, PMC)
- **audio/video/image**: Media analysis and transcription
- **data**: CSV/Excel inspection and quality checks
- **datetime**: Current date/time utilities
- **http_requests**: HTTP GET/POST/PATCH/PUT/DELETE

See [Tools System](tools.md) for detailed documentation.

### 3. MCP Integration

**MCP (Model Context Protocol)** integration provides standardized access to external tools, prompts, and resources (RFC-412):

- **MCPRegistry**: Daemon-singleton connection manager
- **Progressive disclosure**: Deferred tools surfaced via search
- **Prompts as slash commands**: `/mcp__<server>__<prompt>`
- **Resources as attachments**: `@server:uri` syntax
- **Policy-gated access**: Every MCP operation checked via PolicyProtocol
- **Reconnect scheduling**: Automatic recovery for remote transports

See [MCP Integration](mcp.md) for detailed documentation.

### 4. Plugin System

The **Plugin System** (RFC-600) provides a decorator-based API for extending Soothe:

```python
from soothe_sdk.plugin import plugin, tool, subagent

@plugin(name="my-plugin", version="1.0.0", description="My plugin")
class MyPlugin:
    async def on_load(self, context):
        """Initialize resources."""
        self.api_key = context.config.get("api_key")

    @tool(name="greet", description="Greet someone")
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"

    @subagent(name="researcher", description="Custom research agent")
    async def create_agent(self, model, config, context):
        # Return CompiledSubAgent
        return create_research_agent(model, config)
```

**Discovery mechanisms**:
- **Entry points**: `[project.entry-points."soothe.plugins"]`
- **Config-declared**: `plugins:` section in config.yml
- **Filesystem**: `~/.soothe/plugins/<name>/`

**Trust levels**:
- **built-in**: Full permissions (core capabilities)
- **trusted**: Elevated permissions (verified plugins)
- **standard**: Default permissions (third-party)
- **untrusted**: Restricted permissions (experimental)

See [Extension Patterns](extension-patterns.md) for detailed documentation.

## Integration with Other Layers

### Protocol Integration

All capabilities integrate with Soothe's protocol layer:

| Capability | Protocol Integration |
|------------|---------------------|
| **Subagents** | PolicyProtocol checks before execution |
| **Tools** | OperationSecurityProtocol for workspace boundaries |
| **MCP** | PolicyProtocol gates every tool/resource/prompt call |

### Event System

Capabilities emit domain-specific events following RFC-403 naming conventions:

| Namespace | Examples |
|-----------|----------|
| `soothe.subagent.*` | `explore.started`, `plan.completed`, `tacitus.gather` |
| `soothe.tool.*` | `file_ops.read`, `execution.run_command` |
| `soothe.mcp.*` | `server.connected`, `tool.invoke`, `resource.read` |

### Configuration

Capabilities are configured via `config.yml`:

```yaml
# Subagents
subagents:
  explore:
    enabled: true
    thoroughness: medium
  plan:
    enabled: true
    enable_explore: true
  tacitus:
    enabled: true
    domain: public

# MCP servers
mcp_servers:
  - name: filesystem
    transport: stdio
    command: ["mcp-server-filesystem", "--root", "/workspace"]
    defer: true
    enabled: true

# Plugins
plugins:
  - name: my-custom-plugin
    enabled: true
    module: "my_package:MyPlugin"
    config:
      api_key: "${MY_API_KEY}"
```

## Key RFCs

| RFC | Title | Purpose |
|-----|-------|---------|
| [RFC-600](../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System | Plugin API, decorators, discovery |
| [RFC-601](../specs/RFC-601-built-in-agents.md) | Built-in Plugin Agents | Built-in subagent architecture |
| [RFC-613](../specs/RFC-613-explore-agent-llm-orchestrated-search.md) | Explore Agent | LLM-orchestrated search |
| [RFC-618](../specs/RFC-618-plan-subagent-delegation.md) | Plan Subagent | Structured planning |
| [RFC-619](../specs/RFC-619-tacitus-subagent.md) | Tacitus Subagent | Public-domain research |
| [RFC-101](../specs/RFC-101-tool-interface.md) | Tool Interface | Single-purpose design pattern |
| [RFC-412](../specs/RFC-412-mcp-management.md) | MCP Management | MCP subsystem architecture |

## Quick Start

### Adding a Built-in Subagent

Built-in subagents are automatically registered when their package is imported:

```python
# Automatic registration via package __init__.py
from soothe.subagents import explore, plan, tacitus
```

### Creating a Custom Tool

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(name="analyze_data", description="Analyze CSV data")
    def analyze_data(self, file_path: str) -> dict:
        """Analyze CSV file and return statistics."""
        # Implementation
        return {"rows": 100, "columns": 5}
```

### Creating a Custom Subagent

```python
from soothe_sdk.plugin import plugin, subagent
from deepagents import create_react_agent

@plugin(name="my-agent", version="1.0.0")
class MyAgentPlugin:
    @subagent(name="analyzer", description="Data analysis agent")
    async def create_agent(self, model, config, context):
        # Create CompiledSubAgent
        agent = create_react_agent(model, tools=[...])
        return agent
```

### Using MCP Tools

MCP tools are surfaced progressively through `mcp_tool_search`:

```
# First turn: deferred tools listed in <AVAILABLE_MCP_TOOLS>
# Agent calls: mcp_tool_search("search files", limit=5)
# Tool promoted to always-available on subsequent turns
```

## Best Practices

1. **Check langchain ecosystem first** - Don't reinvent if langchain/deepagents already provides it
2. **Follow naming conventions** - `{verb}_{noun}` for tools, clear domain for subagents
3. **Register events properly** - Use `register_event()` for domain events
4. **Respect trust levels** - Use appropriate permissions for plugins
5. **Test thoroughly** - Run `./scripts/verify_finally.sh` after changes
6. **Document clearly** - Add docstrings, usage examples, and configuration notes

---

**Next**: [Subagents Architecture](subagents.md) | [Tools System](tools.md) | [MCP Integration](mcp.md) | [Extension Patterns](extension-patterns.md)
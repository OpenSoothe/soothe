# Subagents Architecture

**Subagents** are specialized autonomous agents that perform multi-step workflows with stateful execution. They extend Soothe's capabilities beyond simple tool invocations, enabling complex operations like filesystem exploration, structured planning, and deep research.

## Overview

### Subagent vs Tool

| Characteristic | Tool | Subagent |
|----------------|------|----------|
| **Operations** | Single-shot | Multi-step workflows |
| **State** | Stateless | Stateful execution |
| **Duration** | Immediate | Seconds to minutes |
| **Complexity** | Simple | Complex orchestration |
| **Results** | Direct output | Comprehensive reports |
| **LLM Calls** | Zero or one | Multiple (orchestrated) |
| **Dependencies** | None | May call other tools/subagents |

### Architecture Pattern

All subagents follow a consistent architecture pattern (RFC-600):

```
┌──────────────────────────────────────────────────────────────┐
│  Subagent Plugin                                             │
│  (@plugin + @subagent decorators)                            │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Implementation Factory                                      │
│  create_<name>_subagent(model, config, context)              │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Compiled LangGraph StateGraph                               │
│  - State schema (TypedDict)                                  │
│  - Nodes (LLM + tools)                                       │
│  - Flow control (conditionals, loops)                        │
│  - Output schema (structured result)                         │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  Events Package                                              │
│  - Domain-specific wire events                               │
│  - register_event() calls                                    │
│  - soothe.subagent.<name>.* namespace                        │
└──────────────────────────────────────────────────────────────┘
```

## Built-in Subagents

### 1. Explore (RFC-613)

**Purpose**: LLM-orchestrated iterative filesystem search

**Architecture**:
```
START → plan_search (LLM)
        ↓ Generate search action
       execute_action (tool)
        ↓ glob / grep / ls / read_file / file_info
       assess_results (LLM)
        ↓ Continue? Adjust? Finish?
        ├─ continue → execute_action
        ├─ adjust → plan_search (refined)
        └─ finish → synthesize → END
```

**Key Features**:
- **LLM as orchestrator**: Dynamically decides which tool to use based on findings
- **Configurable thoroughness**: `quick` (2 iterations), `medium` (4), `thorough` (6)
- **Read-only safety**: Never modifies filesystem
- **Tool reuse**: Uses deepagents' existing tools (no custom implementations)

**Configuration**:
```yaml
subagents:
  explore:
    enabled: true
    thoroughness: medium  # quick | medium | thorough
```

**Usage**:
```python
# Invoked via task tool
result = await task(
    subagent_type="explore",
    description="Find authentication module",
    inputs={"target": "auth.py", "thoroughness": "quick"}
)
```

**Wire Events**:
- `soothe.subagent.explore.started`
- `soothe.subagent.explore.iteration`
- `soothe.subagent.explore.completed`

### 2. Plan (RFC-618)

**Purpose**: Structured planning with optional explore delegation

**Architecture**:
```
START → ingest_task
       → [enable_explore?] collection_iteration ⟲  else → plan_iteration
       → plan_iteration ⟲
       → emit_final → END
```

**Key Features**:
- **Two-phase design**: Collection (explore calls) → Planning (markdown refinement)
- **Explicit explore integration**: Direct `invoke` on explore runnable (no nested task tool)
- **Agentic collection**: Multiple rounds, multiple explore tasks per round
- **Agentic plan design**: Multiple refinement rounds until model declares "done"
- **Bounded cost**: Configurable caps on rounds and total explore invocations

**Configuration**:
```yaml
subagents:
  plan:
    enabled: true
    enable_explore: true
    max_explore_passes: 24        # Total explore invocations
    max_collection_rounds: 6      # Collection LLM rounds
    max_explore_tasks_per_round: 8
    max_plan_rounds: 5            # Plan design rounds
```

**Usage**:
```python
# Invoked via task tool
plan = await task(
    subagent_type="plan",
    description="Plan module refactoring",
    inputs={"task": "Refactor authentication module"}
)
```

**Wire Events**:
- `soothe.subagent.plan.started`
- `soothe.subagent.plan.collection_round`
- `soothe.subagent.plan.plan_iteration`
- `soothe.subagent.plan.completed`

### 3. Tacitus (RFC-619)

**Purpose**: Public-domain research across web, academic papers, and URLs

**Architecture**:
```
analyze → generate_queries → gather → summarize → reflect
      ↑                                    │
      └──────── iterate ──────────────────┘
                      ↓ sufficient
                   synthesize → END
```

**Key Features**:
- **Public-only boundary**: Web search, Wikipedia, academic papers, URL crawling
- **Semantic routing**: Sentence-transformer similarity for source selection
- **Domain profiles**: `public` (all), `web`, `academic`
- **Fast-paths**: URL regex → include `url_crawl`, arXiv ID → boost `academic_search`

**Capabilities**:
| capability_id | Tooling | Purpose |
|---------------|---------|---------|
| `web_search` | `WizsearchSearchTool` | Multi-engine web search |
| `wikipedia` | `WikipediaQueryRun` | Encyclopedia/definitions |
| `academic_search` | `DeepxivSearchTool` | Semantic paper search |
| `url_crawl` | `WizsearchCrawlTool` | Extract content from URLs |

**Configuration**:
```yaml
subagents:
  tacitus:
    enabled: true
    domain: public  # public | web | academic
    max_loops: 3    # Reflection iterations
    effort: normal  # normal | high | xhigh
```

**Usage**:
```python
# Invoked via task tool
research = await task(
    subagent_type="tacitus",
    description="Research async patterns in Python",
    inputs={"topic": "Python asyncio patterns"}
)
```

**Wire Events**:
- `soothe.subagent.tacitus.started`
- `soothe.subagent.tacitus.gather.summary`
- `soothe.subagent.tacitus.completed`

### 4. Browser Use (Opt-in)

**Purpose**: Browser automation for web tasks

**Dependencies**: Included in base `soothe` dependencies

**Key Features**:
- Navigate pages, click elements, fill forms
- Extract content, take screenshots
- Web scraping and browser-based testing

**Configuration**:
```yaml
subagents:
  browser_use:
    enabled: true
```

**Usage**:
```python
# Invoked via task tool
result = await task(
    subagent_type="browser_use",
    description="Extract data from webpage",
    inputs={"url": "https://example.com/data"}
)
```

### 5. Claude (Opt-in)

**Purpose**: Claude Code agent for complex code analysis

**Dependencies**: Requires `soothe[claude]` extra

**Key Features**:
- Multi-file refactoring
- Sophisticated generation tasks
- Deep code analysis

**Configuration**:
```yaml
subagents:
  claude:
    enabled: true  # Requires claude extra
```

**Usage**:
```python
# Invoked via task tool
refactor = await task(
    subagent_type="claude",
    description="Refactor authentication module",
    inputs={"scope": "packages/auth"}
)
```

## Implementation Pattern

### Package Structure

Each subagent follows the module self-containment pattern (IG-047):

```
packages/soothe/src/soothe/subagents/<name>/
├── __init__.py           # Plugin definition + public API
├── events.py             # Wire events + register_event() calls
├── implementation.py     # Factory function
├── schemas.py            # State + output schemas
└── engine.py             # LangGraph StateGraph (if complex)
```

### Plugin Definition

```python
from soothe_sdk.plugin import plugin, subagent

@plugin(
    name="<name>",
    version="1.0.0",
    description="<description>",
    trust_level="built-in",
)
class <Name>Plugin:
    """Built-in <name> subagent plugin."""

    async def on_load(self, context):
        """Initialize plugin."""
        context.logger.info("Loaded <name> subagent v1.0.0")

    @subagent(
        name="<name>",
        description="<detailed description>",
        triggers=["keyword1", "keyword2"],  # Optional
        system_context="<special instructions>",  # Optional
    )
    async def create_subagent(self, model, config, context):
        """Create subagent runnable."""
        context_dict = {
            "work_dir": getattr(context, "work_dir", ""),
            # Additional context
        }
        return create_<name>_subagent(model, config, context_dict)
```

### State Schema

```python
from typing import Annotated
from typing_extensions import TypedDict

class <Name>State(TypedDict):
    """Subagent state schema."""
    messages: Annotated[list, add_messages]  # Required for CompiledSubAgent
    # Domain-specific fields
    workspace: str
    findings: list[dict]
    iterations_used: int
    max_iterations: int
    # Output fields
    result: dict | None
```

### Output Schema

```python
from pydantic import BaseModel

class <Name>Result(BaseModel):
    """Structured output."""
    target: str
    matches: list[MatchEntry]
    summary: str
    # Domain-specific fields
```

### Factory Function

```python
from langgraph.graph import StateGraph, END
from deepagents import CompiledSubAgent

def create_<name>_subagent(model, config, context):
    """Create <name> subagent runnable.

    Args:
        model: LLM for agent operations.
        config: SootheConfig instance.
        context: Plugin context dict.

    Returns:
        CompiledSubAgent runnable.
    """
    # Build StateGraph
    graph = StateGraph(<Name>State)
    
    # Add nodes
    graph.add_node("node1", node1_func)
    graph.add_node("node2", node2_func)
    
    # Add edges
    graph.add_edge("node1", "node2")
    graph.add_conditional_edges("node2", should_continue, {
        "continue": "node1",
        "finish": END
    })
    
    # Compile
    return graph.compile()
```

### Event Registration

```python
from soothe.foundation.events import register_event
from soothe.foundation.base_events import SootheEvent

class <Name>StartedEvent(SootheEvent):
    type: str = "soothe.subagent.<name>.started"
    target: str = ""

class <Name>CompletedEvent(SootheEvent):
    type: str = "soothe.subagent.<name>.completed"
    duration_ms: int = 0
    summary: str = ""

# Register at module load
register_event(<Name>StartedEvent, summary_template="<name> started: {target}")
register_event(<Name>CompletedEvent, summary_template="<name> completed in {duration_ms}ms")
```

## Integration Points

### Task Tool Invocation

Subagents are invoked via the `task` tool:

```python
# Main agent calls task tool
result = tool_runtime.task(
    subagent_type="<name>",
    description="<task description>",
    inputs={"field": "value"}
)
```

The task tool:
1. Resolves subagent via `resolve_subagents()` from PluginRegistry
2. Invokes the CompiledSubAgent runnable
3. Returns structured result to main agent

### Policy Integration

All subagent operations pass through PolicyProtocol:

```python
# Policy check before subagent execution
allowed = await policy.check(
    Permission("subagent", "invoke", "<name>")
)
if not allowed:
    raise PermissionError("Subagent <name> not permitted")
```

### Workspace Boundaries

Subagents inherit workspace boundaries:

```python
# Workspace security applied
workspace = resolve_workspace_for_tool_execution(
    runtime=tool_runtime,
    fallback=work_dir
)
# All operations scoped to workspace
```

### Model Role Resolution

Subagents use specific model roles:

| Subagent | Model Role | Config Override |
|----------|------------|-----------------|
| explore | `fast` | `subagents.explore.model` (ignored) |
| plan | `think` | `subagents.plan.model` (ignored) |
| tacitus | `fast` | `subagents.tacitus.model` (ignored) |

The router `think` role is always used for plan subagent primary model.

## Extension Pattern

### Creating a Custom Subagent

1. **Create package structure**:
```bash
mkdir -p packages/soothe/src/soothe/subagents/my_agent
```

2. **Define plugin** (`__init__.py`):
```python
from soothe_sdk.plugin import plugin, subagent

@plugin(name="my-agent", version="1.0.0")
class MyAgentPlugin:
    @subagent(name="my_agent", description="My custom agent")
    async def create_agent(self, model, config, context):
        return create_my_agent(model, config, context)
```

3. **Implement factory** (`implementation.py`):
```python
def create_my_agent(model, config, context):
    graph = StateGraph(MyAgentState)
    # Build graph...
    return graph.compile()
```

4. **Define schemas** (`schemas.py`):
```python
class MyAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    # Domain fields

class MyAgentResult(BaseModel):
    # Structured output
```

5. **Register events** (`events.py`):
```python
from soothe.foundation.events import register_event

class MyAgentStartedEvent(SootheEvent):
    type: str = "soothe.subagent.my_agent.started"

register_event(MyAgentStartedEvent)
```

6. **Run verification**:
```bash
./scripts/verify_finally.sh
```

### Best Practices

1. **Follow naming conventions**: `<name>` for subagent ID, `<Name>Plugin` for class
2. **Include messages in state**: Required for CompiledSubAgent contract
3. **Return structured output**: Use Pydantic models, not raw dicts
4. **Register events properly**: Module-level `register_event()` calls
5. **Document thoroughly**: Clear descriptions, usage examples
6. **Test comprehensively**: Unit tests for factory, nodes, output schema
7. **Check langchain first**: Don't reinvent if langchain/deepagents provides it

## Related RFCs

| RFC | Title | Key Sections |
|-----|-------|--------------|
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System | §1-5 (decorators, lifecycle) |
| [RFC-601](../../specs/RFC-601-built-in-agents.md) | Built-in Plugin Agents | §4 (Research architecture) |
| [RFC-613](../../specs/RFC-613-explore-agent-llm-orchestrated-search.md) | Explore Agent | §4-5 (architecture, specification) |
| [RFC-618](../../specs/RFC-618-plan-subagent-delegation.md) | Plan Subagent | §4 (architecture, configuration) |
| [RFC-619](../../specs/RFC-619-tacitus-subagent.md) | Tacitus Subagent | §4-5 (architecture, routing) |

## Troubleshooting

### Common Issues

1. **ImportError on subagent load**:
   - Check dependencies in plugin manifest
   - Verify required packages installed (`soothe`, and `soothe[claude]` when using claude)

2. **CompiledSubAgent contract violation**:
   - Ensure `messages: Annotated[list, add_messages]` in state
   - Return single `AIMessage` in final node

3. **Workspace boundary violation**:
   - Use `resolve_workspace_for_tool_execution()`
   - Apply `WorkspaceToolOperationSecurity` for file operations

4. **Event registration missing**:
   - Import events package in `__init__.py` (side-effect registration)
   - Check event namespace matches subagent ID

### Debugging Tips

```bash
# Enable debug logs
SOOTHE_LOG_LEVEL=DEBUG soothe -p "use explore subagent"

# Check subagent loading
grep -i "loaded.*subagent" ~/.soothe/logs/soothe.log

# Verify event registration
grep -i "register_event.*subagent" ~/.soothe/logs/soothe.log
```

---

**Previous**: [Capabilities Index](index.md) | **Next**: [Tools System](tools.md)
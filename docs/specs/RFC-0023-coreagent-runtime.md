# RFC-0023: Layer 1 - CoreAgent Runtime Architecture

**RFC**: 0023
**Title**: Layer 1: CoreAgent Runtime Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-29
**Dependencies**: RFC-0001, RFC-0002

## Abstract

This RFC defines Layer 1 of Soothe's three-layer execution architecture: the CoreAgent runtime built on `create_soothe_agent()` factory. CoreAgent provides a CompiledStateGraph with built-in tools, subagents, and middlewares, executing through LangGraph's Model → Tools → Model loop. It serves as the execution foundation for Layer 2's ACT phase and direct CLI/daemon usage.

## Architecture Position

### Three-Layer Model

```
Layer 3: Autonomous Goal Management (RFC-0007)
  └─ Delegates to Layer 2 (PERFORM stage)

Layer 2: Agentic Goal Execution (RFC-0008)
  └─ Delegates to Layer 1 (ACT phase) for step execution

Layer 1: CoreAgent Runtime (this RFC)
  ├─ Foundation: create_soothe_agent() → CompiledStateGraph
  ├─ Execution: Model → Tools → Model loop (LangGraph native)
  └─ Used by: Layer 2 ACT phase, CLI, daemon
```

### Layer 1 Responsibilities

Layer 1 provides the execution runtime for tool and subagent operations:

- **CoreAgent factory**: `create_soothe_agent()` creates CompiledStateGraph
- **Built-in capabilities**: Tools, subagents, MCP servers, middlewares
- **Execution engine**: LangGraph Model → Tools → Model loop
- **Thread management**: Sequential vs parallel execution with isolated threads
- **Middleware integration**: Context, memory, policy, planner, summarization
- **Protocol attachments**: Soothe protocol instances attached to graph
- **Layer 2 integration**: agent.astream() for ACT phase step execution

### Integration with Layer 2

**Layer 2 ACT → Layer 1**:

Layer 2's ACT phase invokes CoreAgent for step execution:

```python
# Sequential execution (one agent turn)
result = await core_agent.astream(
    input=build_input_from_steps(steps),
    config={"configurable": {"thread_id": tid}}
)

# Parallel execution (multiple agent turns with isolated threads)
results = await asyncio.gather(*[
    core_agent.astream(
        input=f"Execute: {step.description}",
        config={"configurable": {"thread_id": f"{tid}__step_{i}"}}
    )
    for i, step in enumerate(steps)
])
```

## CoreAgent Factory

### Factory Function

`create_soothe_agent()` creates Soothe's CoreAgent runtime:

```python
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """
    Factory that creates Soothe's CoreAgent runtime (Layer 1).

    Assembles:
    - Tools (execution, websearch, research, etc.)
    - Subagents (Browser, Claude, Skillify, Weaver)
    - MCP servers (loaded via configuration)
    - Middlewares (context, memory, policy, planner, summarization)
    - Protocol instances (attached to graph)

    Args:
        config: Soothe configuration

    Returns:
        CompiledStateGraph with attached protocol instances:
        - soothe_context: ContextProtocol instance
        - soothe_memory: MemoryProtocol instance
        - soothe_planner: PlannerProtocol instance
        - soothe_policy: PolicyProtocol instance
        - soothe_durability: DurabilityProtocol instance

    Example:
        config = SootheConfig.from_file("config.yml")
        agent = create_soothe_agent(config)
        stream = await agent.astream("query", config={"thread_id": "123"})
    """
```

### Factory Assembly

The factory assembles components in this order:

1. **Load configuration**: Resolve models, protocols, capabilities
2. **Instantiate protocols**: Context, Memory, Planner, Policy, Durability
3. **Resolve models**: Map roles to provider:model strings
4. **Assemble tools**: Built-in + configured tools
5. **Assemble subagents**: Browser, Claude, Skillify, Weaver
6. **Load MCP servers**: Via langchain-mcp-adapters
7. **Wire middlewares**: Soothe protocol middlewares + deepagents middlewares
8. **Call create_deep_agent()**: Assemble final graph
9. **Attach protocols**: Add protocol instances as graph attributes
10. **Return CompiledStateGraph**: Ready for execution

## Execution Interface

### Agent Stream API

CoreAgent provides streaming execution interface:

```python
agent.astream(
    input: str | dict,
    config: RunnableConfig
) → AsyncIterator[StreamChunk]
```

**Input**:
- `input`: User query or execution instruction (str or dict)
- `config`: LangGraph configuration

**Config Structure**:
```python
config = {
    "configurable": {
        "thread_id": str,  # Thread context for execution
        "recursion_limit": int,  # Max tool calls per turn (default: 25)
        # ... other LangGraph config
    }
}
```

**Output**:
- AsyncIterator yielding `StreamChunk` events
- Events include: messages, tool calls, custom events, tokens

### Execution Flow

```
agent.astream(input, config)
    |
    v
LangGraph CompiledStateGraph execution:
    |
    +-- Model turn:
    |      LLM processes input + context
    |      Decides tool calls
    |
    +-- Tool execution:
    |      Execute tools in parallel (tool_calls)
    |      Collect tool results
    |      Middlewares: policy check, context update, memory persist
    |
    +-- Model turn (second call):
    |      LLM processes tool results
    |      Decides more tools OR final response
    |
    +-- Stream output:
           Yield StreamChunk events (messages, tool calls, custom events)
```

### Example Usage

```python
# Basic usage
config = SootheConfig.from_file("config.yml")
agent = create_soothe_agent(config)

async for chunk in agent.astream(
    input="What files are in the src directory?",
    config={"configurable": {"thread_id": "thread-123"}}
):
    print(chunk)

# Layer 2 ACT phase usage
result = await agent.astream(
    input="Execute: Read config.json and validate schema",
    config={"configurable": {"thread_id": "thread-123__step-1"}}
)
```

## Thread Model

### Sequential Execution

Single thread context for sequential operations:

```python
# One agent turn, shared context
result = await agent.astream(
    input="Execute steps 1, 2, 3 sequentially",
    config={"configurable": {"thread_id": "tid"}}
)
```

**Characteristics**:
- Single thread context: `thread_id` maintained across agent turn
- Middlewares work per-thread: context isolation, memory persistence
- Tools/subagents share thread state
- Conversation history preserved

### Parallel Execution

Isolated thread contexts for parallel operations:

```python
# Multiple agent turns, isolated contexts
results = await asyncio.gather(*[
    agent.astream(
        input=f"Execute: {step.description}",
        config={"configurable": {"thread_id": f"{tid}__step_{i}"}}
    )
    for i, step in enumerate(steps)
])
```

**Characteristics**:
- Parent thread → child threads (`{parent}__step_{i}`)
- Each parallel execution gets independent agent context
- Results merged after parallel completion
- Thread isolation prevents context pollution

**Thread Naming Convention**:
- Parent: `thread-123`
- Parallel steps: `thread-123__step_0`, `thread-123__step_1`, `thread-123__step_2`
- Goals: `thread-123__goal_a1b2c3d4`

## Built-in Capabilities

### Tools

**Execution Tools** (RFC-0016):
- `execute`: Run shell commands
- `ls`, `read_file`, `write_file`, `edit_file`: File operations
- `glob`, `grep`: Search tools

**Websearch Tools**:
- `TavilySearchResults`: Tavily web search
- `DuckDuckGoSearchRun`: DuckDuckGo search

**Research Tools** (RFC-0021):
- `ArxivQueryRun`: ArXiv paper search
- `WikipediaQueryRun`: Wikipedia search
- `GitHubAPIWrapper`: GitHub operations

**Other Tools**:
- langchain ecosystem tools (Gmail, Python REPL, etc.)
- Custom tools via configuration

### Subagents

**Browser** (deepagents): Web browsing and automation
**Claude** (deepagents): Claude CLI integration
**Skillify** (RFC-0004): Skill discovery and execution
**Weaver** (RFC-0005): Code weaving and synthesis

### MCP Servers

**Loading**: Via langchain-mcp-adapters
**Configuration**: In `config.yml` under `mcp_servers`
**Exposure**: As tools through langchain tool interface

### Middlewares

**deepagents Middlewares**:
- `SummarizationMiddleware`: Auto-compaction for long conversations
- `PromptCachingMiddleware`: Cache frequent prompts
- `TodoListMiddleware`: Task tracking
- `FilesystemMiddleware`: File operations

**Soothe Protocol Middlewares** (wrapped):
- `ExecutionHintsMiddleware`: Process Layer 2 execution hints, inject into system prompt
- `ContextMiddleware`: Context injection and persistence
- `MemoryMiddleware`: Memory recall and persistence
- `PolicyMiddleware`: Policy checking for actions
- `PlannerMiddleware`: Planner protocol integration

## Protocol Attachments

Protocol instances are attached to the CompiledStateGraph for access during execution:

```python
agent = create_soothe_agent(config)

# Access protocol instances
context = agent.soothe_context  # ContextProtocol
memory = agent.soothe_memory    # MemoryProtocol
planner = agent.soothe_planner  # PlannerProtocol
policy = agent.soothe_policy    # PolicyProtocol
durability = agent.soothe_durability  # DurabilityProtocol
```

**Usage in Tools/Middlewares**:
```python
# In a tool
def my_tool(state: AgentState) -> str:
    context = state["agent"].soothe_context
    memory = state["agent"].soothe_memory
    # Use protocols
    ...
```

## Integration Contract

### Layer 2 Usage Pattern

Layer 2's ACT phase uses CoreAgent for step execution:

```python
# Layer 2 ACT phase
async def execute_step_via_agent(
    agent: CompiledStateGraph,
    step: StepAction,
    thread_id: str
) -> StepResult:
    """Execute single step through Layer 1 CoreAgent with hints."""

    # Build config with Layer 2 → Layer 1 hints (advisory)
    config = {
        "configurable": {
            "thread_id": thread_id,
            "soothe_step_tools": step.tools,           # Suggested tools
            "soothe_step_subagent": step.subagent,     # Suggested subagent
            "soothe_step_expected_output": step.expected_output,  # Expected result
        }
    }

    stream = await agent.astream(
        input=f"Execute: {step.description}",
        config=config  # Hints passed via config
    )
    # Collect evidence from stream
    result = await collect_stream_evidence(stream)
    return result
```

### Execution Hints

Layer 2's ACT phase passes advisory execution hints to Layer 1 CoreAgent via `config.configurable`:

| Hint Field | Purpose | Example |
|------------|---------|---------|
| `soothe_step_tools` | Suggested tools for execution | `["read_file", "grep"]` |
| `soothe_step_subagent` | Suggested subagent to invoke | `"browser"` |
| `soothe_step_expected_output` | Expected result description | `"File contents matching pattern"` |

**Hint Behavior**:
- **Advisory, not mandatory**: Layer 1 LLM considers hints but may choose different approach
- **ExecutionHintsMiddleware**: Injects hints into system prompt for LLM consideration
- **Natural integration**: LLM sees hints in decision-making context, decides final execution
- **Backward compatible**: Steps without hints work unchanged (middleware skips processing)

**Example Integration**:

```python
# Layer 2 Planner decision
decision = AgentDecision(
    steps=[
        StepAction(
            description="Find configuration files",
            tools=["glob", "grep"],
            expected_output="List of config files"
        )
    ],
    execution_mode="sequential"
)

# Executor passes hints to Layer 1
await core_agent.astream(
    input="Execute: Find configuration files",
    config={
        "configurable": {
            "thread_id": "thread-123",
            "soothe_step_tools": ["glob", "grep"],
            "soothe_step_expected_output": "List of config files"
        }
    }
)

# CoreAgent LLM receives enhanced system prompt:
# "You are Soothe agent...
#
# Execution hints: Suggested tools: glob, grep. Expected output: List of config files.
# Consider using the suggested approach first, but decide based on what works best."
#
# → LLM decides to use glob first, then grep for filtering
```

**Architecture Principle**: This integration honors the three-layer separation:
- Layer 2 controls **what to execute** (step content + tool/subagent suggestions)
- Layer 1 handles **how to execute** (runtime decisions with hints as context)

### Responsibilities Split

**Layer 2 Controls**:
- What to execute (step content)
- When to execute (iteration timing)
- How to sequence (parallel vs sequential vs dependency)
- Thread isolation strategy

**Layer 1 (CoreAgent) Handles**:
- How to execute (tool sequencing within agent turn)
- Middleware application (context, memory, policy)
- Thread state management
- Tool/subagent orchestration

## Architecture Role

### Foundation for Multiple Consumers

CoreAgent serves as foundation for:

1. **Layer 2 ACT phase**: Step execution in agentic loop
2. **CLI direct usage**: `soothe run "query"` without agentic loop
3. **Daemon queries**: HTTP/WebSocket/Unix socket requests
4. **Tool execution**: Subagent tool calls (deepagents `task` tool)

### Execution Model

```
User Request (via CLI/daemon/agent)
    ↓
CoreAgent.astream(input, thread_config)
    ↓
LangGraph Model → Tools → Model loop
    ↓
Middlewares: context, memory, policy, planner
    ↓
Tools/Subagents: execute operations
    ↓
Stream results back to caller
```

## Implementation

### File: `src/soothe/core/agent.py`

**Status**: ✅ Implemented

The `create_soothe_agent()` factory exists and assembles:
- Tools from `soothe.tools.*`
- Subagents from `soothe.subagents.*`
- MCP servers from configuration
- Middlewares from deepagents + Soothe protocols
- Protocol instances from `soothe.protocols.*`

**Implementation Notes**:
- Uses `create_deep_agent()` from deepagents
- Wires protocols as middleware
- Attaches protocol instances to returned graph
- Follows RFC-0001 Principle 2: "Extend deepagents, don't fork it"

## Configuration

```yaml
# CoreAgent capabilities configured in SootheConfig
providers:
  openai:
    api_key: ${OPENAI_API_KEY}

models:
  default: openai:gpt-4o
  fast: openai:gpt-4o-mini
  embedding: openai:text-embedding-3-small

tools:
  - execution
  - websearch
  - research

subagents:
  - browser
  - claude
  - skillify
  - weaver

mcp_servers:
  filesystem:
    command: mcp-filesystem
    args: ["/path/to/root"]
```

## Related Documents

- [RFC-0001](./RFC-0001-system-conceptual-design.md) - System Conceptual Design
- [RFC-0002](./RFC-0002-core-modules-architecture.md) - Core Modules Architecture
- [RFC-0007](./RFC-0007-autonomous-goal-management-loop.md) - Layer 3: Autonomous Goal Management
- [RFC-0008](./RFC-0008-agentic-goal-execution-loop.md) - Layer 2: Agentic Goal Execution
- [RFC-0004](./RFC-0004-skillify-agent-architecture.md) - Skillify Subagent
- [RFC-0005](./RFC-0005-weaver-agent-architecture.md) - Weaver Subagent
- [RFC-0016](./RFC-0016-tool-interface-optimization.md) - Tool Interface
- [RFC-0021](./RFC-0021-research-subagent.md) - Research Tools

## Changelog

### 2026-03-29
- Initial RFC establishing Layer 1 foundation
- Documented CoreAgent architecture based on existing implementation
- Defined three-layer positioning and Layer 2 integration
- Documented execution interface, thread model, built-in capabilities
- Specified protocol attachments and middleware integration
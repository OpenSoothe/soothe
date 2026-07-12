# RFC-100: CoreAgent Runtime Architecture

**RFC**: 100
**Title**: CoreAgent Runtime Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-29
**Updated**: 2026-05-26
**Dependencies**: RFC-000, RFC-001

## Abstract

This RFC defines CoreAgent, the foundational runtime of Soothe's execution architecture. Built on the `create_soothe_agent()` factory, CoreAgent provides a CompiledStateGraph with built-in tools, subagents, and middlewares, executing through LangGraph's Model → Tools → Model loop. It serves as the execution foundation for StrangeLoop's ACT phase and direct CLI/daemon usage.

## Architecture Position

### Three-Level Execution Model

```
GoalEngine: Autonomous Goal Management (RFC-200) → StrangeLoop (PERFORM stage)
StrangeLoop: Agentic Goal Execution (RFC-200) → CoreAgent (ACT phase)
CoreAgent: Runtime (this RFC) → Tools/Subagents
```

**CoreAgent Responsibilities**: CoreAgent factory (`create_soothe_agent()` → CompiledStateGraph), built-in capabilities (tools, subagents, MCP, middlewares), execution engine (LangGraph loop), thread management, middleware integration, protocol attachments, StrangeLoop integration.

### Level Integration

**StrangeLoop → CoreAgent**: Sequential execution `await core_agent.astream(input, config={"thread_id": tid})`, parallel execution `asyncio.gather([astream(step, thread_id=tid)])` (note: RFC-207 simplifies to single thread_id for all executions).

**CoreAgent Usage**: Foundation for StrangeLoop ACT phase, CLI direct usage, daemon queries, subagent tool calls.

## CoreAgent Factory

### Factory Function

```python
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """
    Factory that creates Soothe's CoreAgent runtime.

    Assembles: Tools, Subagents, MCP servers, Middlewares, Protocol instances.

    Returns:
        CompiledStateGraph with attached protocol instances:
        - soothe_context, soothe_memory, soothe_planner, soothe_policy, soothe_durability
    """
```

### Assembly Steps

1. Load configuration → resolve models, protocols, capabilities
2. Instantiate protocols → Context, Memory, Planner, Policy, Durability
3. Resolve models → Map roles to provider:model strings
4. Assemble tools/subagents → Built-in + configured
5. Load MCP servers → Via langchain-mcp-adapters
6. Wire middlewares → Soothe + deepagents
7. Call `create_deep_agent()` → Assemble graph
8. Attach protocols → Add instances as graph attributes

## Execution Interface

### Stream API

```python
agent.astream(input: str | dict, config: RunnableConfig) → AsyncIterator[StreamChunk]
```

**Config**: `{"configurable": {"thread_id": str, "recursion_limit": int}}`

**Output**: AsyncIterator yielding StreamChunk events (messages, tool calls, custom events, tokens).

### Execution Flow

```
agent.astream(input, config) → LangGraph execution:
  Model turn → LLM processes input, decides tool calls
  Tool execution → Execute tools, collect results, apply middlewares
  Model turn → LLM processes results, decides more tools or final response
  Stream output → Yield events
```

## Thread Model

### Sequential Execution

Single thread context: `astream(input, config={"thread_id": "tid"})`. Shared context, middlewares per-thread, tools/subagents share state.

### Parallel Execution

Concurrent execution: `asyncio.gather([astream(step, thread_id=tid) for step in steps])`. All steps use parent thread_id, langgraph handles concurrent message queue safely.

**Thread Naming** (RFC-207 simplified): Parent `thread-123`, goals `thread-123__goal_id` (for GoalEngine). No manual step thread suffixes.

## Built-in Capabilities

### Tools

**Execution** (RFC-101): `run_command`, `run_python`, `run_background`, `tail_background_log`, `kill_process` (host subprocess tools; deepagents `execute` is stripped).

**Filesystem** (deepagents middleware): `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`.

**Websearch**: `TavilySearchResults`, `DuckDuckGoSearchRun`.

**Research** (RFC-601): `ArxivQueryRun`, `WikipediaQueryRun`, `GitHubAPIWrapper`.

**Other**: langchain ecosystem tools, custom tools via configuration.

### Subagents

**Explore**, **Plan**, and **Research** ship in core Soothe. Optional delegated agents are published in **`soothe-plugins`** (install and configuration documented there).

**Skillify** (RFC-601): Skill discovery and execution.

**Weaver** (RFC-601): Code weaving and synthesis.

### MCP Servers

Loading via langchain-mcp-adapters, configuration in `config.yml`, exposed as tools.

### Middlewares

**deepagents**: `SummarizationMiddleware`, `PromptCachingMiddleware`, `TodoListMiddleware`, `FilesystemMiddleware`.

**Soothe Protocol** (wrapped): `ExecutionHintsMiddleware`, `ContextMiddleware`, `MemoryMiddleware`, `PolicyMiddleware`, `PlannerMiddleware`.

## Protocol Attachments

Protocol instances attached to CompiledStateGraph: `agent.soothe_context`, `agent.soothe_memory`, `agent.soothe_planner`, `agent.soothe_policy`, `agent.soothe_durability`.

**Usage**: Tools/middlewares access protocols via `state["agent"].soothe_*`.

## StrangeLoop Integration Contract

### Execution Hints

StrangeLoop passes advisory hints via `config.configurable`:

| Hint | Purpose | Example |
|------|---------|---------|
| `soothe_step_subagent` | Suggested subagent | `"explore"` |
| `soothe_step_expected_output` | Expected result | `"File contents matching pattern"` |

**Behavior**: Advisory (not mandatory), `ExecutionHintsMiddleware` injects into system prompt, LLM considers hints but decides final execution, backward compatible (steps without hints work unchanged).

**Example**:
```python
# StrangeLoop decision
decision = AgentDecision(
    steps=[StepAction(description="Find config files", subagent="explore", expected_output="Matching paths")]
)

# Executor passes hints (no per-step tool allowlist; CoreAgent keeps full tool surface)
await core_agent.astream(
    input="Execute: Find config files",
    config={
        "configurable": {
            "thread_id": "tid",
            "soothe_step_subagent": "explore",
            "soothe_step_expected_output": "Matching paths",
        }
    },
)
```

### Responsibility Split

**StrangeLoop Controls**: What to execute (step content), when to execute (timing), how to sequence (parallel/sequential/dependency), thread isolation.

**CoreAgent Handles**: How to execute (tool sequencing within turn), middleware application, thread state, tool/subagent orchestration.

## Implementation

**File**: `src/soothe/core/agent.py`

**Status**: ✅ Implemented

Factory assembles tools (`soothe.tools.*`), subagents (`soothe.subagents.*`), MCP servers, middlewares, protocols (`soothe.protocols.*`). Uses `create_deep_agent()` from deepagents, wires protocols as middleware, attaches instances to graph. Follows RFC-000 Principle 2: "Extend deepagents, don't fork it".

## Configuration

```yaml
providers:
  openai:
    api_key: ${OPENAI_API_KEY}

models:
  default: openai:gpt-4o
  fast: openai:gpt-4o-mini

tools: [execution, websearch, research]
subagents: [explore, plan, research]

mcp_servers:
  filesystem:
    command: mcp-filesystem
    args: ["/path/to/root"]
```

## Changelog

### 2026-03-29
- Initial RFC establishing CoreAgent foundation
- Documented CoreAgent architecture, execution interface, thread model, capabilities
- Specified protocol attachments and StrangeLoop integration with execution hints

## References

- RFC-000: System conceptual design
- RFC-001: Core modules architecture
- RFC-200: GoalEngine autonomous goal management
- RFC-200: StrangeLoop agentic goal execution
- RFC-601: Skillify subagent
- RFC-601: Weaver subagent
- RFC-101: Tool interface
- RFC-601: Research tools

---

*CoreAgent runtime providing execution foundation through LangGraph Model → Tools → Model loop.*
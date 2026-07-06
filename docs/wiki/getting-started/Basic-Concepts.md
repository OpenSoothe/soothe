---
title: "Basic Concepts"
parent: Getting Started
grand_parent: Wiki
nav_order: 3
description: Understand the core concepts and architecture behind Soothe's autonomous agent framework.
---

# Basic Concepts

Understand the core concepts and architecture behind Soothe's autonomous agent framework.

---

## Overview

Soothe is a **goal-driven orchestration framework** for building 24/7 long-running autonomous agents. It extends LangChain/DeepAgents with planning, context engineering, security policy, durability, and remote agent interoperability.

### Key Capabilities

- **Autonomous Execution**: Multi-step task completion without human intervention
- **Persistent Memory**: Context maintained across sessions
- **Goal Management**: Complex goals decomposed into manageable steps
- **Protocol-First Design**: Pluggable backends for all core functions
- **Security**: Least-privilege execution with fine-grained policies

---

## Core Architecture

### Three-Level Execution Model

Soothe uses a hierarchical execution model:

```
┌─────────────────────────────────────────────────────────────┐
│ ContextEngine: Autonomous Goal Management                  │
│ • Manages goal DAGs (directed acyclic graphs)             │
│ • Delegates single goals to StrangeLoop                     │
│ • Loop: Goal → PLAN → PERFORM → REFLECT → Update          │
└─────────────────────────────────────────────────────────────┘
                          ↓ PERFORM (full delegation)
┌─────────────────────────────────────────────────────────────┐
│ StrangeLoop: Agentic Goal Execution                          │
│ • Executes single goals through Plan → Execute iterations │
│ • Maximum ~8 iterations per goal                           │
│ • Adapts plans based on results                           │
└─────────────────────────────────────────────────────────────┘
                          ↓ EXECUTE (step execution)
┌─────────────────────────────────────────────────────────────┐
│ CoreAgent: Runtime Foundation                              │
│ • Model → Tools → Model loop (LangGraph native)           │
│ • Tool execution and result processing                     │
│ • Foundation: create_soothe_agent() → CompiledStateGraph  │
└─────────────────────────────────────────────────────────────┘
```

**Key Insight**: Each level delegates to the level below it, enabling autonomous behavior while maintaining control.

### Component Overview

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| **ContextEngine** | Autonomous goal management | Goal DAGs, inter-goal coordination, reflection |
| **StrangeLoop** | Single goal execution | Plan-adapt-execute cycles, step management |
| **CoreAgent** | Foundation runtime | LangGraph agent, tool execution, memory |

---

## Goals and Threads

### What is a Goal?

A **goal** is a user-defined objective that Soothe works to accomplish. Goals can be:

- **Simple**: "List all Python files in this directory"
- **Complex**: "Refactor the authentication system to support OAuth2"
- **Multi-step**: "Research best practices for API rate limiting and implement them"

### Goal Lifecycle

```
User Query → Parse → Plan → Execute → Reflect → Complete
                ↑                      ↓
                └────── Adapt ─────────┘
```

1. **Parse**: Understand user intent
2. **Plan**: Decompose into actionable steps
3. **Execute**: Run tools and subagents
4. **Reflect**: Evaluate progress
5. **Adapt**: Adjust plan if needed
6. **Complete**: Mark goal as done

### What is a Thread?

A **thread** is a conversation context that maintains:

- Message history
- Goal state
- Memory and context
- Subagent interactions

**Thread Benefits:**
- Resume previous conversations
- Maintain long-running context
- Track goal progress over time
- Enable multi-turn interactions

### Thread Management

```bash
# List recent threads
soothe loop list

# Continue a thread
soothe loop continue <thread-id>

# Delete a thread
soothe loop delete <thread-id>
```

---

## Subagents

### What are Subagents?

**Subagents** are specialized agents that handle specific types of tasks. Soothe automatically delegates work to the appropriate subagent.

### Built-in Subagents

| Subagent | Purpose | When Used |
|----------|---------|-----------|
| **Explore** | Filesystem search and analysis | Finding files, exploring codebases |
| **Plan** | Task planning and decomposition | Complex multi-step tasks |
| **Tacitus** | Academic research | Finding papers, literature reviews |
| **Browser Use** | Web automation | Interacting with websites |
| **Veritas** | Research synthesis and verification | Fact-checking, validation |

> **Note**: Community subagents (e.g. `weaver`) are available via the
> `soothe-plugins` package, not as core subagents.

### Subagent Workflow

```
User Query
    ↓
CoreAgent analyzes task
    ↓
Delegates to specialized subagent
    ↓
Subagent executes with focused capabilities
    ↓
Returns results to CoreAgent
    ↓
CoreAgent synthesizes and responds
```

### Example

```
User: "Find all TODO comments in the codebase and prioritize them"

Soothe:
  1. Delegates to Explore subagent to search files
  2. Explore returns 23 TODO comments
  3. CoreAgent analyzes and prioritizes
  4. Returns prioritized list to user
```

---

## Tools

### What are Tools?

**Tools** are individual functions that agents can call to perform specific actions:

- File operations (read, write, edit)
- Shell commands
- Web search
- Code execution
- Data analysis

### Tool Categories

| Category | Tools |
|----------|-------|
| **Filesystem** | `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep` |
| **Execution** | `run_command`, `run_python`, `run_background` |
| **Web** | `wizsearch_search`, `wizsearch_crawl`, `requests_get` |
| **Documents** | `extract_text`, `inspect_data`, `summarize_data` |
| **Media** | `analyze_image`, `transcribe_audio`, `analyze_video` |
| **Research** | `deepxiv_search`, `deepxiv_paper_brief` |
| **Task Management** | `write_todos`, `task` (subagent spawning) |

### Tool Execution

```
Agent decides to use a tool
    ↓
Security policy checks permissions
    ↓
Tool executes in sandboxed environment
    ↓
Result returned to agent
    ↓
Agent processes result and continues
```

---

## Memory and Context

### Memory System

Soothe maintains different types of memory:

| Memory Type | Purpose | Persistence |
|-------------|---------|-------------|
| **Conversation** | Message history | Thread lifetime |
| **Episodic** | Past interactions | Cross-session |
| **Semantic** | Knowledge vectors | Long-term |
| **Working** | Current task context | Goal lifetime |

### Context Management

**Context** provides relevant information to the agent:

- File contents from workspace
- Previous conversation history
- Relevant memories
- Subagent results

### Context Protocols

Soothe supports pluggable context backends:

- **KeywordContext**: Simple keyword-based retrieval
- **VectorContext**: Semantic search with embeddings
- **Custom**: User-defined context providers

---

## Protocols and Backends

### Protocol-First Design

Soothe defines **protocols** (interfaces) for all core functions, with pluggable **backends** (implementations).

### Core Protocols

| Protocol | Purpose | Implementations |
|----------|---------|-----------------|
| **ContextProtocol** | Information retrieval | KeywordContext, VectorContext |
| **MemoryProtocol** | Persistent memory | KeywordMemory, VectorMemory |
| **PlannerProtocol** | Task planning | SimplePlanner, SubagentPlanner, AutoPlanner |
| **PolicyProtocol** | Security policies | ConfigDrivenPolicy |
| **DurabilityProtocol** | State persistence | JsonDurability, RocksDBDurability |
| **VectorStoreProtocol** | Vector storage | PGVector, Weaviate, InMemory |

### Configuring Backends

```yaml
# ~/.soothe/config/config.yml

# Context backend
context:
  backend: vector  # or: keyword
  vector_store:
    type: pgvector
    connection_string: "${DATABASE_URL}"

# Memory backend
memory:
  backend: vector  # or: keyword

# Durability backend
durability:
  backend: rocksdb  # or: json, postgres
  path: ~/.soothe/state

# Planner backend
planner:
  type: auto  # or: simple, subagent, model-specific
```

---

## Security Model

### Least-Privilege Execution

Soothe operates with **least privilege** by default:

- **Sandboxed execution**: Tools run in isolated environments
- **Policy-based permissions**: Fine-grained access control
- **Workspace restrictions**: Limited to specified directories
- **Network policies**: Controlled internet access

### Security Policies

Configure what actions Soothe can perform:

```yaml
# ~/.soothe/config/config.yml

policy:
  # Filesystem access
  filesystem:
    allowed_paths:
      - "."
      - "~/projects"
    denied_paths:
      - "~/.ssh"
      - "~/.gnupg"
  
  # Network access
  network:
    allowed_domains:
      - "api.openai.com"
      - "github.com"
    deny_all: false
  
  # Shell commands
  shell:
    allowed_commands:
      - "git"
      - "npm"
      - "python"
    deny_all: false
```

### Security Layers

```
User Request
    ↓
Policy Check (can agent do this?)
    ↓
Workspace Check (is path allowed?)
    ↓
Sandboxed Execution
    ↓
Result Filtering
    ↓
Return to Agent
```

---

## Daemon Architecture

### What is the Daemon?

The **daemon** is a long-running background process that:

- Manages agent instances
- Provides WebSocket and HTTP APIs
- Maintains thread persistence
- Handles resource management

### Daemon Benefits

| Feature | Benefit |
|---------|---------|
| **Background Processing** | Run long tasks without keeping terminal open |
| **Remote Access** | Connect from other applications via API |
| **Thread Persistence** | Resume conversations across sessions |
| **Resource Sharing** | Efficient memory and connection pooling |

### Daemon Transports

| Transport | Use Case | Performance |
|-----------|----------|-------------|
| **WebSocket** | CLI, TUI, browser clients, remote access | Good |

### Daemon Management

```bash
# Start daemon
soothed start

# Check status
soothed status

# View logs
soothed logs --follow

# Stop daemon
soothed stop

# Restart daemon
soothed restart
```

---

## Event System

### What are Events?

**Events** are real-time notifications about agent activities:

- Task progress
- Subagent actions
- Tool executions
- State changes

### Event Flow

```
Agent Activity
    ↓
Event Emitted
    ↓
Event Queue
    ↓
Listeners Notified
    ↓
UI Updates / Logging / Actions
```

### Event Types

| Event Type | Description |
|------------|-------------|
| `task.started` | Task begins execution |
| `task.progress` | Progress update |
| `task.completed` | Task finished successfully |
| `task.failed` | Task failed |
| `subagent.spawned` | Subagent created |
| `subagent.completed` | Subagent finished |
| `tool.called` | Tool invoked |
| `tool.result` | Tool returned result |

---

## Planning and Execution

### Plan-Driven Execution

Soothe uses **plan-driven execution** for complex tasks:

```
1. Decompose goal into steps
2. Create execution plan
3. Execute steps sequentially
4. Evaluate results
5. Adapt plan if needed
6. Continue or complete
```

### Planning Strategies

| Strategy | When Used | Description |
|----------|-----------|-------------|
| **Simple** | Direct tasks | Quick decomposition |
| **Subagent** | Complex tasks | Dedicated planning subagent |
| **Auto** | Mixed complexity | Automatic selection |

### Execution Loops

**StrangeLoop** manages execution with bounded iterations:

```python
# Maximum ~8 iterations
for iteration in range(max_iterations):
    # 1. Plan next step
    step = planner.plan(current_state)
    
    # 2. Execute step
    result = executor.execute(step)
    
    # 3. Evaluate progress
    if is_complete(result):
        break
    
    # 4. Adapt plan
    current_state = adapt(current_state, result)
```

---

## Configuration Hierarchy

### Configuration Sources

Soothe loads configuration from multiple sources (in priority order):

1. **CLI Arguments**: `--config`, `--debug`, etc.
2. **Environment Variables**: `SOOTHE_*` prefixed
3. **Config File**: `~/.soothe/config/config.yml` (default)
4. **Built-in Defaults**: Hardcoded sensible defaults

### Example Configuration

```yaml
# ~/.soothe/config/config.yml

# Providers (LLM backends)
providers:
  - name: openai
    provider_type: openai
    api_key: "${OPENAI_API_KEY}"
    models:
      - gpt-4o-mini
      - gpt-4o
      - o3-mini

# Model routing by purpose
router:
  default: "openai:gpt-4o-mini"  # General tasks
  think: "openai:o3-mini"         # Complex reasoning
  fast: "openai:gpt-4o-mini"       # Quick tasks
  embedding: "openai:text-embedding-3-small"

# Workspace settings
filesystem_middleware:
  workspace_root: "."

observability:
  verbosity: normal

# Subagents (core defaults; optional from soothe-plugins)
subagents:
  plan:
    enabled: true
  tacitus:
    enabled: true
  browser_use:
    enabled: true
```

---

## Putting It All Together

### Example Workflow

Here's how all concepts work together:

```
User: "Refactor the authentication module to support OAuth2"
    ↓
1. CoreAgent receives query
2. ContextEngine creates goal with subtasks
3. StrangeLoop plans execution steps
    ↓
Step 1: Explore codebase for auth module
    ↓
    Explore Subagent searches files
    ↓
Step 2: Research OAuth2 best practices
    ↓
    Tacitus Subagent finds papers
    ↓
Step 3: Create implementation plan
    ↓
    Plan Subagent decomposes work
    ↓
Step 4: Implement changes
    ↓
    Tools: read_file, edit_file, run_command
    ↓
Step 5: Test implementation
    ↓
    Tools: run_command (pytest)
    ↓
ContextEngine reflects on results
    ↓
Returns completed refactoring
```

---

## Next Steps

Now that you understand the basics:

1. **[Configuration Guide](../configuration.md)** - Customize Soothe for your needs
2. **[Autonomous Mode](../autonomous-mode.md)** - Enable autonomous execution
3. **[Architecture Overview](../architecture/index.md)** - Deep dive into design
4. **[RFC Specifications](../../specs/)** - Technical specifications

---

## Further Reading

- **[RFC-000: System Conceptual Design](../../specs/RFC-000-system-conceptual-design.md)** - Complete architecture
- **[RFC-200: Autonomous Goal Management](../../specs/archive/RFC-200-autonomous-goal-management.md)** - ContextEngine details (archived)
- **[RFC-201: StrangeLoop](../../specs/RFC-201-strangeloop-plan-execute-loop.md)** - Execution loop details
- **[Architecture Overview](../architecture/index.md)** - Visual guides and explanations
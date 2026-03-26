# RFC Namings

This document defines the terminology and naming conventions used in this project.

## Core Terminology

### Domain Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Orchestrator | The Soothe agent instance created by `create_soothe_agent()`. Wires together all protocols and delegates to deepagents. | RFC-0001 |
| Thread | One continuous agent conversation/execution. Has a unique ID, persistable state, and metadata. | RFC-0001 |
| Delegation | Routing work to a subagent (local or remote) via deepagents' `task` tool. | RFC-0001 |
| Context Ledger | The orchestrator's unbounded, append-only accumulation of `ContextEntry` items. Distinct from conversation history. | RFC-0001, RFC-0002 |
| Context Projection | A bounded, purpose-scoped view of the context ledger, assembled to fit within a token budget. | RFC-0001, RFC-0002 |
| Long-Term Memory | Cross-thread persistent knowledge managed by `MemoryProtocol`. Explicitly populated, semantically queryable. | RFC-0001, RFC-0002 |
| Plan / Step | A structured decomposition of a goal. Steps have execution hints and statuses. | RFC-0001, RFC-0002 |
| Policy Profile | A named configuration of permitted actions (e.g., `readonly`, `standard`, `privileged`). | RFC-0001, RFC-0002 |
| Permission Set | A collection of structured `Permission` objects with scope-aware matching logic. | RFC-0001, RFC-0002 |
| Concurrency Policy | Configuration controlling parallel execution limits for steps, subagents, and tools. | RFC-0001, RFC-0002 |

### Technical Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Protocol | A Python `Protocol` or abstract base class defining a runtime-agnostic interface. NOT a network protocol. | RFC-0001 |
| `ContextProtocol` | Protocol for cognitive context accumulation and projection. | RFC-0002 |
| `ContextEntry` | A unit of knowledge in the context ledger (source, content, timestamp, tags, importance). | RFC-0002 |
| `ContextProjection` | A bounded view of the context ledger for a specific purpose (entries, summary, token count). | RFC-0002 |
| `MemoryProtocol` | Protocol for cross-thread long-term memory (remember, recall, forget). | RFC-0002 |
| `MemoryItem` | A unit of long-term knowledge (id, content, tags, importance, metadata). | RFC-0002 |
| `PlannerProtocol` | Protocol for goal decomposition, plan creation, reflection, and revision. | RFC-0002 |
| `DirectPlanner` | Simple planner using single LLM call with structured output. For routine tasks. | RFC-0002 |
| `SubagentPlanner` | Complex planner using a dedicated subagent for multi-turn reasoning. | RFC-0002 |
| `PolicyProtocol` | Protocol for permission checking and enforcement. | RFC-0002 |
| `Permission` | A structured permission with category, action, and scope (e.g., `Permission("shell", "execute", "!rm")`). | RFC-0002 |
| `PolicyMiddleware` | deepagents `AgentMiddleware` that enforces `PolicyProtocol`. | RFC-0002 |
| `ContextMiddleware` | deepagents `AgentMiddleware` that manages `ContextProtocol` integration. | RFC-0002 |
| `DurabilityProtocol` | Protocol for thread lifecycle management and state persistence. | RFC-0002 |
| `ThreadInfo` | Data model for thread state (id, status, timestamps, metadata). | RFC-0002 |
| `RemoteAgentProtocol` | Protocol for invoking remote agents (ACP, A2A, LangGraph). | RFC-0002 |
| `ConcurrencyPolicy` | Data model controlling parallel execution of steps, subagents, and tools. | RFC-0002 |
| `StepResult` | Data model for a completed plan step's output and status. | RFC-0002 |

### Progress Event Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Progress Event | A `soothe.*` custom event dict emitted via the LangGraph stream for protocol observability. Follows the 4-segment naming convention `soothe.<domain>.<component>.<action>`. | RFC-0015 |
| Event Domain | The second segment of a progress event type string. One of: `lifecycle`, `protocol`, `tool`, `subagent`, `output`, `error`. Enables structural classification without heuristics. | RFC-0015 |
| `SootheEvent` | Pydantic `BaseModel` base class for all typed progress events. Subclassed by domain base classes (`LifecycleEvent`, `ProtocolEvent`, `ToolEvent`, `SubagentEvent`, `OutputEvent`, `ErrorEvent`). | RFC-0015 |
| `EventRegistry` | Central registry mapping event type strings to `EventMeta` (model, domain, verbosity, summary template) and handler callables. Provides O(1) dispatch. | RFC-0015 |
| `EventRenderer` | Protocol for rendering progress events. Implementations: `CliEventRenderer` (stderr text), `TuiEventRenderer` (Rich Text), `JsonlEventRenderer` (passthrough). | RFC-0015 |
| `EventMeta` | Frozen dataclass holding metadata for a registered event type: type string, model class, domain, component, action, verbosity category, and summary template. | RFC-0015 |

### Tool Interface Terms (RFC-0016)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Single-Purpose Tool | A tool that performs exactly one operation with direct naming (e.g., `run_command`, `read_file`). Replaces unified dispatch tools for better LLM tool selection. | RFC-0016 |
| Unified Dispatch Tool | DEPRECATED pattern. A tool that routes to multiple operations via mode/action parameters (e.g., `execute(mode="shell")`). Replaced by single-purpose tools due to cognitive load. | RFC-0016 |
| Surgical Editing | Line-based file modification using tools like `edit_file_lines`, `insert_lines`, `delete_lines`. Safer than full-file rewrites. | RFC-0016 |
| Python Session | Persistent IPython InteractiveShell instance keyed by thread_id. Enables variable persistence across `run_python` calls. | RFC-0016 |
| Session Manager | Singleton managing Python sessions with thread_id isolation, cleanup, and thread-safe execution. | RFC-0016 |
| Structured Error | Error response with standardized format: error, details, suggestions, recoverable, auto_retry_hint. Provides actionable guidance for LLM recovery. | RFC-0016 |

## Naming Conventions

### General Principles

1. **Clarity over brevity**: Prefer descriptive names
2. **Consistency**: Use the same term for the same concept throughout
3. **Domain language**: Use terms from the problem domain
4. **Protocol suffix**: All Soothe protocol interfaces end with `Protocol` (e.g., `ContextProtocol`)
5. **Middleware suffix**: All deepagents middleware implementations end with `Middleware` (e.g., `PolicyMiddleware`)

### Code Naming

| Convention | Pattern | Example |
|-----------|---------|---------|
| Protocol classes | `{Name}Protocol` | `ContextProtocol`, `PolicyProtocol` |
| Middleware classes | `{Name}Middleware` | `ContextMiddleware`, `PolicyMiddleware` |
| Data models | PascalCase, no suffix | `ContextEntry`, `Plan`, `Permission` |
| Config fields | snake_case | `planner_routing`, `policy_profiles` |
| Module directories | snake_case | `src/soothe/protocols/`, `src/soothe/middleware/` |

## Related Documents

- [RFC Standard](./rfc-standard.md) - Specification kinds
- [RFC Index](./rfc-index.md) - All RFCs

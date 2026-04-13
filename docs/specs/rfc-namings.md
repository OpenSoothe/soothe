# RFC Namings

This document defines the terminology and naming conventions used in this project.

## Core Terminology

### Domain Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Orchestrator | The Soothe agent instance created by `create_soothe_agent()`. Wires together all protocols and delegates to deepagents. | RFC-000 |
| Thread | One continuous agent conversation/execution. Has a unique ID, persistable state, and metadata. | RFC-000 |
| Delegation | Routing work to a subagent (local or remote) via deepagents' `task` tool. | RFC-000 |
| Parallel Delegation | Routing work to multiple subagents concurrently via multiple `task` tool calls in a single CoreAgent turn. Each subagent gets isolated thread branch automatically. | RFC-605 |
| Explore Subagent | Specialized subagent for targeted filesystem searches using wave-based strategy (list → glob → grep), LLM-driven search planning, and match validation with relevance ranking. | RFC-605 |
| Search Wave | Progressive search depth in explore subagent: Wave 1 (directory listing), Wave 2 (glob patterns), Wave 3 (content search). Minimizes expensive operations. | RFC-605 |
| Search Strategy | LLM-generated plan for filesystem search including priority directories, file patterns, content keywords, and search type classification. | RFC-605 |
| Match Validation | LLM assessment of found candidates against search target, ranking by relevance ("high", "medium", "low") and returning top 3-5 matches with brief descriptions. | RFC-605 |
| Context Ledger | The orchestrator's unbounded, append-only accumulation of `ContextEntry` items. Distinct from conversation history. | RFC-000, RFC-001 |
| Context Projection | A bounded, purpose-scoped view of the context ledger, assembled to fit within a token budget. | RFC-000, RFC-001 |
| Long-Term Memory | Cross-thread persistent knowledge managed by `MemoryProtocol`. Explicitly populated, semantically queryable. | RFC-000, RFC-001 |
| Plan / Step | A structured decomposition of a goal. Steps have execution hints and statuses. | RFC-000, RFC-001 |
| Policy Profile | A named configuration of permitted actions (e.g., `readonly`, `standard`, `privileged`). | RFC-000, RFC-001 |
| Permission Set | A collection of structured `Permission` objects with scope-aware matching logic. | RFC-000, RFC-001 |
| Concurrency Policy | Configuration controlling parallel execution limits for steps, subagents, and tools. | RFC-000, RFC-001 |

### Technical Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Protocol | A Python `Protocol` or abstract base class defining a runtime-agnostic interface. NOT a network protocol. | RFC-000 |
| `ContextProtocol` | Protocol for cognitive context accumulation and projection. | RFC-001 |
| `ContextEntry` | A unit of knowledge in the context ledger (source, content, timestamp, tags, importance). | RFC-001 |
| `ContextProjection` | A bounded view of the context ledger for a specific purpose (entries, summary, token count). | RFC-001 |
| `MemoryProtocol` | Protocol for cross-thread long-term memory (remember, recall, forget). | RFC-001 |
| `MemoryItem` | A unit of long-term knowledge (id, content, tags, importance, metadata). | RFC-001 |
| `PlannerProtocol` | Protocol for goal decomposition, plan creation, reflection, and revision. | RFC-001 |
| `LLMPlanner` | Unified planner using two-phase architecture (StatusAssessment + PlanGeneration) for token efficiency. Replaces SimplePlanner, ClaudePlanner, AutoPlanner after IG-150 consolidation. | RFC-001, RFC-604 |
| `PolicyProtocol` | Protocol for permission checking and enforcement. | RFC-001 |
| `Permission` | A structured permission with category, action, and scope (e.g., `Permission("shell", "execute", "!rm")`). | RFC-001 |
| `PolicyMiddleware` | deepagents `AgentMiddleware` that enforces `PolicyProtocol`. | RFC-001 |
| `ContextMiddleware` | deepagents `AgentMiddleware` that manages `ContextProtocol` integration. | RFC-001 |
| `DurabilityProtocol` | Protocol for thread lifecycle management and state persistence. | RFC-001 |
| `ThreadInfo` | Data model for thread state (id, status, timestamps, metadata). | RFC-001 |
| `RemoteAgentProtocol` | Protocol for invoking remote agents (ACP, A2A, LangGraph). | RFC-001 |
| `ConcurrencyPolicy` | Data model controlling parallel execution of steps, subagents, and tools. | RFC-001 |
| `StepResult` | Data model for a completed plan step's output and status. | RFC-001 |

### Progress Event Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Progress Event | A `soothe.*` custom event dict emitted via the LangGraph stream for protocol observability. Follows the 4-segment naming convention `soothe.<domain>.<component>.<action>`. | RFC-401 |
| Event Domain | The second segment of a progress event type string. One of: `lifecycle`, `protocol`, `tool`, `subagent`, `output`, `error`. Enables structural classification without heuristics. | RFC-401 |
| `SootheEvent` | Pydantic `BaseModel` base class for all typed progress events. Subclassed by domain base classes (`LifecycleEvent`, `ProtocolEvent`, `ToolEvent`, `SubagentEvent`, `OutputEvent`, `ErrorEvent`). | RFC-401 |
| `EventRegistry` | Central registry mapping event type strings to `EventMeta` (model, domain, verbosity, summary template) and handler callables. Provides O(1) dispatch. | RFC-401 |
| `EventRenderer` | Protocol for rendering progress events. Implementations: `CliEventRenderer` (stderr text), `TuiEventRenderer` (Rich Text), `JsonlEventRenderer` (passthrough). | RFC-401 |
| `EventMeta` | Frozen dataclass holding metadata for a registered event type: type string, model class, domain, component, action, verbosity category, and summary template. | RFC-401 |

### Tool Interface Terms (RFC-101)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Single-Purpose Tool | A tool that performs exactly one operation with direct naming (e.g., `run_command`, `read_file`). Replaces unified dispatch tools for better LLM tool selection. | RFC-101 |
| Unified Dispatch Tool | DEPRECATED pattern. A tool that routes to multiple operations via mode/action parameters (e.g., `execute(mode="shell")`). Replaced by single-purpose tools due to cognitive load. | RFC-101 |
| Surgical Editing | Line-based file modification using tools like `edit_file_lines`, `insert_lines`, `delete_lines`. Safer than full-file rewrites. | RFC-101 |
| Python Session | Persistent IPython InteractiveShell instance keyed by thread_id. Enables variable persistence across `run_python` calls. | RFC-101 |
| Session Manager | Singleton managing Python sessions with thread_id isolation, cleanup, and thread-safe execution. | RFC-101 |
| Structured Error | Error response with standardized format: error, details, suggestions, recoverable, auto_retry_hint. Provides actionable guidance for LLM recovery. | RFC-101 |

### Autopilot Terms (RFC-204)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Autopilot Mode | Layer 3 extension enabling long-running autonomous operation with dreaming mode and continuous improvement. | RFC-204 |
| Dreaming Mode | Persistent idle state where Soothe performs memory consolidation, indexing, goal anticipation, and health monitoring. | RFC-204 |
| Consensus Loop | Layer 3 validation of Layer 2 completion judgment with send-back capability and budget. | RFC-204 |
| Send-Back Budget | Per-goal limit on Layer 3 rejections (default: 3 rounds). Independent from Layer 2 iteration budget. | RFC-204 |
| Channel Protocol | Message-centric protocol for user ↔ Soothe communication. Generic routing by type prefix. | RFC-204 |
| ChannelMessage | Data structure with type, payload, timestamp, sender fields for channel communication. | RFC-204 |
| CriticalityEvaluator | Module in GoalEngine that determines if a proposed goal requires user confirmation (MUST status). | RFC-204 |
| SchedulerService | Independent service in `cognition/scheduler/` for time-based task execution (delay, cron, recurrence). | RFC-204 |
| Goal Relationship | Connection between goals: `depends_on` (hard), `informs` (soft), `conflicts_with` (mutual exclusion). | RFC-204 |
| Context Envelope | Rich context package sent from Layer 3 to Layer 2 containing world info, goals, memory, instructions. | RFC-204 |
| Same-Cron Conflict | Multiple tasks with identical cron expression. Resolved by sequential execution, ordered by creation/priority. | RFC-204 |
| Critical Message | Channel message requiring acknowledgment (e.g., blocker_alert, MUST goal confirmation). Retries with backoff. | RFC-204 |

### Layer 2 Execution Terms (RFC-201)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Context Isolation | Thread isolation for delegation steps where subagents receive only explicit task input, no prior conversation history. Prevents cross-wave contamination. | RFC-201 |
| Thread Isolation | Automatic isolation provided by task tool for subagent delegations. Tool executions use parent thread_id with langgraph concurrent safety. Simplified in RFC-209. | RFC-201, RFC-209 |
| Execution Bounds | Two-layer constraint preventing runaway subagent loops: soft constraint (schema/prompt) and hard constraint (subagent task cap). | RFC-201 |
| Wave Metrics | Structured metrics collected per Act wave (tool_call_count, subagent_task_count, output_length, error_count, context_window) informing Reason decisions. | RFC-201 |
| Subagent Task Cap | Maximum subagent delegations per Act wave (default 2). Stops stream early on cap hit, signals metrics to Reason. | RFC-201 |
| Output Contract | Layer 2 anti-repetition instructions preventing main model from pasting full subagent output after streaming. | RFC-201 |
| Manual Thread ID Generation (deprecated) | Old pattern where executor created isolated thread IDs (`{thread_id}__l2act{uuid}`, `{thread_id}__step_{i}`) and manually merged results. Removed in RFC-209. | RFC-201 (deprecated), RFC-209 |
| Outcome Metadata | Structured dict replacing full tool result content in StepResult. Contains type, tool_call_id, success_indicators, entities, size_bytes, optional file_ref. Enables Layer 2 reasoning without content bloat. | RFC-211 |
| Tool Call ID | Unique identifier from LangChain for each tool invocation (format: `call_<uuid>`). Guaranteed unique even for same tool called multiple times. Used for file cache naming. | RFC-211 |
| Tool Result Cache | File system cache for large tool results (>50KB) at `~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json`. Optional, cleaned up after thread completion. | RFC-211 |
| Minimal Data Contract | Design principle where Layer 2 receives only outcome metadata from Layer 1, not full tool result content. Layer 1 owns final report generation. | RFC-211 |

### Prompt Architecture Terms (RFC-206)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Hierarchical Prompt | Three-layer XML structure separating system context from user tasks. Uses explicit container tags: `<SYSTEM_CONTEXT>`, `<USER_TASK>`, `<INSTRUCTIONS>`. Prevents LLM confusion between metadata and user content. | RFC-206 |
| PromptBuilder | Internal API class that composes hierarchical prompts from modular XML fragments. Manages fragment loading, template rendering, and assembly. Not exposed to users for configuration. | RFC-206 |
| SYSTEM_CONTEXT | Top-level XML container holding static system metadata (environment, workspace, capabilities, policies). Explicitly marked as non-user-content to prevent processing during ambiguous requests. | RFC-206 |
| USER_TASK | Top-level XML container holding dynamic user-specific content (goal, prior conversation, evidence). This is the section LLM should focus on for user requests. | RFC-206 |
| INSTRUCTIONS | Top-level XML container holding output format specification and execution rules. Defines how LLM should respond to the task. | RFC-206 |
| Fragment Composition | Modular prompt construction from XML fragment files stored in `src/soothe/prompts/fragments/`. Each fragment has single responsibility (e.g., environment.xml, goal.xml). Internal implementation detail, not user-configurable. | RFC-206 |

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

# RFC Namings

This document defines the terminology and naming conventions used in this project.

**Last Updated**: 2026-06-25

## Core Terminology

### Core Module Architecture

| Term | Definition | Introduced In |
|------|------------|---------------|
| CoreAgent | Foundation runtime for Soothe's execution architecture. Handles tool/subagent execution via LangGraph CompiledStateGraph, created by `create_soothe_agent()`. Operates at the lowest level with Model → Tools → Model loop. | RFC-100 |
| StrangeLoop | Single-goal execution through iterative Plan-Execute cycles. Agentic goal execution for single-goal completion via iterative refinement. Operates at the middle level with Plan → Execute → Assess loop (max ~8 iterations). | RFC-201 |
| GoalEngine | Autonomous goal management with multi-goal DAGs, scheduling, and long-running workflows. Operates at the highest level with Goal → PLAN → PERFORM → REFLECT loop. Daemon-owned singleton service. | RFC-222 |
| LoopState | Persistent execution state across plan-execute cycles in StrangeLoop. Contains plan, progress, metrics, and execution context. LangGraph state schema. | RFC-201 |

**Naming Convention**: Use concrete module names (CoreAgent, StrangeLoop, GoalEngine) instead of abstract "Layer N" terminology. This improves clarity and follows CLAUDE.md Rule #9.

### Domain Terms

| Term | Definition | Introduced In |
|------|------------|---------------|
| Orchestrator | The Soothe agent instance created by `create_soothe_agent()`. Wires together all protocols and delegates to deepagents. | RFC-000 |
| Thread | One continuous agent conversation/execution. Has a unique ID, persistable state, and metadata. | RFC-000 |
| Delegation | Routing work to a subagent (local or remote) via deepagents' `task` tool. | RFC-000 |
| Parallel Delegation | Routing work to multiple subagents concurrently via multiple `task` tool calls in a single CoreAgent turn. Each subagent gets isolated thread branch automatically. | RFC-613 |
| Explore Agent | Specialized subagent for targeted filesystem searches using LLM-orchestrated iterative tool selection. Adapts strategy dynamically based on findings. | RFC-613 |
| Search Thoroughness | Configurable search depth levels: quick (3 iterations, minimal reading), medium (6 iterations, selective reading), thorough (10 iterations, deep analysis). | RFC-613 |
| Search Strategy | LLM-generated plan for filesystem search including priority directories, file patterns, content keywords, and search type classification. | RFC-613 |
| Match Validation | LLM assessment of found candidates against search target, ranking by relevance ("high", "medium", "low") and returning top 3-5 matches with brief descriptions. | RFC-613 |
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
| `LLMPlanner` | Unified planner using two-phase architecture (`StatusAssessment` + conditional `PlanGeneration` → `PlanResult`) for token efficiency; IG-372/IG-329 prompt and schema alignment. Replaces SimplePlanner, ClaudePlanner, AutoPlanner after IG-150 consolidation. | RFC-001, RFC-604 |
| `PolicyProtocol` | Protocol for permission checking and enforcement. | RFC-001 |
| `Permission` | A structured permission with category, action, and scope (e.g., `Permission("shell", "execute", "!rm")`). | RFC-001 |
| `PolicyMiddleware` | deepagents `AgentMiddleware` that enforces `PolicyProtocol`. | RFC-001 |
| `ContextMiddleware` | deepagents `AgentMiddleware` that manages `ContextProtocol` integration. | RFC-001 |
| `DurabilityProtocol` | Protocol for thread lifecycle management and state persistence. | RFC-001 |
| `IdentityProtocol` | Protocol for AKSK-based authentication and JWT token management. Provides user creation, AKSK provisioning, token issuance/validation, and external channel identity mapping. | RFC-307 |
| `IdentityMiddleware` | First middleware in stack, validates JWT tokens or resolves external sender_id to user_id before PolicyMiddleware. | RFC-307 |
| `AKSKPair` | Access Key / Secret Key credential pair for authentication. Access key format: `AK-{16 chars}`, Secret key format: `SK-{32 chars}`. | RFC-307 |
| `TokenClaims` | JWT payload structure containing jti, user_id, aksk_id, token_type, issued_at, expires_at. | RFC-307 |
| `ExternalIdentityMapping` | Mapping from external channel sender_id to soothe user_id for workspace isolation on external channels. | RFC-307 |
| `ThreadInfo` | Data model for thread state (id, status, timestamps, metadata). | RFC-001 |
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

### Autopilot Terms (RFC-203)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Autopilot Mode | Layer 3 extension enabling long-running autonomous operation with dreaming mode and continuous improvement. | RFC-203 |
| Dreaming Mode | Persistent idle state where Soothe performs memory consolidation, indexing, goal anticipation, and health monitoring. | RFC-203 |
| Consensus Loop | Layer 3 validation of Layer 2 completion judgment with send-back capability and budget. | RFC-203 |
| Send-Back Budget | Per-goal limit on Layer 3 rejections (default: 3 rounds). Independent from Layer 2 iteration budget. | RFC-203 |
| Channel Protocol | Message-centric protocol for user ↔ Soothe communication. Autopilot control uses HTTP REST; platform channels use RFC-620. | RFC-203 |
| CriticalityEvaluator | Module in GoalEngine that determines if a proposed goal requires user confirmation (MUST status). | RFC-203 |
| SchedulerService | Independent service in `core/goal_engine/scheduled_tasks.py` for time-based task execution (delay, cron, recurrence). | RFC-203 |
| Goal Relationship | Connection between goals: `depends_on` (hard), `informs` (soft), `conflicts_with` (mutual exclusion). | RFC-203 |
| Context Envelope | Rich context package sent from Layer 3 to Layer 2 containing world info, goals, memory, instructions. | RFC-203 |
| Same-Cron Conflict | Multiple tasks with identical cron expression. Resolved by sequential execution, ordered by creation/priority. | RFC-203 |
| Critical Message | Channel message requiring acknowledgment (e.g., blocker_alert, MUST goal confirmation). Retries with backoff. | RFC-203 |

### Entity Model Consolidation Terms (RFC-626)

| Term | Definition | Introduced In |
|------|------------|---------------|
| ExecutionState | Thin facade holding execution-only runtime fields (iteration, max_iterations, wave metrics, context window stats) with CE-backed properties for goal/step data. Replaces LoopState. | RFC-626 |
| Job | Root GoalNode with `parent_id=None` submitted to AutopilotService. Single entry point for DAG visualization and status queries. | RFC-626, RFC-228 |
| GoalNode | Unified entity model combining goal lifecycle, retry/backoff semantics, workspace metadata, and dreaming fields. CE's atomic unit of persistence. | RFC-624, RFC-625, RFC-626 |
| StepNode | Execution step entity within GoalNode's embedded StepDAG with lineage tracking (plan_iteration, reasoning_trace). | RFC-624, RFC-626 |
| LedgerManager | Unified message ledger replacing LoopWorkingMemory and loop_messages list, with phase-scoped retrieval and bounded projection. | RFC-624, RFC-626 |
| CheckpointEnvelope | Consolidated checkpoint structure storing CE GoalStepDAG snapshot and ExecutionState fields, eliminating duplicate StrangeLoop checkpoint schemas. | RFC-626 |

### Layer 2 Execution Terms (RFC-200)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Context Isolation | Thread isolation for delegation steps where subagents receive only explicit task input, no prior conversation history. Prevents cross-wave contamination. | RFC-200 |
| Thread Isolation | Automatic isolation provided by task tool for subagent delegations. Tool executions use parent thread_id with langgraph concurrent safety. Simplified in RFC-207. | RFC-200, RFC-207 |
| Execution Bounds | Two-layer constraint preventing runaway subagent loops: soft constraint (schema/prompt) and hard constraint (subagent task cap). | RFC-200 |
| Wave Metrics | Structured metrics collected per Act wave (tool_call_count, subagent_task_count, output_length, error_count, context_window) informing Reason decisions. | RFC-200 |
| Subagent Task Cap | Maximum subagent delegations per Act wave (default 2). Stops stream early on cap hit, signals metrics to Reason. | RFC-200 |
| Output Contract | Layer 2 anti-repetition instructions preventing main model from pasting full subagent output after streaming. | RFC-200 |
| Manual Thread ID Generation (deprecated) | Old pattern where executor created isolated thread IDs (`{thread_id}__l2act{uuid}`, `{thread_id}__step_{i}`) and manually merged results. Removed in RFC-207. | RFC-200 (deprecated), RFC-207 |
| Outcome Metadata | Structured dict replacing full tool result content in StepResult. Contains type, tool_call_id, success_indicators, entities, size_bytes, optional file_ref. Enables Layer 2 reasoning without content bloat. | RFC-211 |
| Tool Call ID | Unique identifier from LangChain for each tool invocation (format: `call_<uuid>`). Guaranteed unique even for same tool called multiple times. Used for file cache naming. | RFC-211 |
| Tool Result Cache | File system cache for large tool results (>50KB) at `~/.soothe/runs/{thread_id}/tool_results/{tool_call_id}.json`. Optional, cleaned up after thread completion. | RFC-211 |
| Minimal Data Contract | Design principle where Layer 2 receives only outcome metadata from Layer 1, not full tool result content. Layer 1 owns final report generation. | RFC-211 |

### Prior-Progress Digest Terms (RFC-227)

| Term | Definition | Introduced In |
|------|------------|---------------|
| `PriorProgressDigest` | Compact, typed snapshot of the most recent execute wave (`iteration`, `wave_index`, `steps_completed`, `steps_failed`, `tool_calls`, `evidence_excerpts`, `derived_progress_hint`). Produced once per wave by the executor, stashed on `LoopState.prior_progress`, consumed by `plan_assess` and `plan_generate` as grounding. Overwrite-only (K=1). | RFC-227 |
| `ToolCallHead` | One tool invocation captured from the most recent wave: `{name, head}` where `head` is the first non-empty line of the tool message content, stripped and truncated at 120 chars. | RFC-227 |
| `<PRIOR_PROGRESS>` | XML block appended to the plan-context envelope when `state.prior_progress` is present and not stale; renders `iter/wave/done/failed/hint`, up to 8 `tools` lines, and up to 3 `evidence` lines. Hard-capped at 600 chars. | RFC-227 |
| `derived_progress_hint` | Deterministic `"none"\|"low"\|"medium"\|"high"` label computed by `_update_prior_progress` from wave success/failure counts and evidence-text heuristics (digits, table glyphs, completion keywords). Shown verbatim inside `<PRIOR_PROGRESS>`; never overrides `StatusAssessment.goal_progress` in code. | RFC-227 |
| `_update_prior_progress()` | Executor helper invoked from `_append_parallel_wave_ledger`. Reads the just-finished wave's `steps`, `gather_results`, and `step_messages`; writes `state.prior_progress`. Pure-function over wave outputs; no I/O. | RFC-227 |
| Digest staleness | The envelope omits `<PRIOR_PROGRESS>` when `prior_progress.iteration < state.iteration - 1`. Prevents showing a snapshot from a long-past iteration as if it described the current state. | RFC-227 |
| Assessment-reasoning contract | The `plan_assess_instructions.xml` paragraph requiring `StatusAssessment.assessment_reasoning` to (a) summarize `<PRIOR_PROGRESS>` evidence when present and (b) never restate the user query. Closes the RFC-227 prompt gap. | RFC-227 |

### Continuation Discriminator Terms (RFC-226)

| Term | Definition | Introduced In |
|------|------------|---------------|
| `continuation_assess` | Iter=0 LLM call in `plan_assess` for continuation queries (`continue_loop_mode` AND `goal_history >= 2`). Reads the new query against persisted prior goals (RFC-225 enrichment) and emits a `ContinuationAssessment` that routes to either bootstrap or `plan_generate`. Replaces the structural `continue_loop_plan_bootstrap_allowed()` heuristic. | RFC-226 |
| `ContinuationAssessment` | Pydantic structured output of the `continuation_assess` LLM call: `{action: "bootstrap" | "plan_generate", reasoning, goal_progress}`. | RFC-226 |
| `LOOP_CONTINUATION_ASSESS_PROMPT` | Prompt template that surfaces prior goals (`goal_text`, `goal_completion` preview, `step_count`, `current_plan.next_action`) plus available capabilities to the discriminator LLM. | RFC-226 |
| `PlanResult.terminal_after_execute` | Boolean field on `PlanResult` asserting that the plan's single step IS the goal completion. When True, `route_after_record_iteration` routes directly to `goal_completion`, skipping the iter=1 status check. Set by the bootstrap path; default False elsewhere. | RFC-226 |
| Bootstrap action | `ContinuationAssessment.action == "bootstrap"` — the assess LLM judges that the new query can be answered using prior loop context with no new tools or steps. Triggers a single-step terminal plan via `build_continue_loop_bootstrap_plan(..., terminal_after_execute=True)`. | RFC-226 |
| Plan-generate action | `ContinuationAssessment.action == "plan_generate"` — the assess LLM judges that the new query needs multiple steps, new tools, or cross-domain work. Routes to the standard `plan_generate` node. | RFC-226 |
| Post-execute fast exit | The `record_iteration → goal_completion` conditional edge that fires when `ctx.scratch.plan_result.terminal_after_execute` is True. Eliminates the redundant iter=1 `plan_assess` LLM call on bootstrap paths. | RFC-226 |

### Loop Continuity & Goal Record Terms (RFC-225)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Loop | A continuous conversational unit identified by `loop_id`. Spans many goals and survives across user turns until the user starts a new loop (`/clear`). The unit of continuity for agentic intent. | RFC-207, RFC-225 |
| `continue_loop_mode` | Boolean derived once in `StrangeLoop` immediately after `state_manager.load()`. True when the loaded checkpoint has prior goals and is alive (`status ∈ {running, idle}`). Replaces the prior `continue_thread_mode` flag. | RFC-225 |
| Intent Type | Two-value LLM classification: `quiz` (greeting / thanks / trivia answerable without tools) or `agentic` (everything else). Whether an agentic query continues a loop is derived structurally, not classified. | RFC-225 |
| Quiz Fast-Path | Pre-stream short-circuit when `IntentClassification.intent_type == "quiz"`; uses the LLM's piggybacked `quiz_response` to skip the agent loop entirely. | RFC-225 |
| Idle (loop status) | `StrangeLoopCheckpoint.status == "idle"` — loop is alive between goals. Renamed from the legacy value `ready_for_next_goal`; legacy persisted values are coerced on load. | RFC-225 |
| Goal Record | `GoalExecutionRecord` — durable per-goal log inside `StrangeLoopCheckpoint.goal_history`. Carries the latest plan DAG (`current_plan`), accumulated `step_results`, `evidence_ledger`, `completed_step_ids`, `plan_revision_count`, the orchestration `loop_messages` ledger, and final output. Sufficient to recover the goal's plan DAG with execution overlay without external lookup. | RFC-207, RFC-225 |
| Plan DAG Recoverability | Invariant that the full DAG of any persisted goal — nodes, edges, execution mode, planner metadata, done-node overlay, per-node outcomes — is recoverable from `GoalExecutionRecord` alone. | RFC-225 |
| `_LOOP_CONTINUATION_GUIDE` | System-prompt section injected by `system_prompt` when `state["continue_loop_mode"]` is `True`. Renamed from `_THREAD_CONTINUATION_GUIDE`. | RFC-225 |
| `seed_loop_ledger_from_prior_goal()` | Seeds a new goal's `loop_messages` from the immediately prior completed goal in the same loop. Runs unconditionally for any same-loop new goal. Renamed from `seed_continue_thread_ledger_from_prior_goal()`. | RFC-225 |

### Clarification Relay Terms (RFC-622, RFC-623)

| Term | Definition | Introduced In |
|------|------------|---------------|
| Clarification Relay | CoreAgent → user → CoreAgent loop to resolve ambiguity without stopping the agent loop. When CoreAgent cannot confidently answer, it emits a `ClarificationRequest` event, suspends itself, waits for user clarification via `await_clarification` node, then resumes with the clarified answer. | RFC-622 |
| Veritas | Agent node that performs structured yes/no confidence checking for core agent answers. Checks whether CoreAgent has enough information to confidently respond to user. Emits `ClarificationDeferredError` when confidence is insufficient. | RFC-622 |
| Interactive Fallback | Mechanism allowing StrangeLoop to auto-retry Veritas failures up to N times before raising `ClarificationDeferredError` to the orchestrator. Prevents immediate loop exit on transient issues. | RFC-623 |
| `ClarificationPolicy` | Config knob controlling Veritas behavior: `max_defer_attempts` (N), `confidence_threshold`, `auto_retry_on_defer_kind`. | RFC-622 |
| `ClarificationRequest` | Event payload: `{question, context, urgency, timeout_hint}`. Sent from daemon to client when CoreAgent needs clarification. | RFC-622 |
| `ClarificationAnswer` | Event payload: `{original_question, answer, source}`. User response to a clarification request. | RFC-622 |
| `ClarificationDeferredError` | Exception raised after N Veritas failures. Signals StrangeLoop to either retry with different parameters or exit goal with clarification status. | RFC-622, RFC-623 |
| `DeferKind` | Enum in Veritas response: `ambiguous`, `insufficient_context`, `contradiction`, `other`. Used by Interactive Fallback to decide retry strategy. | RFC-623 |
| `VeritasAnswerSchema` | Pydantic model for Veritas structured output: `{can_answer: bool, defer_kind: DeferKind | null, reasoning: str}`. | RFC-622, RFC-623 |
| `await_clarification` Node | StrangeLoop state node that suspends execution, sends clarification request to client, and waits for user input. Resumes when `ClarificationAnswer` arrives. | RFC-622 |
| `awaiting_clarification` | LoopState status flag indicating CoreAgent is suspended waiting for user clarification. | RFC-622 |
| `defer_kind` (event field) | Field in `ClarificationDeferredError` event indicating why Veritas deferred. Used by downstream handlers for categorization. | RFC-623 |
| `invoke_structured_chat` | Veritas helper that calls the model with `VeritasAnswerSchema` to check confidence. Returns structured `can_answer` decision. | RFC-623 |
| `build_veritas_response_schema(n)` | Constructor for Veritas schema with configurable `max_defer_attempts` N. | RFC-623 |

### Code Naming

| Convention | Pattern | Example |
|------------|---------|---------|
| Protocol classes | `{Name}Protocol` | `ContextProtocol`, `PolicyProtocol` |
| Middleware classes | `{Name}Middleware` | `ContextMiddleware`, `PolicyMiddleware` |
| Module directories | snake_case | `src/soothe/protocols/`, `src/soothe/middleware/` |
| Config fields | snake_case | `planner_routing`, `policy_profiles` |
| Data models | CamelCase | `ContextEntry`, `Plan`, `Permission` |

---

## Related Documents

- [RFC Standard](rfc-standard.md) - RFC process and specification kinds
- [RFC Index](rfc-index.md) - Complete RFC catalog
- [RFC History](rfc-history.md) - Chronological change history

This terminology index is manually curated with automated extraction support. To update:

```bash
# Manual additions are preserved
# Automated extraction available via:
python scripts/generate_rfc_namings.py
```
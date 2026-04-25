# Soothe LLM Communication Flow Analysis

**Author**: Claude Code Analysis
**Date**: 2026-04-09
**Last Updated**: 2026-04-09 (Layer 1/Layer 2 message flow analysis added)
**Scope**: Analysis of how and what is sent to LLM in each execution thread across Soothe's three-layer architecture, including detailed message flow between layers

---

## Executive Summary

Soothe uses a **three-layer execution architecture** with distinct LLM communication patterns at each level. The system employs strategic LLM calls for classification, reasoning, and execution, with middleware-driven prompt optimization and bounded context projections for subagent delegations.

**Recent Optimization (RFC-207)**: Layer 1 CoreAgent now consolidates context projection and memories into SystemMessage, following RFC-207's SystemMessage/HumanMessage separation pattern. This improves token efficiency, LLM response quality, and architectural clarity.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ Layer 3: Autonomous Goal Management                     │
│ • Goal DAG coordination, PERFORM/REFLECT stages         │
│ • Delegates single goals to Layer 2                     │
└─────────────────────────────────────────────────────────┘
                      ↓ PERFORM (full delegation)
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Agentic Goal Execution (Reason → Act loop)    │
│ • Reason: One LLM call per iteration (planning +        │
│   progress assessment)                                  │
│ • Act: Delegates steps to Layer 1 CoreAgent             │
│ • Max ~8 iterations per goal                            │
└─────────────────────────────────────────────────────────┘
                      ↓ ACT (step execution)
┌─────────────────────────────────────────────────────────┐
│ Layer 1: CoreAgent Runtime                              │
│ • Model → Tools → Model loop (LangGraph native)         │
│ • Middleware stack (policy, prompts, context, hints)    │
│ • Tool parallelism, subagent delegation                 │
└─────────────────────────────────────────────────────────┘
```

**Key Reference Documents**:
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-200: Layer 2 Agentic Goal Execution Loop
- RFC-207: Message Type Separation (Layer 2)
- RFC-207: CoreAgent Message Optimization (Layer 1)
- RFC-100: Layer 1 CoreAgent Runtime

---

## LLM Communication Flow Per Thread

### Phase 1: Query Classification (Tier-1 Routing)

**When**: Before entering execution loop
**Model**: Fast model (role="fast")
**Purpose**: Determine query complexity and routing strategy
**Location**: `src/soothe/core/unified_classifier.py`

#### Input to LLM

**Recent Conversation Context**:
- Last 6 messages loaded from LangGraph checkpointer
- Formatted as short conversation string (max 300 chars per message)
- Format: `User: <preview>\nAssistant: <preview>`

**Current Query**:
- Raw user input text
- Unmodified

**Classification Prompt Structure**:
```
[System instructions for routing]
[Conversation context]
[User query]
[Output format specification]
```

#### Output from LLM

**Structured Response** (`UnifiedClassification`):
- `task_complexity`: chitchat | medium | complex
- `preferred_subagent`: Optional routing hint (e.g., "claude", "browser")
- `routing_hint`: subagent | default
- `chitchat_response`: Piggybacked response (chitchat only)

#### Behavioral Paths

**Chitchat Path** (complexity="chitchat"):
- Returns piggybacked response immediately
- No further LLM calls
- Saves exchange to checkpointer
- Total: **1 LLM call**

**Medium/Complex Path**:
- Proceeds to pre-stream preparation
- Loads memory and context projections
- Enters Layer 2 agentic loop

---

### Phase 2: Pre-Stream Preparation

**When**: After classification, before Layer 2 execution
**Model**: None (retrieval operations)
**Purpose**: Load persisted context and memory

#### Operations (Parallel Execution)

**Memory Recall** (`MemoryProtocol.recall()`):
- Query: user_input
- Limit: 5 items
- Backend: MemU memory store
- Output: `recalled_memories` list

**Context Projection** (`ContextProtocol.project()`):
- Query: user_input
- Token budget: 4000
- Backend: KeywordContext or VectorContext
- Output: `context_projection` with relevant entries

#### Thread Management

**Thread Creation/Resume**:
- `DurabilityProtocol.create_thread()` or `resume_thread()`
- Thread ID generation or reuse
- Checkpointer initialization (AsyncSqliteSaver/AsyncPostgresSaver)

**Context Restore** (when resuming):
- `ContextProtocol.restore(thread_id)` for persisted context ledger
- Lock-protected restoration (async lock)

**Note**: Zero LLM calls in this phase - pure retrieval from persisted storage.

---

### Phase 3: Layer 2 Reason Phase (Per Iteration)

**When**: Each iteration of the agentic loop (up to 8 times max)
**Model**: Reasoning model (role="reasoning")
**Purpose**: Assess progress and produce next plan fragment
**Location**: `src/soothe/cognition/agent_loop/reason.py`

#### Call Frequency Pattern

- **Iteration 0**: Always called (initial planning)
- **Subsequent iterations**:
  - Called if `plan_action=="replan"` or no remaining steps
  - Skipped if `plan_action=="continue"` and steps remain
- **Max calls**: ~8 per single goal execution

#### Input to LLM

**Message Structure**: `SystemMessage + HumanMessage` (RFC-207 proper separation)

**SystemMessage Contents** (static context):

1. **Environment/Workspace Prefix** (RFC-104):
   - Configuration metadata
   - Workspace path (when available)
   - Git status (branch, remote, status summary)

2. **Workspace Rules** (when workspace present):
   ```
   <WORKSPACE_RULES>
   - Use file tools against this directory
   - For architecture goals: inspect directory immediately
   - Do NOT ask user for GitHub URLs or file uploads
   </WORKSPACE_RULES>
   ```

3. **Prior Conversation Follow-Up Policy** (when recent messages exist):
   ```
   <FOLLOW_UP_POLICY>
   - Status MUST NOT be "done" until CoreAgent execution produces output
   - Include concrete execute_steps item for follow-up work
   </FOLLOW_UP_POLICY>
   ```

4. **Static Policy Fragments**:
   - Delegation policy (from `fragments/system/policies/delegation.xml`)
   - Granularity policy (from `fragments/system/policies/granularity.xml`)

5. **Output Format Specification**:
   - Structured output schema for ReasonResult
   - JSON/YAML format instructions

**HumanMessage Contents** (dynamic task):

1. **Goal Description**:
   - Raw goal text from user

2. **Loop Iteration Info**:
   - Current iteration number
   - Max iterations limit

3. **Prior Conversation Excerpts** (IG-128, IG-133):
   - Last 10 messages formatted as XML tags
   - Only HumanMessage and AIMessage (no tool/system messages)
   - Format: `<user>...</user>` and `<assistant>...</assistant>`
   - Last AIMessage gets higher char limit (100k vs 8k)

4. **Evidence from Completed Steps**:
   - Summary strings from previous Act phase
   - Format: `Step ID: <result preview>`
   - Truncated to prevent bloat

5. **Completed Step Summaries**:
   - Planner context of previously completed steps
   - Prevents redundant work

6. **Working Memory Excerpt** (RFC-203):
   - Structured scratchpad for current goal
   - Authoritative record of inspected items
   - Encourages file reads over repeated listings

7. **Previous Reason Assessment** (continuity):
   - Status from last iteration
   - Progress estimate
   - User summary preview
   - Next steps hint

8. **Available Capabilities**:
   - List of enabled tools
   - List of enabled subagents

**Prompt Construction**: `src/soothe/core/prompts/builder.py` → `build_reason_messages()`

#### Output from LLM

**Structured ReasonResult** (Pydantic model):

```python
{
  "status": "done" | "continue" | "replan",
  "goal_progress": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "Internal reasoning string",
  "evidence_summary": "Accumulated evidence from steps",
  "user_summary": "Human-readable progress summary",
  "plan_action": "keep" | "new",
  "decision": AgentDecision | None,  # New plan when plan_action=="new"
  "soothe_next_action": "Action description for UI display",
  "next_steps_hint": "Guidance for next Act phase",
  "full_output": None | "Complete output when done"
}
```

**AgentDecision Structure**:
- `type`: "execute_steps" | "final"
- `steps`: List of StepAction (1-N steps)
- `execution_mode`: "parallel" | "sequential" | "dependency"
- `reasoning`: Plan rationale

**StepAction Structure**:
- `description`: Step goal description
- `tools`: Optional tool suggestions
- `subagent`: Optional subagent hint
- `expected_output`: Expected result description
- `dependencies`: Optional step dependencies (DAG)

#### Evidence Accumulation

**Before LLM Call**:
- Step results formatted as evidence strings
- `state.evidence_summary` populated

**After LLM Call**:
- Model-supplied evidence truncated if too long (max 600 chars)
- Prefers compact step-derived evidence

#### Post-Processing

**Action Enhancement** (RFC-603):
- `soothe_next_action` enriched for specificity
- Prevents vague action descriptions
- Checks against recent action history (last 3)
- Updates both `soothe_next_action` AND `user_summary`

**Action History Tracking**:
- Enhanced action added to `state.action_history`
- Prevents progressive repetition across iterations

---

### Phase 4: Layer 2 Act Phase → Layer 1 CoreAgent Execution

**When**: Each step in the AgentDecision (parallel or sequential)
**Model**: Default model (role="default") or subagent-specific model
**Purpose**: Execute tools/subagents to accomplish step goal
**Location**: `src/soothe/cognition/agent_loop/executor.py`

#### Thread Isolation Strategy

**Automatic Isolation** (RFC-200, simplified in RFC-207):
- **Subagent Steps**: task tool creates isolated thread branches automatically
  - Thread ID: `{thread_id}__task_{uuid}` (handled by task tool internally)
  - Fresh checkpoint branch
  - Results merge back via ToolMessage
- **Tool-Only Steps**: Use parent thread context
  - Standard thread continuation
  - All prior messages visible
  - langgraph handles concurrent execution safely

**Purpose**: Prevents cross-wave contamination (e.g., research output interfering with translation language detection)

**Note**: RFC-207 simplifies executor implementation by removing manual thread ID generation (`{thread_id}__l2act{uuid}` and `{thread_id}__step_{i}`) and trusting langgraph's built-in concurrency handling and task tool's automatic isolation.

#### Execution Bounds

**Soft Constraint**:
- Schema/prompt defines: "one delegation = one call"
- Retry requires explicit second step

**Hard Constraint**:
- `max_subagent_tasks_per_wave`: 2 (default)
- Cap hit signals metrics to Reason
- Stream stops early when cap exceeded

---

### Phase 4.1: Middleware Stack (Pre-Model Processing)

**Order**: Sequential processing before LLM call
**Location**: `src/soothe/core/middleware/_builder.py`

#### Middleware Chain

1. **WorkspaceContextMiddleware**:
   - Sets ContextVar for workspace path
   - Enables file operations without explicit path passing
   - Location: `src/soothe/core/middleware/workspace_context.py`

2. **SoothePolicyMiddleware**:
   - Checks permissions for tool/subagent calls
   - Enforces PolicyProtocol before execution
   - Returns deny/allow/need-approval decisions
   - Location: `src/soothe/core/middleware/policy.py`

3. **SystemPromptOptimizationMiddleware**:
   - Dynamic system prompt based on complexity
   - Injects XML context sections (RFC-104)
   - Location: `src/soothe/core/middleware/system_prompt_optimization.py`

4. **ExecutionHintsMiddleware**:
   - Injects Layer 2 execution hints
   - Advisory suggestions (tools, subagent, expected output)
   - Location: `src/soothe/core/middleware/execution_hints.py`

5. **SubagentContextMiddleware**:
   - Injects context briefing for subagent delegations
   - Scoped projection (max 1200 tokens)
   - Location: `src/soothe/core/middleware/subagent_context.py`

---

### Phase 4.2: CoreAgent LLM Input Construction

**System Prompt** (complexity-based optimization, updated in RFC-207):

**Chitchat Complexity**:
```
[SIMPLE_SYSTEM_PROMPT]
[Current date line]
```
- Minimal prompt for quick greetings
- No context injection

**Medium Complexity**:
```
[MEDIUM_SYSTEM_PROMPT]
[Current date line]
<ENVIRONMENT>...</ENVIRONMENT>
<WORKSPACE>...</WORKSPACE>
<context>...</context> [RFC-207]
<memory>...</memory> [RFC-207]
<SOOTHE_THREAD_CONTEXT>...</SOOTHE_THREAD_CONTEXT>
<SOOTHE_PROTOCOL_SUMMARY>...</SOOTHE_PROTOCOL_SUMMARY>
```
- Standard prompt with guidelines
- Context and memory sections now in SystemMessage (RFC-207)

**Complex Complexity**:
```
[DEFAULT_SYSTEM_PROMPT or config.system_prompt]
[Current date line]
<ENVIRONMENT>...</ENVIRONMENT>
<WORKSPACE>...</WORKSPACE>
<context>...</context> [RFC-207]
<memory>...</memory> [RFC-207]
<SOOTHE_THREAD_CONTEXT>...</SOOTHE_THREAD_CONTEXT>
<SOOTHE_PROTOCOL_SUMMARY>...</SOOTHE_PROTOCOL_SUMMARY>
```
- Full prompt with all context
- Maximum context injection including context/memory

**XML Context Sections** (RFC-104, RFC-207):

- `<ENVIRONMENT>`:
  - Platform, shell, OS version
  - Model identifier and knowledge cutoff

- `<WORKSPACE>`:
  - Workspace root path
  - Git status (branch, remote, file changes)
  - Recent commits summary

- `<context>` (RFC-207 NEW):
  - Context projection entries (top 10, 200 chars each)
  - Relevant findings from tool/subagent results
  - Moved from HumanMessage to SystemMessage

- `<memory>` (RFC-207 NEW):
  - Recalled memories (top 5, 200 chars each)
  - Cross-thread long-term memory items
  - Moved from HumanMessage to SystemMessage

- `<SOOTHE_THREAD_CONTEXT>`:
  - Thread ID
  - Active goals
  - Conversation turn count
  - Current plan preview

- `<SOOTHE_PROTOCOL_SUMMARY>`:
  - Context protocol stats (entry count)
  - Memory protocol stats (recalled items)
  - Planner and policy type names

**Execution Hints Injection** (advisory):

- `soothe_step_tools`: Suggested tool names (e.g., "read_file, grep")
- `soothe_step_subagent`: Suggested subagent name (e.g., "claude")
- `soothe_step_expected_output`: Expected result description

**Note**: Hints are advisory - LLM can choose different tools or ignore suggestions.

**Context Briefing** (for subagent delegations only):

```
<subagent_context>
Use this scoped context briefing while solving the task:
- [source] content preview (max 8 entries, 220 chars each)
</subagent_context>
```
- Token budget: 1200 (default)
- Scoped projection from orchestrator's context ledger
- Injected into `task` tool prompt argument

**HumanMessage** (simplified in RFC-207):

**Before RFC-207**:
- Context projection entries
- Recalled memories
- User query text

**After RFC-207**:
- **User query text ONLY**
- Context and memory moved to SystemMessage
- Clear separation: SystemMessage = context, HumanMessage = user task

**Prior Messages** (if resuming thread):
- Loaded from LangGraph checkpointer
- Full message history for thread context
- Maintained as conversation history

---

### Phase 4.3: Model Call and Response

**LLM Invocation**:
- LangGraph agent execution via `core_agent.astream()`
- Stream modes: messages, updates, custom
- Subgraphs=True for nested visibility

#### Response Types

**AIMessage Stream**:
- Text chunks accumulated via `_accumulate_response()`
- Content blocks extracted
- Full response assembled for evidence

**Tool Calls**:
- Multiple tool calls per message (parallel execution)
- `asyncio.gather()` for concurrent tool invocation
- Results as ToolMessage

**Policy Enforcement**:
- Every tool call checked by SoothePolicyMiddleware
- Permission set narrowed for subagents
- Deny stops execution, returns error

#### Tool Execution

**Parallel Tool Pattern**:
```python
results = await asyncio.gather([
    execute_tool(tool_call_1),
    execute_tool(tool_call_2),
    ...
])
```

**Tool Types**:
- Built-in tools (file operations, web search, etc.)
- MCP server tools (loaded via config)
- Custom plugin tools (decorator-based)

#### Subagent Delegation

**Task Tool Invocation**:
- `task` tool called with prompt/description
- SubagentContextMiddleware injects briefing
- Creates CompiledSubAgent instance
- Inherits narrowed permission set

**Subagent Execution**:
- Isolated thread branch (automatic)
- Fresh LangGraph state
- Scoped context (no orchestrator's full ledger)
- Returns results only

**Result Integration**:
- Subagent output streamed to TUI
- Results collected for Layer 2 evidence
- Merged back to canonical thread after completion

#### Response Accumulation

**Stream Processing**:
- AIMessage chunks collected per message ID
- Deduplication via `seen_message_ids` set
- Content blocks and text content merged

**Evidence Collection**:
- Successful step outputs recorded
- Tool call counts tracked
- Duration metrics captured

---

### Phase 5: Layer 3 Autonomous Goal Management

**When**: Explicit goal DAG execution (autonomous=True)
**Model**: Goal-specific models (think/reasoning roles)
**Purpose**: Multi-goal coordination with explicit goal lifecycle
**Location**: `src/soothe/cognition/goal_engine/`

#### Additional LLM Calls

**Goal Engine Operations**:
- Goal validation (structured checks)
- Consensus verification (think model)
- Goal state transitions

**REFLECT Stage**:
- Multi-goal reflection after PERFORM
- Goal progress assessment
- Strategy revision

**Goal DAG Scheduling**:
- Dependency resolution
- Parallel goal execution (when independent)
- Priority-based ordering

#### Delegation Pattern

**PERFORM Stage → Layer 2**:
- Full delegation to agentic loop
- Single goal execution handled entirely by Layer 2
- Layer 3 coordinates at goal level

**Goal Evidence Accumulation**:
- Layer 2 → Layer 3: Goal-level results
- Evidence aggregated across multiple goals
- Final synthesis at DAG completion

---

## Communication Summary Table

| Layer | Phase | Model Role | Calls Per Iteration | Input Key Elements | Output Key Elements |
|-------|-------|------------|---------------------|-------------------|-------------------|
| Tier-1 | Classification | fast | 1 | Recent messages (6) + query | Complexity + routing + piggybacked response |
| Pre-stream | Memory/Context | - | 0 (retrieval) | User query | Memories (5) + projection (4000 tokens) |
| Layer 2 | Reason | reasoning | ~8 max | System (static policies) + Human (goal, evidence, working memory, prior conversation) | ReasonResult (plan + progress + evidence) |
| Layer 1 | Act (per step) | default | 1+ (per tool call) | System (complexity-optimized + context + memory [RFC-207]) + Human (user query) + hints + context briefing | Tool calls + AI response (streamed) |
| Subagent | Delegation | inherited | 1+ (isolated thread) | Scoped briefing (1200 tokens) + task description | Task results (no full context) |
| Layer 3 | Autonomous | think | Goal-dependent | Goal DAG state + goal descriptions | Goal coordination + consensus |

---

## Key Design Principles

### 1. Context Isolation

**Orchestrator Context**:
- Unbounded context ledger (ContextProtocol)
- Append-only accumulation
- Persisted across threads via DurabilityProtocol

**Subagent Context**:
- Bounded projections (max 1200 tokens)
- Scoped to subagent goal
- No access to orchestrator's full ledger

**Thread Isolation**:
- Automatic for subagent steps
- Prevents cross-wave contamination
- Fresh checkpoint branches

### 2. Middleware-Driven Optimization

**Prompt Adjustment**:
- Complexity-based system prompts
- XML context injection (RFC-104)
- Execution hints (advisory)

**Policy Enforcement**:
- Pre-execution permission checks
- Least-privilege delegation
- Scoped permission inheritance

### 3. Streaming Architecture

**Stream Modes**:
- `messages`: AI content chunks
- `updates`: State transitions
- `custom`: Protocol events (soothe.* namespace)

**Nested Agent Visibility**:
- Subgraphs=True for deep visibility
- Event propagation through layers
- Progressive result display

### 4. Evidence Accumulation

**Layer 1 → Layer 2**:
- Tool results → step results
- Output length, call counts, duration
- Success/failure status

**Layer 2 Reason**:
- Aggregates evidence for progress assessment
- Truncated summaries (max 600 chars)
- Working memory integration

**Layer 3 → Goals**:
- Goal-level evidence for DAG coordination
- Multi-goal synthesis
- Consensus verification

### 5. Execution Bounds

**Iteration Limits**:
- Layer 2: Max 8 iterations per goal
- Prevents infinite loops

**Subagent Caps**:
- Max 2 subagent tasks per Act wave
- Soft + hard constraints
- Metrics signal to Reason

**Rate Limiting**:
- ThreadExecutor has APIRateLimiter
- Concurrent thread execution control
- Max 4 concurrent threads (default)

---

## Thread Lifecycle Persistence

### State Management

**LangGraph Checkpointer**:
- Stores all messages (Human, AI, Tool, System)
- AsyncSqliteSaver or AsyncPostgresSaver
- Thread ID as primary key

**Context Ledger**:
- Persisted via ContextProtocol.persist()
- One file per thread (JSON/RocksDB)
- Restored on thread resume

**Thread Metadata**:
- DurabilityProtocol manages lifecycle
- Status: active, suspended, archived
- Timestamps, policy profile, labels

### Resume Pattern

**Thread Resume Operations**:
1. Load thread metadata from durability
2. Initialize AsyncSqliteSaver/AsyncPostgresSaver
3. Load recent messages from checkpointer (limit: 16)
4. Restore context ledger from persistence
5. Format prior conversation for Reason phase
6. Continue from last checkpoint state

**Conversation Context**:
- Last 10 messages for Reason (IG-128)
- Last 16 messages for routing/classification
- XML format for multi-line content handling

---

## Layer 1 ↔ Layer 2 Message Flow Architecture

### Critical Boundaries

This section analyzes the message flow between Layer 1 CoreAgent and Layer 2 Loop Agent, focusing on what's persisted, derived, and carried forward across iterations.

**Key Principle**: Layer 2 maintains its own checkpoint separate from Layer 1, deriving conversation context from execution results rather than inheriting raw messages (RFC-203).

#### 1. What's Saved in Layer 1 Checkpointer

**LangGraph Checkpointer Contents** (AsyncSqliteSaver/AsyncPostgresSaver):

```python
# Full message history in thread checkpoint
[
    SystemMessage(content="...system prompt with context/memory..."),  # RFC-207
    HumanMessage(content="User query"),
    AIMessage(content="AI response with tool calls"),
    ToolMessage(content="Tool result", name="read_file"),
    ToolMessage(content="Subagent result", name="task"),  # Subagent delegations
    AIMessage(content="Final response"),
    ...
]
```

**Characteristics**:
- **All message types**: System, Human, AI, Tool
- **Full thread history**: Unbounded growth (middleware handles summarization)
- **Automatic persistence**: Every turn saved atomically
- **Thread ID keyed**: `{thread_id}` as primary key
- **Subagent isolation**: ToolMessage(name="task") contains subagent results

**Storage Location**: `src/soothe/core/runner/_runner_phases.py` lines 307-324

#### 2. What's Passed to Layer 2 Reason Phase

**Layer 2's Independent Checkpoint** (RFC-203):

From `src/soothe/cognition/agent_loop/loop_agent.py` lines 124-137:

```python
# Layer 2 uses its OWN checkpoint, not Layer 1 messages
checkpoint = state_manager.load()  # Layer 2's own checkpoint
if checkpoint and checkpoint.status == "running":
    # Recover from Layer 2 checkpoint
    prior_outputs = state_manager.derive_reason_conversation(limit=10)
    reason_excerpts = prior_outputs
else:
    # Start fresh - NO Layer 1 messages
    checkpoint = state_manager.initialize(goal, max_iterations)
    reason_excerpts = []  # Empty - no prior conversation from Layer 1
```

**What's in `reason_conversation_excerpts`**:

From `src/soothe/core/runner/_runner_phases.py` lines 259-296:

```python
# Format: <user>...</user> and <assistant>...</assistant> XML tags
# Last 10 messages (configurable via prior_conversation_limit)
# Only HumanMessage and AIMessage (no Tool/System)
# Last AIMessage gets higher char limit (100k vs 8k)
```

**Example Format**:
```xml
<user>Translate this to Chinese</user>
<assistant>I'll help you translate the document...</assistant>
<user>Research async patterns in Python</user>
<assistant>I found several async patterns...</assistant>
```

**Why Layer 2 Doesn't Inherit Layer 1 Messages**:
- Layer 2 manages **goal-level** reasoning, not conversation turns
- Layer 1's tool execution details are noise for goal planning
- Prior conversation should be **derived** from Layer 2's own step outputs
- Prevents contamination from Layer 1's subagent/tool chatter (RFC-203)

**Evidence Flow Direction**:

```
Layer 1 → Layer 2:
  ToolMessage.content → StepResult.output → state.step_results
  ↓
  evidence_lines = [result.to_evidence_string() for result in state.step_results]
  ↓
  state.evidence_summary = "\n".join(evidence_lines)
  ↓
  Reason phase receives evidence_summary + step_results
```

**Not message-level inheritance**: Layer 2 sees **results**, not messages.

#### 3. What's Passed to Next Iteration

**LoopState Carried Forward** (from `src/soothe/cognition/agent_loop/schemas.py`):

```python
# State passed to next iteration
state.previous_reason          # Last ReasonResult (continuity)
state.step_results             # All StepResult objects (accumulation)
state.evidence_summary         # Accumulated evidence text
state.completed_step_ids       # Set of completed step IDs
state.current_decision         # Active AgentDecision (for reuse)
state.working_memory           # LoopWorkingMemory (RFC-203)
state.action_history           # Progressive actions (RFC-603)
state.iteration                # Current iteration number

# Metrics from last Act wave (IG-130)
state.last_wave_tool_call_count
state.last_wave_subagent_task_count
state.last_wave_hit_subagent_cap
state.last_wave_output_length
state.last_wave_error_count
state.total_tokens_used
state.context_percentage_consumed
```

**Loop Continuity Mechanism** (`src/soothe/cognition/agent_loop/loop_agent.py` lines 158-346):

```python
while state.iteration < state.max_iterations:
    # REASON phase
    reason_result = await self.reason_phase.reason(goal, state, context)

    # ACT phase
    async for item in self.executor.execute(decision, state):
        # Stream events + collect StepResults
        step_results.append(item)

    # UPDATE state for next iteration
    for result in step_results:
        state.add_step_result(result)  # Accumulates to state.step_results

    state.previous_reason = reason_result
    state.iteration += 1

    # Checkpoint persistence (RFC-203)
    state_manager.record_iteration(
        iteration=state.iteration,
        reason_result=reason_result,
        decision=decision,
        step_results=step_results,
        state=state,
        working_memory=state.working_memory,
    )
```

### Message Type Lifecycle

#### HumanMessage

**Created at**:
- CLI user input (`src/soothe/core/runner/_runner_phases.py` line 796)
- Executor for Act phase (`src/soothe/cognition/agent_loop/executor.py` lines 370, 531)

**Stored in**:
- Layer 1 checkpointer (full conversation)
- Layer 2 checkpoint (derived excerpts only)

**Passed to**:
- Layer 1 CoreAgent.astream() (current turn)
- Layer 2 Reason phase (as XML excerpts)
- Next iteration (as `reason_conversation_excerpts` in state)

#### AIMessage

**Created at**:
- Model response (Layer 1 execution)
- Executor accumulation (`src/soothe/cognition/agent_loop/executor.py` line 667)

**Stored in**:
- Layer 1 checkpointer (with tool calls)
- Layer 2 checkpoint (derived excerpts)

**Passed to**:
- Layer 2 Reason (as `<assistant>` XML excerpts)
- Next iteration (in `previous_reason.user_summary`)

#### ToolMessage

**Created at**:
- Tool execution results (Layer 1)
- Subagent delegation results (task tool)

**Stored in**:
- Layer 1 checkpointer ONLY
- NOT passed to Layer 2 Reason

**Evidence flow**:
- ToolMessage.content → StepResult.output → state.step_results
- Layer 2 sees results, NOT raw ToolMessages

#### SystemMessage

**Created at**:
- CoreAgent middleware stack (RFC-207)
- Contains: context, memory, policies, environment

**Stored in**:
- Layer 1 checkpointer
- NOT passed to Layer 2

**Purpose**: Layer 1 execution context only

### Layer Separation Principle

**Layer 1**: Conversation turns, tool execution, subagent delegations
**Layer 2**: Goal reasoning, iteration planning, progress assessment

**Critical separation** (RFC-203):
- Layer 2 does NOT inherit Layer 1's message history
- Layer 2 derives its own conversation context from step outputs
- Prevents contamination from tool/subagent chatter
- Focuses reasoning on goal-level context, not execution details

### Contamination Prevention Example

**Scenario**: Research → Translation workflow (RFC-200)

```
Iteration 1: Research async patterns (subagent delegation)
  → Layer 1 creates isolated thread for subagent
  → Research output in ToolMessage(name="task")
  → Returns to parent thread as ToolMessage

Iteration 2: Write async function (tool execution)
  → Layer 2 sees: "Step 1 completed: found async patterns"
  → Layer 2 does NOT see: Full research output (ToolMessage content)
  → Reason prompt: "Prior conversation: <user>Research async...</user>"

Translation scenario (contamination risk):
  → If Layer 2 saw Layer 1's research ToolMessage
  → Language detection could fail (research output mixing)
  → Isolation prevents this automatically (RFC-207)
```

### Message Flow Summary Table

| Content Type | Layer 1 Checkpoint | Layer 2 Checkpoint | Passed to Next Iteration |
|--------------|-------------------|--------------------|-------------------------|
| HumanMessage (user queries) | ✅ Full history | ✅ Derived excerpts (XML) | ✅ reason_conversation_excerpts |
| AIMessage (AI responses) | ✅ Full history | ✅ Derived excerpts (XML) | ✅ previous_reason.user_summary |
| ToolMessage (tool results) | ✅ All tool messages | ❌ NOT stored | ✅ Via StepResult.output |
| SystemMessage (context) | ✅ System prompt | ❌ NOT stored | ❌ NOT passed |
| StepResult (execution) | ❌ NOT in L1 | ✅ In L2 checkpoint | ✅ state.step_results |
| ReasonResult (reasoning) | ❌ NOT in L1 | ✅ In L2 checkpoint | ✅ state.previous_reason |
| LoopState (full state) | ❌ NOT in L1 | ✅ Full state | ✅ Carried forward |

**Flow direction**: Layer 1 messages → Layer 2 derived excerpts → Next iteration state

**Separation principle**: Layer 2 uses its own checkpoint, not Layer 1's raw messages

**Evidence flow**: ToolMessage → StepResult → evidence_summary → Reason phase

### Complete Message Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1 COREAGENT (Tool Execution)                                 │
│                                                                      │
│ Checkpointer stores:                                                │
│ ├─ SystemMessage (context, memory, policies) [RFC-207]            │
│ ├─ HumanMessage (user query)                                        │
│ ├─ AIMessage (tool calls)                                          │
│ ├─ ToolMessage (tool results)                                       │
│ ├─ ToolMessage (task=subagent results)                             │
│ └─ AIMessage (final response)                                       │
│                                                                      │
│ Thread ID: {thread_id}                                              │
│ Persistence: Full conversation history                               │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (NOT passed directly to Layer 2)
                    ↓ (Layer 2 uses its own checkpoint)

┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 2 LOOP AGENT (Goal Reasoning)                                │
│                                                                      │
│ Separate checkpoint (RFC-203):                                      │
│ ├─ goal: Goal description                                           │
│ ├─ iteration: Current iteration                                     │
│ ├─ status: running/completed/failed                                │
│ ├─ step_outputs: Derived conversation excerpts                      │
│ └─ working_memory_state: Inspection records                         │
│                                                                      │
│ reason_conversation_excerpts (IG-128):                              │
│ ├─ Last 10 messages formatted as XML                               │
│ ├─ <user>...</user> tags                                            │
│ ├─ <assistant>...</assistant> tags                                  │
│ └─ Derived from Layer 2 step outputs (NOT Layer 1)                 │
│                                                                      │
│ Thread ID: {thread_id}__layer2 (separate namespace)                │
│ Persistence: Goal-level reasoning state                              │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (State passed to next iteration)

┌─────────────────────────────────────────────────────────────────────┐
│ NEXT ITERATION STATE                                                │
│                                                                      │
│ LoopState carries forward:                                          │
│ ├─ previous_reason: Last ReasonResult                               │
│ ├─ step_results: All StepResult objects                            │
│ ├─ evidence_summary: Accumulated evidence                           │
│ ├─ completed_step_ids: Set of completed IDs                         │
│ ├─ current_decision: Active AgentDecision                          │
│ ├─ working_memory: LoopWorkingMemory                                │
│ ├─ action_history: Last 3 actions (RFC-603)                        │
│ └─ iteration: Incremented counter                                   │
│                                                                      │
│ Metrics from last Act wave:                                         │
│ ├─ last_wave_tool_call_count                                       │
│ ├─ last_wave_subagent_task_count                                   │
│ ├─ last_wave_hit_subagent_cap                                      │
│ ├─ last_wave_output_length                                         │
│ ├─ last_wave_error_count                                           │
│ ├─ total_tokens_used                                               │
│ └─ context_percentage_consumed                                     │
│                                                                      │
│ Persistence: Layer 2 checkpoint updated each iteration              │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Source Files

**Layer 1 Checkpointer**:
- `src/soothe/core/runner/_runner_phases.py`: Message persistence (lines 307-324)
- `src/soothe/core/runner/_runner_agentic.py`: Thread loading (lines 191-195)

**Layer 2 State Management**:
- `src/soothe/cognition/agent_loop/loop_agent.py`: Checkpoint recovery (lines 124-137)
- `src/soothe/cognition/agent_loop/state_manager.py`: Layer 2 checkpoint operations
- `src/soothe/cognition/agent_loop/schemas.py`: LoopState schema definition

**Message Formatting**:
- `src/soothe/core/runner/_runner_phases.py`: XML excerpt formatting (lines 259-296)

**Evidence Accumulation**:
- `src/soothe/cognition/agent_loop/reason.py`: Evidence aggregation (lines 35-62)
- `src/soothe/cognition/agent_loop/executor.py`: Step result collection

---

## Performance Optimization Patterns

### Parallel Execution

**Tier-2 Enrichment** (RFC-0008 Phase 2):
- Memory recall + context projection in parallel
- `asyncio.gather()` for concurrent operations
- Reduces pre-stream latency

**Tool Parallelism**:
- Multiple tool calls per AI message
- `asyncio.gather()` for concurrent execution
- Results merged as ToolMessages

### Caching Strategies

**Prompt Fragment Loading**:
- Static fragments cached in memory
- Loaded once at startup
- No repeated file reads

**Context Projection**:
- Token budget-aware projections
- Relevance-ranked entries
- Prevents context bloat

**Memory Recall**:
- Semantic search with limit
- Avoids loading entire memory store
- Top-K retrieval

---

## Error Handling and Degradation

### LLM Call Failures

**Classification Failure**:
- Falls back to heuristic classification
- Continues execution with safe defaults

**Reason Failure**:
- Returns fallback ReasonResult
- Status: "replan", progress: 0.0
- Evidence summary preserved

**Tool Execution Failure**:
- Individual tool errors recorded
- Step marked as failed
- Evidence accumulated for Reason

### Graceful Degradation

**Partial Results**:
- Failed steps don't abort entire goal
- Reason can replan with partial evidence
- Goal progress tracked despite failures

**Checkpoint Recovery**:
- Layer 2 checkpoint saves iteration state
- Can resume from last successful iteration
- State manager handles persistence

---

## Implementation References

### Key Source Files

**Runner and Orchestration**:
- `src/soothe/core/runner/__init__.py`: Main runner
- `src/soothe/core/runner/_runner_agentic.py`: Layer 2 loop
- `src/soothe/core/runner/_runner_phases.py`: Stream phases

**Loop Agent**:
- `src/soothe/cognition/agent_loop/loop_agent.py`: AgentLoop class
- `src/soothe/cognition/agent_loop/reason.py`: Reason phase
- `src/soothe/cognition/agent_loop/executor.py`: Act executor

**Middleware Stack**:
- `src/soothe/core/middleware/_builder.py`: Stack construction
- `src/soothe/core/middleware/system_prompt_optimization.py`: Prompt optimization
- `src/soothe/core/middleware/subagent_context.py`: Context briefing

**Prompt Building**:
- `src/soothe/core/prompts/builder.py`: Reason prompt construction
- `src/soothe/core/prompts/context_xml.py`: XML context sections
- `src/soothe/core/prompts/fragments/`: Static prompt fragments

**Classification**:
- `src/soothe/core/unified_classifier.py`: Query classification

**Protocols**:
- `src/soothe/protocols/context.py`: ContextProtocol
- `src/soothe/protocols/memory.py`: MemoryProtocol
- `src/soothe/protocols/planner.py`: PlannerProtocol

### Configuration Files

**System Configuration**:
- `config/config.yml`: Template configuration
- `config/config.dev.yml`: Development defaults
- `config/env.example`: Environment variables

**Protocol Settings**:
- `protocols.context.enabled`: Context protocol activation
- `protocols.memory.enabled`: Memory protocol activation
- `performance.unified_classification`: Classification mode

---

## Future Optimizations

### Potential Enhancements

1. **Prompt Caching**: Cache assembled prompts for repeated patterns
2. **Context Compression**: More aggressive context summarization for large ledgers
3. **Parallel Reason**: Multi-goal Reason calls in parallel (Layer 3)
4. **Adaptive Token Budgets**: Dynamic budget allocation based on goal complexity
5. **LLM Call Batching**: Batch multiple Reason calls when goals are independent

### RFC Alignment

- RFC-000: System conceptual design
- RFC-001: Core modules architecture
- RFC-200: Layer 2 agentic execution
- RFC-104: Context XML injection
- RFC-203: Working memory integration
- RFC-207: Message type separation (Layer 2)
- RFC-207: CoreAgent message optimization (Layer 1)
- RFC-603: Action specificity enhancement

---

## Conclusion

Soothe's LLM communication architecture demonstrates sophisticated separation of concerns across three layers, with strategic LLM calls optimized for classification, reasoning, and execution. The middleware-driven prompt optimization, bounded context projections, and thread isolation patterns ensure efficient token usage while maintaining comprehensive context for the orchestrator.

Key strengths:
- **Hierarchical delegation**: Clear boundaries between layers
- **Context isolation**: Prevents contamination across execution waves
- **Middleware flexibility**: Dynamic prompt adjustment without code changes
- **Streaming architecture**: Progressive result display with nested visibility
- **Evidence accumulation**: Structured information flow from execution to reasoning
- **Message separation** (RFC-207, RFC-207): SystemMessage for context, HumanMessage for tasks

This architecture enables Soothe to handle complex multi-step goals with bounded LLM context windows while maintaining full cognitive context continuity across threads and restarts.

---

**Document Status**: Analysis Updated (Layer 1/Layer 2 Message Flow)
**Generated**: 2026-04-09 by Claude Code
**Last Updated**: 2026-04-09 (Added comprehensive Layer 1/Layer 2 message flow analysis)
**Reviewed**: Pending human review
# Context Management Design: Volatility-Tiered Prompt Architecture

> Date: 2026-05-08
> Status: Draft

## Problem

The current prompt architecture has three issues:

1. **Cache-unfriendly structure**: Dynamic content (date, execution hints, per-turn memories) is mixed with static content (identity, policies, tool schemas) in the system prompt. Anthropic's prompt caching works at the content-block level within a single message — when any block changes, subsequent blocks lose their cache hit. Volatile content placed before or between static blocks breaks caching for everything that follows.

2. **Message duplication**: AgentLoop's `loop_messages` ledger and CoreAgent's checkpoint message history contain overlapping content. CoreAgent `AIMessage` responses are re-recorded as `LoopAIMessage` in the ledger. Plan-phase projections and checkpoint recovery both pay the cost of this duplication.

3. **Muddy semantics**: Memory, RAG documents, and dynamic context are injected into the system prompt alongside behavioral instructions. The LLM cannot distinguish persistent directives from per-turn context, and dialogue semantics are polluted — retrieved knowledge looks like system-level authority rather than supplemental information.

## Design

### 1. CoreAgent System Prompt — Two Tiers, Volatility-Ordered

The system prompt is a single `SystemMessage` with multiple content blocks ordered from least volatile to most volatile. Static blocks cache for the entire session; semi-static blocks cache across goals within a session.

#### Static Tier (session-stable)

These blocks rarely or never change during a session. They form the cache-friendly prefix.

| # | Block | XML Tag | Content | Source |
|---|-------|---------|---------|--------|
| 1 | Agent identity + behavioral rules | (plain text) | Name, guidelines (concise answers, multi-step plans, obstacle handling, never reference internal architecture, maintain context, respect CLAUDE.md/AGENTS.md) | `_DEFAULT_SYSTEM_PROMPT` / `_MEDIUM_SYSTEM_PROMPT` |
| 2 | Tool orchestration guide | (plain text) | Shell, file ops, surgical edit, data, goals, research, subagent guides + key rules | `_TOOL_ORCHESTRATION_GUIDE` |
| 3 | Execution policies | `<EXECUTION_POLICIES>` | Step granularity, filesystem discovery, first-wave constraints | `execution_policies.xml` fragment |
| 4 | Subagent routing directive | `<SUBAGENT_ROUTING_DIRECTIVE>` | When user explicitly requests a subagent (`/browser`, `/claude`, etc.) — force `task` tool usage | Conditionally injected |
| 5 | Agent loop output contract | `<AGENT_LOOP_OUTPUT_CONTRACT>` | Wrap-up limits for tool/subagent results | Conditionally injected when `current_decision` exists |

#### Semi-Static Tier (goal-stable)

These blocks change infrequently — at most once per goal or when the workspace context shifts. They sit after the static tier so the static prefix stays cached.

| # | Block | XML Tag | Content | Source |
|---|-------|---------|---------|--------|
| 6 | Workspace rules | `<WORKSPACE_RULES>` | "Use file tools against this directory. Don't ask for paths. Inspect immediately for architecture goals." | Inline in builder |
| 7 | Workspace metadata | `<WORKSPACE>` | Root path, VCS presence, branch, main branch, layout preview, README excerpt | `build_soothe_workspace_section()` |
| 8 | Environment | `<ENVIRONMENT>` | Platform, shell, OS version, model, knowledge cutoff | `build_soothe_environment_section()` |
| 9 | Memory summary | `<MEMORY_SUMMARY>` | User persona, long-term preferences, retrieved semi-static facts (up to 5 items, 200 chars each) | `_build_memory_section()` — long-term memories only |
| 10 | Context projection | `<CONTEXT_PROJECTION>` | Projected context entries when context tools are triggered | `_build_context_section()` |
| 11 | Thread context | `<THREAD>` | Thread ID, conversation turns, active goals, current plan | `build_soothe_thread_section()` — complex only |
| 12 | Protocol summary | `<PROTOCOLS>` | Active protocols (memory, planner, policy) with type and stats | `build_soothe_protocols_section()` — complex only |
| 13 | Scenario guidance | (plain text) | Architecture analysis, research synthesis, thread continuation, quiz — intent-driven guides | `_build_scenario_section()` |

#### What is NOT in the system prompt

All per-turn volatile content is removed from the system prompt:

- **Date/time** — moves to `<CONTEXT_INFO>` in the user message envelope
- **Execution hints** — moves to `<EXECUTION_HINTS>` in the user message envelope
- **Per-turn recalled memories** — moves to `<RETRIEVED_KNOWLEDGE>` in the user message envelope
- **Current goal context** — moves to `<CURRENT_GOAL>` in the user message envelope

This ensures the system prompt is cache-stable across the entire session (static tier) or across goals (semi-static tier). The only cache-invalidating changes are workspace shifts, memory updates, or environment changes — all of which are inherently infrequent.

### 2. User Message Envelope

Every `LoopHumanMessage` sent to CoreAgent follows a standard XML envelope. The envelope groups per-turn dynamic content into semantically distinct sections, keeping dialogue semantics clean.

```xml
<DYNAMIC_CONTEXT>
  <CURRENT_GOAL>
    Goal text and progress summary
  </CURRENT_GOAL>
  <EXECUTION_HINTS>
    Step-specific guidance from AgentLoop (previously appended by ExecutionHintsMiddleware)
  </EXECUTION_HINTS>
  <CONTEXT_INFO>
    <timestamp>2026-05-08T14:30:00Z</timestamp>
    <workspace_state>lightweight diff summary for this turn (uncommitted changes, staged files)</workspace_state>
    <date>2026-05-08</date>
  </CONTEXT_INFO>
</DYNAMIC_CONTEXT>

<RETRIEVED_KNOWLEDGE>
  <MEMORY>
    Per-turn recalled memories (short-term, situational recall — distinct from
    the long-term MEMORY_SUMMARY in the system prompt)
  </MEMORY>
  <RAG_DOCS>
    Per-turn retrieved documents
  </RAG_DOCS>
</RETRIEVED_KNOWLEDGE>

<USER_QUERY>
  Actual user message or orchestration instruction
</USER_QUERY>
```

**Design rationale for the split:**

- `<DYNAMIC_CONTEXT>` contains operational state the LLM needs to act correctly this turn (what goal, what hints, what time).
- `<RETRIEVED_KNOWLEDGE>` contains supplemental information the LLM may reference but should not treat as directive — it is retrieved, not prescribed.
- `<USER_QUERY>` is the actual dialogue content. The LLM's response addresses this section; the other sections provide context.

**Memory split semantics:**

- **System prompt `<MEMORY_SUMMARY>`**: Long-term user persona, persistent preferences, semi-static facts. These change rarely and cache well. The LLM should treat these as authoritative background.
- **User message `<MEMORY>`**: Per-turn situational recall — things remembered from recent conversations that are relevant to the current query. These change every turn and should not pollute the system prompt's cache boundary.

### 3. Complete AgentLoop Ledger

The `loop_messages` ledger becomes a complete record of the entire AgentLoop conversation across all phases — not just execute steps.

**Ledger records all phases:**

| Phase | `LoopHumanMessage.phase` | `LoopAIMessage.phase` | Recorded in ledger | Injected into CoreAgent thread |
|-------|--------------------------|------------------------|-------------------|-------------------------------|
| plan-assess | `"plan_assess"` | `"plan_assess"` | Yes | **No** |
| plan-generate | `"plan_generate"` | `"plan_generate"` | Yes | **No** |
| execute | `"execute_step"` | `"execute_step"` | Yes | Yes |

**Why record plan-phase messages in the ledger:**

1. **Cache maximization**: Prior plan-assess and plan-generate turns from previous iterations appear in the ledger portion of subsequent plan prompts. This increases the unchanged prefix between plan calls — the model sees its own prior reasoning as native message turns, and they cache.
2. **Complete audit trail**: The ledger is the single source of truth for the full AgentLoop conversation. Checkpoint recovery, debugging, and observability all benefit from a complete history.
3. **Iteration continuity**: When the planner re-assesses after an execute wave, it sees its own prior assessment and plan as preceding turns, not as a flattened summary.

**CoreAgent isolation**: When building messages for CoreAgent execution, ledger projection filters to `phase="execute_step"` only. Plan-phase messages are excluded — CoreAgent never sees planning reasoning in its thread. This keeps CoreAgent's message history focused on tool execution and prevents planning internals from leaking into tool-call context.

### 4. AgentLoop Plan Prompt Structure

The Plan phase prompt follows the same volatility-tiered philosophy, with the complete ledger as the message history.

#### System Prompt (static + semi-static)

| # | Block | XML Tag | Volatility |
|---|-------|---------|------------|
| 1 | Plan assess instructions | `<PLAN_ASSESS>` | Static |
| 2 | Plan generate instructions | `<PLAN_GENERATE>` | Static (generate phase only) |
| 3 | Execution policies | `<EXECUTION_POLICIES>` | Static (generate phase only) |
| 4 | Workspace rules | `<WORKSPACE_RULES>` | Semi-static |
| 5 | Follow-up policy | `<FOLLOW_UP_POLICY>` | Semi-static |
| 6 | Environment | `<ENVIRONMENT>` | Semi-static |
| 7 | Workspace metadata | `<WORKSPACE>` | Semi-static (placed last for cache boundary) |

#### Message List Structure (cache-maximized)

Prior conversation is injected as native message turns in the message list (not as XML inside the user message). The complete ledger — including prior plan-assess, plan-generate, and execute pairs — forms the shared prefix between calls.

**Message list layout (iteration 2 example):**

```
[0]  SystemMessage         — static instructions + semi-static context
[1]  LoopHumanMessage      — ledger: plan-assess user (iteration 1)
[2]  LoopAIMessage         — ledger: plan-assess AI response (iteration 1)
[3]  LoopHumanMessage      — ledger: plan-generate user (iteration 1)
[4]  LoopAIMessage         — ledger: plan-generate AI response (iteration 1)
[5]  LoopHumanMessage      — ledger: execute step input (iteration 1)
[6]  LoopAIMessage         — ledger: execute step output (iteration 1)
[7]  LoopHumanMessage      — ledger: execute step input (iteration 1)
[8]  LoopAIMessage         — ledger: execute step output (iteration 1)
...                         — all prior ledger pairs (projected/capped)
[N]  LoopHumanMessage      — plan-context user message (volatile)
```

**Plan-context user message** (the final message, different per call):

```xml
<GOAL_PROGRESS>
  Goal: <goal text>
  Execute iteration: 3/10
</GOAL_PROGRESS>

<PLAN_STEP_ID_HINT>
  Next step indices start at 05...
</PLAN_STEP_ID_HINT>

<PLAN_DAG_CONTEXT>
  Total steps: 8, Completed: 4, Ready: 05,06
</PLAN_DAG_CONTEXT>

<CONTEXT_INFO>
  <timestamp>2026-05-08T14:30:00Z</timestamp>
  <date>2026-05-08</date>
</CONTEXT_INFO>
```

**Cache behavior:**

- **Within an iteration** (plan-assess → plan-generate): The system prompt and all ledger turns [0..N-1] are identical — full cache hit on the prefix. Only the final user message changes.
- **Across iterations**: Ledger grows with new execute pairs (plus the prior iteration's plan turns). The existing prefix still caches; only new turns and the final user message are uncached.
- **Prior plan reasoning caches**: Because plan-assess and plan-generate turns are in the ledger, the planner sees its own previous reasoning as cached message turns — not as a summary that must be re-processed every iteration.
- `<PRIOR_CONVERSATION>` is eliminated — prior thread messages are injected as real `LoopHumanMessage`/`LoopAIMessage` turns in the ledger portion, preserving dialogue semantics and cache boundaries.

### 5. Message Dedup Mechanism

**Current state**: AgentLoop's `loop_messages` and CoreAgent's checkpoint messages contain duplicate content. When the Executor wraps a CoreAgent `AIMessage` into a `LoopAIMessage`, the content is duplicated. Plan-phase projections and checkpoint recovery both pay for this.

**Solution — reference-based dedup**:

- `LoopHumanMessage` gains `core_agent_message_id: str | None`
- `LoopAIMessage` gains `core_agent_message_id: str | None`
- When the Executor wraps CoreAgent responses into ledger entries, it records the original message ID
- Ledger projection skips messages whose `core_agent_message_id` matches a message already present in CoreAgent's thread state
- CoreAgent continues to own its own message history — the ledger is a parallel index with orchestration metadata, not a replacement

This preserves both stores (no data loss, no architectural upheaval) while eliminating redundant content when projecting for plan prompts or recovering from checkpoints.

### 6. Data Flow

```
User input
  |
  +-- Memory recall (parallel) ----> recalled_memories (short-term)
  +-- Context projection -----------> context_projection
  |
  v
AgentLoop (Plan phase)
  |
  +-- System prompt: static instructions + semi-static workspace/memory
  +-- Complete ledger as native human/AI turns (plan + execute phases from prior iterations)
  +-- User message: goal progress + plan hints + context info
  |
  v  Plan LLM response
  |
  +-- Record plan-assess or plan-generate user/AI pair in ledger
  +-- Plan-phase messages NOT injected into CoreAgent thread
  |
  v
AgentLoop (Execute phase)
  |
  +-- Build LoopHumanMessage envelope (execute-step phase):
  |     <DYNAMIC_CONTEXT>  goal + hints + timestamp
  |     <RETRIEVED_KNOWLEDGE> memory + RAG
  |     <USER_QUERY> orchestration instruction
  |
  v
CoreAgent.astream(envelope)
  |
  +-- System prompt (two tiers):
  |     Static: identity + tools + policies + directives
  |     Semi-static: workspace rules + workspace + environment + memory summary + context + thread + protocols
  +-- User message: the envelope above
  +-- CoreAgent thread receives ONLY execute-phase ledger messages
  |
  v
CoreAgent response (AIMessage)
  |
  +-- Wrapped into LoopAIMessage(phase="execute_step") with core_agent_message_id
  +-- Appended to loop_messages ledger
  |
  v
Checkpoint save (complete loop_messages ledger + CoreAgent state)
```

### 7. Migration Path

The change can be implemented incrementally:

1. **Add `core_agent_message_id` fields** to `LoopHumanMessage` and `LoopAIMessage`. Backward-compatible — `None` by default, existing serialized messages deserialize without error.

2. **Expand ledger to record plan phases**. After plan-assess and plan-generate LLM calls, record the user/AI pairs into `loop_messages` with `phase="plan_assess"` / `phase="plan_generate"`. Update ledger projection for CoreAgent to filter `phase="execute_step"` only. Update plan-phase ledger projection to include all phases (plan + execute).

3. **Restructure CoreAgent system prompt** in `SystemPromptOptimizationMiddleware._get_prompt_for_complexity()`. Reorder blocks into static → semi-static tiers. Remove date line and execution hints from the system prompt.

4. **Introduce the user message envelope** in the Executor's `_build_batch_human_messages()`. Move volatile content (goal context, execution hints, per-turn memory, date/time) from the system prompt into the envelope.

5. **Restructure Plan prompt** in `PromptBuilder.build_plan_messages()`. Move `<GOAL_PROGRESS>` and date/time out of the system message and into the plan-context user message. Replace `<PRIOR_CONVERSATION>` XML injection with native message turns in the message list — prior thread messages become `LoopHumanMessage`/`LoopAIMessage` pairs in the ledger portion. The complete ledger (including plan-phase turns from prior iterations) is now the shared prefix.

6. **Wire dedup in ledger projection**. Skip messages with `core_agent_message_id` that match CoreAgent's thread state. This is the last step since it depends on the new fields being populated.

### 8. Open Questions

- **Per-turn vs. session memory threshold**: What determines whether a recalled memory goes into `<MEMORY_SUMMARY>` (system prompt) vs. `<MEMORY>` (user envelope)? Current heuristic: items tagged as "persona" or "preference" → system; items recalled by semantic similarity to the current query → user envelope. Formalize this in MemoryProtocol.
- **Semi-static tier cache invalidation**: When workspace branch changes or memory is updated, the semi-static tier invalidates. Should we detect this and rebuild only the affected blocks, or is a full system prompt rebuild acceptable (simpler, still caches the static tier)?
- **RAG docs format**: The `<RAG_DOCS>` section is currently a placeholder. The actual format depends on the vector store backend and retrieval pipeline, which is a separate design concern.
- **Ledger growth with plan phases**: Recording plan-assess and plan-generate turns in the ledger increases its size each iteration. The existing `PlanPromptLedgerConfig` caps (max messages, max chars per message, max total chars) apply to the full ledger projection. Should plan-phase messages have separate/different caps than execute-phase messages, or does the unified cap work well enough?

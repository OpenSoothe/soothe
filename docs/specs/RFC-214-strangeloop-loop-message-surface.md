# RFC-214: Volatility-Tiered Prompt Architecture & Unified Message Ledger

**RFC**: 214
**Title**: Volatility-Tiered Prompt Architecture & Unified Message Ledger
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-05-03
**Updated**: 2026-05-13
**Dependencies**: RFC-100 (CoreAgent Runtime), RFC-206 (Prompt Architecture), RFC-104 (Dynamic System Context), RFC-207 (Thread Lifecycle & Goal Context), RFC-203 (StrangeLoop State & Memory), RFC-803 (StrangeLoop Checkpoint Backend), RFC-218 (Checkpoint Tree), RFC-217 (Goal Context Management)
**Related**: RFC-211 (Tool Result Shaping), RFC-213 (StrangeLoop Reasoning Quality), RFC-220 (LangGraph Agent Loop Orchestrator), RFC-614 (Streaming Messaging)

---

## Abstract

StrangeLoop orchestration currently maintains context through multiple parallel encoding paths, mixes volatile and static content in system prompts (breaking prompt caching), and duplicates messages between the ledger and CoreAgent checkpoints. This RFC addresses three problems with a unified design:

1. **Cache-unfriendly prompt structure**: Dynamic content (date, execution hints, per-turn memories) is interleaved with static content (identity, policies, tool schemas) in the system prompt, preventing prompt-cache hits on stable prefixes.

2. **Fragmented and duplicated context**: The Plan phase receives context from multiple disjoint sources (evidence strings, XML excerpts, LangGraph message replay, working memory). The same subagent output appears in multiple encodings that can diverge.

3. **Muddy semantics**: Memory, RAG documents, and dynamic context are injected into the system prompt alongside behavioral instructions. The LLM cannot distinguish persistent directives from per-turn context.

**Solution**:

- **Volatility-tiered prompt architecture**: System prompts are split into a static tier (session-stable, maximum cache hits) and a semi-static tier (goal-stable). All per-turn volatile content moves to a structured user message envelope.
- **Complete StrangeLoop ledger**: All orchestration turns — plan-assess, plan-generate, and execute-step — are recorded in a single `loop_messages` ledger. Plan-phase messages are excluded from CoreAgent's thread.
- **User message envelope**: A standard XML envelope carries per-turn dynamic content (goal context, execution hints, retrieved knowledge, user query) in semantically distinct sections.
- **Reference-based dedup**: Ledger messages carry `core_agent_message_id` to reference CoreAgent message history without duplicating content.

---

## Motivation

### Problem 1: Cache-Unfriendly Prompt Structure

Anthropic's prompt caching works at the content-block level within a single message. When any block changes, subsequent blocks lose their cache hit. The current system prompt interleaves volatile content (date line, execution hints, per-turn memories) with static content (identity, policies, tool schemas):

```
[System: identity + policies + tools + ENVIRONMENT + WORKSPACE + memory + date + hints]
```

Every turn, the date line and execution hints change, invalidating the cache for everything that follows — including the tool schemas and policies that never change.

### Problem 2: Fragmented and Duplicated Context

The Plan phase receives context from multiple disjoint sources:

- `PromptBuilder` assembling goal and evidence fragments
- `LoopState.step_results` storing raw execution outputs (legacy `CONCRETE EVIDENCE`)
- `plan_conversation_excerpts` with XML-wrapped excerpts (legacy `<PRIOR_CONVERSATION>`)
- `StateManager.derive_plan_conversation` reconstructing conversations from execution history
- LangGraph `messages` channel containing full transcripts with tool traffic

Execute persists traces into Pydantic records (`ReasonStepRecord`, `ActWaveRecord`, `StepExecutionRecord`) while CoreAgent maintains full LangGraph transcripts. This fragmentation causes:

**Duplication and Drift**: The same subagent output appears in multiple encodings (act checkpoint strings, evidence blocks, `<PRIOR_CONVERSATION>` XML, CoreAgent `messages`). Each encoding path can diverge.

**Ambiguous Step Identity**: Step outcomes are not first-class objects. Orchestration uses aggregated `AIMessage` / delegate-final heuristics. No explicit `LoopAIMessage` tied to `step_id`.

**Checkpoint Fidelity Issues**: Loop-typed messages must round-trip through LangGraph serde. Allowlist drift can deserialize messages as plain `dict` payloads. Loss of type information breaks the "Loop message" invariant.

**Prompt Cost Inefficiency**: Plan prompts grow with redundant encodings. Multiple representations of the same content increase token costs without improving reasoning quality.

### Problem 3: Muddy Semantics

Memory, RAG documents, and dynamic context are injected into the system prompt alongside behavioral instructions. The LLM cannot distinguish persistent directives from per-turn context, and dialogue semantics are polluted — retrieved knowledge looks like system-level authority rather than supplemental information. Memory items placed as system content are treated as prescriptive rather than referential.

---

## Guiding Principles

### P1: Volatility-Ordered Content Blocks

Content blocks within a message are ordered from least volatile to most volatile. Static blocks (identity, policies, tool schemas) form a cache-friendly prefix that rarely changes. Semi-static blocks (workspace, memory summary) change infrequently. Volatile content (date, execution hints, per-turn memory) is never in the system prompt.

### P2: Ledger Records All Orchestration Turns

The ledger captures all orchestration-visible conversation:
- **plan-assess** phase: assessment user prompts and AI responses
- **plan-generate** phase: plan generation user prompts and AI responses
- **execute-step** phase: step execution turns (human inputs, AI outcomes)
- Special flows: synthesis, thread checks, goal completion

Each turn is marked with `phase` for filtering. CoreAgent receives only execute-step messages (see §3.1 for how dependent steps ground predecessor output on isolated branch checkpoints).

### P3: Ledger as Authoritative Plan Context

No separate "synthetic transcript" for Plan phase:
- Plan reads directly from the message ledger
- No duplicate encoding paths
- No legacy reconstruction heuristics

### P4: CoreAgent Transcript as Implementation Detail

LangGraph checkpoints remain for tool execution, resume capability, and debugging. StrangeLoop orchestration does NOT require:
- Replaying full tool subgraphs for Plan reasoning
- Reading LangGraph `messages` channel for context

### P5: Semantic Separation of Context Types

- **System prompt**: Persistent directives and semi-static background (identity, policies, workspace rules, long-term memory summary). The LLM treats these as authoritative instructions.
- **User message envelope (leading) `<CURRENT_GOAL>` + `<USER_QUERY>`**: The active goal text and the step instruction for this turn. Placed first so the model sees intent and task before auxiliary context.
- **User message envelope `<DYNAMIC_CONTEXT>`**: Per-turn operational context only (execution hints when present, `<CONTEXT_INFO>` with timestamp, date, response-language hint, and optional loop iteration / workspace snapshot). Separated from the leading blocks by a `--- Context ---` delimiter for scanning and cache-friendly grouping.
- **User message envelope `<RETRIEVED_KNOWLEDGE>`**: Supplemental information (per-turn memories, RAG documents). The LLM may reference these but should not treat them as directives.

---

## Target Design

### 1. CoreAgent System Prompt — Two Tiers, Volatility-Ordered

The system prompt is a single `SystemMessage` with multiple content blocks ordered from least volatile to most volatile. Static blocks cache for the entire session; semi-static blocks cache across goals within a session.

#### Static Tier (session-stable)

These blocks rarely or never change during a session. They form the cache-friendly prefix.

| # | Block | XML Tag | Content | Source |
|---|-------|---------|---------|--------|
| 1 | Agent identity + behavioral rules | (plain text) | Name, guidelines (concise answers, multi-step plans, obstacle handling, never reference internal architecture, maintain context, respect CLAUDE.md/AGENTS.md) | `_DEFAULT_SYSTEM_PROMPT` / `_MEDIUM_SYSTEM_PROMPT` |
| 2 | Tool orchestration guide | (plain text) | Shell, file ops, surgical edit, data, goals, research, subagent guides + key rules | `_TOOL_ORCHESTRATION_GUIDE` |
| 3 | Execution policies | `<EXECUTION_POLICIES>` | Step granularity, filesystem discovery, first-wave constraints | `execution_policies.xml` fragment |
| 4 | Subagent routing directive | `<SUBAGENT_ROUTING_DIRECTIVE>` | When user explicitly requests a subagent — force `task` tool usage | Conditionally injected |
| 5 | Agent loop output contract | `<STRANGE_LOOP_OUTPUT_CONTRACT>` | Wrap-up limits for tool/subagent results | Conditionally injected when `current_decision` exists |

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

- **Date/time** → moves to `<CONTEXT_INFO>` inside `<DYNAMIC_CONTEXT>` in the user message envelope
- **Execution hints** → moves to `<EXECUTION_HINTS>` inside `<DYNAMIC_CONTEXT>` in the user message envelope
- **Per-turn recalled memories** → moves to `<RETRIEVED_KNOWLEDGE>` in the user message envelope
- **Current goal context** → moves to `<CURRENT_GOAL>` at the **start** of the user message envelope (not nested under `<DYNAMIC_CONTEXT>`). Any legacy trailing ` (iteration N/M)` suffix on the stored goal string is stripped so `<CURRENT_GOAL>` contains only the user's goal text.

The system prompt is cache-stable across the entire session (static tier) or across goals (semi-static tier). The only cache-invalidating changes are workspace shifts, memory updates, or environment changes — all inherently infrequent.

### 2. User Message Envelope

Every `LoopHumanMessage` sent to CoreAgent follows a standard XML envelope. **Goal and step instruction come first**; **secondary per-turn context** (hints, timestamps, language hint) is grouped after a fixed delimiter so the model reads task-before-metadata and prompt prefixes stay stable.

```xml
<CURRENT_GOAL>
  Goal text (verbatim user goal; no iteration suffix)
</CURRENT_GOAL>

<USER_QUERY>
  Actual user message or orchestration instruction
</USER_QUERY>

--- Context ---

<DYNAMIC_CONTEXT>
  <EXECUTION_HINTS>
    Step-specific guidance from StrangeLoop (previously appended by ExecutionHintsMiddleware); omitted when empty
  </EXECUTION_HINTS>
  <CONTEXT_INFO>
    <timestamp>2026-05-08T14:30:00+00:00</timestamp>
    <date>2026-05-08</date>
    <response_language_hint>...</response_language_hint>
    <workspace_state>lightweight diff summary for this turn (optional)</workspace_state>
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
```

**Slash-skill goals:** When the orchestration goal was expanded from a ``/skill:`` line, ``LoopState.goal_user_submission`` holds that original line. Execute-step and plan-context envelopes then repeat the short trailing user text inside ``<USER_PRIMARY_QUERY>`` before ``<FULL_GOAL_AND_SKILL_CONTEXT>`` (the long composed skill prompt). Plain goals without a slash-skill submission keep a single flat ``<CURRENT_GOAL>`` / ``Goal:`` line layout.

`<RETRIEVED_KNOWLEDGE>` is optional and may be omitted when there is nothing to inject for that turn. When present, it follows `<DYNAMIC_CONTEXT>` (same overall human message).

**Memory split semantics:**

- **System prompt `<MEMORY_SUMMARY>`**: Long-term user persona, persistent preferences, semi-static facts. These change rarely and cache well. The LLM treats these as authoritative background.
- **User message `<MEMORY>`**: Per-turn situational recall — things remembered from recent conversations relevant to the current query. These change every turn and must not pollute the system prompt's cache boundary.

### 3. Complete StrangeLoop Ledger

The `loop_messages` ledger is a complete record of the entire StrangeLoop conversation across all phases — not just execute steps.

**Ledger records all phases:**

| Phase | `LoopHumanMessage.phase` | `LoopAIMessage.phase` | Recorded in ledger | Injected into CoreAgent thread |
|-------|--------------------------|------------------------|-------------------|-------------------------------|
| plan-assess | `"plan_assess"` | `"plan_assess"` | Yes | **No** |
| plan-generate | `"plan_generate"` | `"plan_generate"` | Yes | **No** |
| execute-step | `"execute_step"` | `"execute_step"` | Yes | Yes |

**Why record plan-phase messages in the ledger:**

1. **Cache maximization**: Prior plan-assess and plan-generate turns from previous iterations appear in the ledger portion of subsequent plan prompts. This increases the unchanged prefix between plan calls — the model sees its own prior reasoning as native message turns, and they cache.
2. **Complete audit trail**: The ledger is the single source of truth for the full StrangeLoop conversation. Checkpoint recovery, debugging, and observability all benefit from a complete history.
3. **Iteration continuity**: When the planner re-assesses after an execute wave, it sees its own prior assessment and plan as preceding turns, not as a flattened summary.

**CoreAgent isolation**: When building messages for CoreAgent execution, ledger projection filters to `phase="execute_step"` only. Plan-phase messages are excluded — CoreAgent never sees planning reasoning in its thread. **Parallel branch checkpoints** (§3.1) use a fresh isolated namespace per step; predecessor output for **dependent steps within the same goal** is delivered only via the `PRIOR STEP EVIDENCE` section inside the current execute envelope — not by replaying prior Human/AI ledger rows into the graph input (which would duplicate the same AI body). **Loop-continuation bootstrap** (RFC-225) is the exception: it still replays prior-goal `execute_step` ledger rows when no dependent-step envelope exists.

**Ledger Structure:**

The ledger contains ONLY orchestration-visible messages in adjacent pairs:
- Each `LoopHumanMessage` immediately followed by its `LoopAIMessage`
- Both messages in pair share same `step_id` (for execute-step phase)
- Both messages in pair share same `iteration` (for plan phases)
- Order: plan-assess pair → plan-generate pair → execute step A pair → step B pair → ...
- NO tool messages, NO internal reasoning traces, NO subgraph traffic

### 3.1 Parallel execute branches and LangGraph checkpoint isolation

When several steps run in one wave with **independent** LangGraph checkpoints per step, the runtime uses a **derived** `thread_id` for CoreAgent (for example `{logical_thread}__step_{step_id}`) so each step’s checkpoint stays isolated from siblings. A new namespace starts with an **empty** CoreAgent message list even though the orchestration ledger (`LoopState.loop_messages`) already holds prior execute turns on the **logical** thread.

**Requirement:** Dependency-ordered work must still see completed predecessor **execute** evidence without sibling cross-talk.

#### Dependent steps (same goal, DAG `dependencies`)

The executor builds CoreAgent input as a **single** execute-step envelope:

1. **Current envelope only:** `LoopHumanMessage` with `GOAL`, optional `PRIOR STEP EVIDENCE`, and `EXECUTION HINTS` (see §2). Predecessor bodies are built from the latest transitive-predecessor `LoopAIMessage` rows in `loop_messages`, or from `StepResult` when ledger text is missing, via `build_prior_step_evidence()` (capped at 4000 characters with ellipsis truncation).
2. **No ledger replay:** The executor does **not** deep-copy predecessor Human/AI ledger rows into the graph input. Replaying those rows while also embedding the same AI text under `PRIOR STEP EVIDENCE` duplicates predecessor content (observed as ~2× token cost and confused step boundaries in production traces).

The authoritative ledger remains unchanged — plan-assess, plan-generate, and synthesis still read full `loop_messages`.

#### Loop-continuation bootstrap (`continue_loop=True`, no dependencies)

When a new goal continues a prior loop (RFC-225), the first bootstrap step has no `dependencies` and no `PRIOR STEP EVIDENCE` envelope section. The executor sends a **single** execute envelope whose `PRIOR GOAL COMPLETION` section carries the prior goal’s synthesized completion report (from checkpoint `goal_completion` or ledger `phase=goal_completion` AI rows). Prior-goal `execute_step` Human/AI ledger rows are **not** replayed into CoreAgent input — the completion report is the authoritative continuation context.

When `continue` has actionable recommendations in that report, `plan_assess` may escalate to `plan_generate` instead of bootstrap (RFC-226).

`StepResult` and ledger appends continue to use the **logical** `thread_id`; only the LangGraph stream/checkpoint namespace may use the derived id.

### 4. StrangeLoop Plan Prompt Structure

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

Prior conversation is injected as native message turns in the message list (not as XML inside the user message). The complete ledger — including prior plan-assess, plan-generate, and execute-step pairs — forms the shared prefix between calls.

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

**Plan-context user message** (the final message, different per call). For slash-skill goals (when the original user line was ``/skill:…``), ``<GOAL_PROGRESS>`` may wrap ``<USER_PRIMARY_QUERY>``, ``Execute iteration``, and ``<FULL_GOAL_AND_SKILL_CONTEXT>`` instead of a single ``Goal:`` line — same semantics as execute-step.

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

### 5. Execute Phase Contract

**Batch Execution Model:**

StrangeLoop may execute multiple steps in one CoreAgent invocation ("wave") for latency efficiency. The ledger records each step's turn individually.

**Input to CoreAgent (Batch):**

StrangeLoop sends N `LoopHumanMessage` instances, one per step, each using the user message envelope format:

```python
LoopHumanMessage(
    content=ENVELOPE_TEMPLATE.format(
        dynamic_context=...,
        retrieved_knowledge=...,
        user_query="Step A: Query database for user records"
    ),
    thread_id="<user_thread>",
    iteration=<current_iteration>,
    goal_summary="<goal_text>",
    phase="execute_step",
    step_id="step_a_uuid"
)
```

**Output Processing and Ledger Recording:**

When batch execution completes, StrangeLoop:

1. Collects all `AIMessage` instances from the stream
2. Identifies the final `AIMessage` for each step as the user-visible outcome
3. Promotes each final `AIMessage` to a `LoopAIMessage` keyed by `step_id`
4. Records N `(LoopHumanMessage, LoopAIMessage)` pairs in ledger

**Message Selection Rule:** The final `AIMessage` in the stream is the step outcome. Default rule suffices for 95% of cases; explicit markers (`metadata["step_id"]`, `metadata["is_outcome"]`) are added when execution semantics require.

**Partial Failure Handling:**

If batch execution fails mid-stream:
- Completed steps: ledger records full pairs
- Failed step: ledger records pair with error outcome
- Unstarted steps: ledger records skip messages OR omitted (configurable)

### 6. Reference-Based Message Dedup

**Current problem**: StrangeLoop's `loop_messages` and CoreAgent's checkpoint messages contain overlapping content. When the Executor wraps a CoreAgent `AIMessage` into a `LoopAIMessage`, the content is duplicated. Plan-phase projections and checkpoint recovery both pay for this.

**Solution — reference-based dedup:**

- `LoopHumanMessage` gains `core_agent_message_id: str | None`
- `LoopAIMessage` gains `core_agent_message_id: str | None`
- When the Executor wraps CoreAgent responses into ledger entries, it records the original message ID
- Ledger projection skips messages whose `core_agent_message_id` matches a message already present in CoreAgent's thread state
- CoreAgent continues to own its own message history — the ledger is a parallel index with orchestration metadata, not a replacement

This preserves both stores (no data loss, no architectural upheaval) while eliminating redundant content when projecting for plan prompts or recovering from checkpoints.

### 7. Checkpoint Persistence

**StrangeLoop checkpoints** (SQLite / PostgreSQL per RFC-803) persist:

**Metadata Fields:**
- Loop status, thread health metrics
- Goal metadata: `goal_id`, `goal_text`, status, iteration counters
- Plan metadata: latest plan state, reasoning, next actions
- Step metadata: ordered `StepAction` records with lifecycle status

**Loop Ledger Field:**
```python
loop_messages: list[LoopHumanMessage | LoopAIMessage]  # Ordered, unbounded, adjacent pairs
```

**Persistence Requirements:**
1. Serialized using LangGraph serde (canonical allowlist path)
2. Round-trip must preserve types, NOT deserialize as `dict`
3. Ledger is append-only during execution (no retroactive edits)
4. Adjacent Human-AI pairs: each Human message followed by its AI response
5. Unbounded growth: no truncation, no summarization in the ledger itself (projection applies caps at consumption time)

**Legacy fields removed:**
- `reason_history` — replaced by plan-phase ledger entries
- `act_history` — replaced by execute-step ledger entries
- `StepExecutionRecord.output` string blobs — replaced by `LoopAIMessage`
- `derive_plan_conversation()` — replaced by ledger projection

---

## Data Flow

```
User input
  |
  +-- Memory recall (parallel) ----> recalled_memories (short-term)
  +-- Context projection -----------> context_projection
  |
  v
StrangeLoop (Plan-assess phase)
  |
  +-- System prompt: static instructions + semi-static workspace/memory
  +-- Complete ledger as native human/AI turns (all phases from prior iterations)
  +-- User message: goal progress + plan hints + context info
  |
  v  Plan LLM response
  |
  +-- Record plan-assess user/AI pair in ledger (phase="plan_assess")
  +-- Plan-assess messages NOT injected into CoreAgent thread
  |
  v
StrangeLoop (Plan-generate phase)
  |
  +-- System prompt: same static instructions + EXECUTION_POLICIES + PLAN_GENERATE
  +-- Complete ledger (now including plan-assess pair from this iteration)
  +-- User message: goal progress + plan hints + context info
  |
  v  Plan LLM response
  |
  +-- Record plan-generate user/AI pair in ledger (phase="plan_generate")
  +-- Plan-generate messages NOT injected into CoreAgent thread
  |
  v
StrangeLoop (Execute phase)
  |
  +-- Build LoopHumanMessage envelope (phase="execute_step"):
  |     <CURRENT_GOAL> + <USER_QUERY>  (task first)
  |     --- Context --- + <DYNAMIC_CONTEXT>  hints + CONTEXT_INFO
  |     <RETRIEVED_KNOWLEDGE> memory + RAG (optional)
  |
  v
CoreAgent.astream(messages)
  |
  +-- System prompt (two tiers):
  |     Static: identity + tools + policies + directives
  |     Semi-static: workspace rules + workspace + environment + memory summary + context + thread + protocols
  +-- Message list: execute-step ledger projection (see §3); on **parallel branch** namespaces,
  |     dependent steps: single current envelope with `PRIOR STEP EVIDENCE` (§3.1);
  |     loop-continuation bootstrap: optional prior-goal ledger replay then envelope
  +-- CoreAgent thread (per checkpoint namespace) receives only that projection + envelope — never plan-phase rows
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

---

## Gap Analysis (Current Implementation → Target)

### G1: Batched Execution Not Properly Recorded in Ledger

**Current**: One aggregated `LoopHumanMessage` for multiple steps. No per-step `step_id` pairing.

**Target**: N `LoopHumanMessage` instances (one per step) with envelope format. N `(LoopHumanMessage, LoopAIMessage)` pairs keyed by `step_id`.

### G2: Step Outcomes Not Stored as LoopAIMessage

**Current**: Outcomes are string blobs (`StepResult.to_evidence_string()`). No first-class `LoopAIMessage` in persisted state.

**Target**: Extract final `AIMessage` per step. Promote to `LoopAIMessage` with `step_id`. Persist in `loop_messages` ledger field.

### G3: Plan Context Assembled from Multiple Parallel Sources

**Current**: `PromptBuilder._build_human_message` concatenates goal, `CONCRETE EVIDENCE`, `working_memory`, `<PRIOR_CONVERSATION>`, previous assessment.

**Target**: Plan reads directly from `loop_messages` ledger (all phases). System prompt contains only static + semi-static content. `<PRIOR_CONVERSATION>` eliminated — prior thread messages are native ledger turns.

### G4: StrangeLoop Checkpoint Schema Missing Message Ledger

**Current**: `GoalExecutionRecord` stores `reason_history` and `act_history`. No `loop_messages` field.

**Target**: `GoalExecutionRecord` stores `loop_messages: list[LoopHumanMessage | LoopAIMessage]`. Legacy fields removed.

### G5: CoreAgent Checkpoint Dependency in Plan

**Current**: Plan indirectly depends on overlapping content from LangGraph state.

**Target**: Plan reads only from StrangeLoop ledger. LangGraph checkpoints remain for CoreAgent resume/debug only.

### G6: Serde Allowlist Path Mismatch

**Current**: Allowlist paths don't match implementation paths. Messages deserialize as `dict`.

**Target**: Fix allowlist paths. Round-trip preserves types.

### G7: Plan Phase Turns Not in Ledger

**Current**: Plan turns are generic `HumanMessage`/`AIMessage`, not `LoopHumanMessage`/`LoopAIMessage`. Plan reasoning not captured in ledger.

**Target**: `LoopHumanMessage(phase="plan_assess")` / `LoopAIMessage(phase="plan_assess")` and `LoopHumanMessage(phase="plan_generate")` / `LoopAIMessage(phase="plan_generate")`. All plan turns in ledger.

### G8: Special Flows Outside Ledger Model

**Current**: Synthesis, thread checks, and parallel branches historically used ad hoc context (e.g. empty branch checkpoints without predecessor execute history).

**Target**: `LoopAIMessage(phase="goal_completion")`, `LoopHumanMessage(phase="thread_check")`. All orchestration turns in ledger. **Parallel branches:** dependent steps receive predecessor output only inside the current envelope’s `PRIOR STEP EVIDENCE` block (§3.1); loop-continuation bootstrap may still replay prior-goal execute rows; logical ledger remains canonical.

### G9: Volatile Content in System Prompt Breaks Caching

**Current**: Date line, execution hints, and per-turn memories are appended to the system prompt. Every turn invalidates the cache for the entire prompt suffix.

**Target**: Volatile content moves to user message envelope. System prompt contains only static + semi-static tiers. Cache hits on the stable prefix across turns.

### G10: Execution Hints Injected via Middleware Suffix

**Current**: `ExecutionHintsMiddleware` appends hints to `state['system_prompt']` as a suffix. `SystemPromptOptimizationMiddleware._append_execution_hints_suffix()` copies this onto the system prompt.

**Target**: Execution hints move to `<EXECUTION_HINTS>` in the user message envelope. No middleware suffix needed. `ExecutionHintsMiddleware` sets `state['execution_hints']` instead of mutating the system prompt.

### G11: Memory Injection Lacks Semantic Separation

**Current**: All recalled memories injected as `<memory>` XML in the system prompt (up to 5 items, 200 chars each). No distinction between long-term persona and situational recall.

**Target**: Long-term persona/preference memories → `<MEMORY_SUMMARY>` in system prompt (semi-static tier). Per-turn situational recall → `<MEMORY>` in user message envelope. Different cache volatility, different LLM treatment.

---

## Implementation Order

### Phase 1: Foundation

1. **Add `core_agent_message_id` fields** to `LoopHumanMessage` and `LoopAIMessage`. Backward-compatible — `None` by default.
2. **Fix serde allowlist** (G6): correct module paths.
3. **Add `loop_messages` field** to checkpoint schema (G4).

### Phase 2: Complete Ledger

4. **Expand ledger to record plan phases** (G7). After plan-assess and plan-generate LLM calls, record user/AI pairs into `loop_messages` with `phase="plan_assess"` / `phase="plan_generate"`.
5. **Update ledger projection for CoreAgent**: filter to `phase="execute_step"` only. Plan-phase messages excluded from CoreAgent thread.
6. **Update plan-phase ledger projection**: include all phases (plan + execute).

### Phase 3: Volatility-Tiered Prompts

7. **Restructure CoreAgent system prompt** in `SystemPromptOptimizationMiddleware._get_prompt_for_complexity()`. Reorder blocks into static → semi-static tiers. Remove date line and execution hints from the system prompt.
8. **Introduce the user message envelope** in the Executor's `_build_batch_human_messages()`. Move volatile content from the system prompt into the envelope.
9. **Restructure Plan prompt** in `PromptBuilder.build_plan_messages()`. Move `<GOAL_PROGRESS>` and date/time into the plan-context user message. Replace `<PRIOR_CONVERSATION>` with native ledger turns.
10. **Move execution hints to envelope** (G10). `ExecutionHintsMiddleware` sets `state['execution_hints']` → `<EXECUTION_HINTS>` in envelope.

### Phase 4: Memory Semantics

11. **Split memory injection** (G11). Long-term persona → `<MEMORY_SUMMARY>` in system prompt. Per-turn recall → `<MEMORY>` in user envelope.

### Phase 5: Dedup and Cleanup

12. **Wire dedup in ledger projection**. Skip messages with `core_agent_message_id` matching CoreAgent thread state.
13. **Remove legacy fields**: `reason_history`, `act_history`, `StepExecutionRecord.output`, `derive_plan_conversation()`, `CONCRETE EVIDENCE`, `<PRIOR_CONVERSATION>`, `working_memory` sections.

---

## Amendment: RFC-104 (Dynamic System Context)

**Change**: Add volatility-tiered ordering to `SystemPromptOptimizationMiddleware`.

- **Current**: Sections injected in order: base prompt → ENVIRONMENT → context/memory (conditional) → subagent directive → output contract → dynamic sections → date line.
- **New**: Sections injected in volatility order: base prompt + tool guides + policies (static) → workspace rules + workspace + environment + memory summary + context + thread + protocols (semi-static). Date line, execution hints, and per-turn memories removed from system prompt entirely.
- **Preserved**: All `<SOOTHE_*>` XML tags, classification-driven depth (minimal/medium/complex), `ToolTriggerRegistry` mechanism.
- **Removed from system prompt**: `_current_date_line()`, execution hints suffix, per-turn memory injection.

## Amendment: RFC-206 (Hierarchical Prompt Architecture)

**Change**: The `USER_TASK` layer is replaced by the user message envelope.

- **Current**: `USER_TASK` contains `<GOAL>`, `<PRIOR_CONVERSATION>`, `<EVIDENCE>` as XML inside a single human message.
- **New**: `USER_TASK` becomes the user message envelope: `<CURRENT_GOAL>` and `<USER_QUERY>` first, then `--- Context ---` and `<DYNAMIC_CONTEXT>` (hints + `<CONTEXT_INFO>`), optionally `<RETRIEVED_KNOWLEDGE>`. No `<PRIOR_CONVERSATION>` or `<EVIDENCE>` blocks — these are replaced by native ledger turns in the message list.
- **Preserved**: `SYSTEM_CONTEXT` layer (now split into static + semi-static tiers), `INSTRUCTIONS` layer, `PromptBuilder` fragment composition.
- **Removed**: `<PRIOR_CONVERSATION>`, `CONCRETE EVIDENCE`, `<EVIDENCE>`, `WORKING_MEMORY` sections from all prompt construction.

## Amendment: RFC-217 (Goal Context Management)

**Change**: `GoalContextManager.get_plan_context()` is superseded by the complete ledger.

- **Current**: `get_plan_context()` returns previous goal summaries as XML blocks injected into the Plan-phase user message. `get_execute_briefing()` returns a condensed briefing on thread switch.
- **New**: Plan-phase reads the complete ledger, which already contains prior plan-assess/plan-generate/execute-step turns from previous iterations. `get_plan_context()` is no longer needed — goal history is native ledger turns.
- **Preserved**: `get_execute_briefing()` (thread-switch injection into Execute phase). The ledger records orchestration turns but does not carry cross-thread goal summaries, so thread-switch briefings remain necessary.
- **Removed**: `get_plan_context()`, `inject_previous_goal_context()`, `<previous_goal>` XML blocks in Plan prompts.

---

## Non-Goals

1. **Replace LangGraph as CoreAgent Runtime**: LangGraph remains the execution runtime. The ledger model is an orchestration-level abstraction.
2. **Change User-Thread Streaming Wire Format**: RFC-614 handles streaming wire format. This RFC concerns internal orchestration state.
3. **Analytics Structures Are Derived, Not Primary**: Legacy fields (`reason_history`, `act_history`) are removed from persistence. Analytics tools derive them from ledger if needed.
4. **Address Subagent Output Quality**: RFC-213 handles reasoning quality. This RFC ensures consistent context propagation.
5. **Change Tool Result Shaping**: RFC-211 handles tool output compression. This RFC concerns message structure, not content compression.

---

## Success Criteria

### Functional Requirements

1. **Plan reconstruction without LangGraph dependency**: Given a resumed StrangeLoop checkpoint, Plan can reconstruct full context from ledger + metadata alone.
2. **Deterministic step-outcome pairing**: Each completed step has exactly one `(LoopHumanMessage, LoopAIMessage)` pair in the ledger.
3. **Serde round-trip fidelity**: Checkpoint serialization preserves `LoopHumanMessage`/`LoopAIMessage` types, never deserializes as `dict`.
4. **CoreAgent isolation**: CoreAgent input contains only `phase="execute_step"` messages (and the current-step envelope). Plan-phase reasoning never leaks into CoreAgent context. Parallel branch namespaces (§3.1) ground same-goal dependent steps via `PRIOR STEP EVIDENCE` in the envelope only — not by replaying predecessor ledger rows. Loop-continuation bootstrap may still prepend prior-goal execute ledger rows.

### Cache Performance

5. **Static tier cache hit rate**: The static tier (identity + tools + policies) achieves cache hits across 100% of turns within a session.
6. **Semi-static tier cache hit rate**: The semi-static tier achieves cache hits across all turns within a goal (cache invalidates only on workspace/memory changes).
7. **Plan prompt prefix reuse**: Between plan-assess and plan-generate within the same iteration, the message prefix (system + all prior ledger turns) is identical and fully cached.

### Prompt Efficiency

8. **Plan prompt token reduction**: Ledger-based Plan prompts use ~50% fewer tokens than legacy multi-source prompts (eliminates duplicate evidence strings, XML excerpts, overlapping LangGraph content).

---

## Changelog

| Date | Change |
|------|--------|
| 2026-05-03 | Initial draft (unified ledger model, execute-step contract, gap analysis G1-G8) |
| 2026-05-08 | Major revision: volatility-tiered prompt architecture, user message envelope, complete ledger with plan-assess/plan-generate phases, CoreAgent isolation, reference-based dedup, cache optimization, G9-G11, amendments to RFC-104/206/217 |
| 2026-05-13 | Execute-step envelope layout: `<CURRENT_GOAL>` + `<USER_QUERY>` before `--- Context ---` + `<DYNAMIC_CONTEXT>` (goal no longer nested under `<DYNAMIC_CONTEXT>`). `<CURRENT_GOAL>` omits iteration suffixes (stripped if present on stored goal text); execute iteration is not duplicated in the envelope — use ledger / message metadata. |
| 2026-05-13 | §3.1 **Parallel execute branches:** isolated LangGraph `thread_id` per concurrent step; executor injects transitive-predecessor `execute_step` ledger replay before the step envelope so branches see dependency history without sibling cross-talk. G8 target text aligned. |
| 2026-07-01 | §3.1 **Dependent-step deduplication:** same-goal DAG dependents ground predecessors only via `PRIOR STEP EVIDENCE` in the execute envelope (single Human message to CoreAgent). Removed predecessor Human/AI ledger replay for dependent steps — it duplicated AI bodies already embedded in the envelope. **Loop-continuation bootstrap** now uses envelope `PRIOR GOAL COMPLETION` only (no `prior_loop_execute_messages()` replay). G8 and success-criterion §4 aligned. |

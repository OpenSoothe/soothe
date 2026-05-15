# RFC-206: Hierarchical Prompt Architecture

**RFC**: 206  
**Title**: Hierarchical Prompt Architecture with System/User Separation  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-04-08  
**Dependencies**: RFC-200, RFC-100, RFC-214 (Volatility-Tiered Prompt Architecture & Unified Message Ledger)

## Abstract

This RFC defines a hierarchical prompt architecture that separates system context from user tasks using explicit XML container boundaries. The architecture addresses confusion issues where LLMs would process system metadata (environment/workspace XML) as user content, particularly for ambiguous requests like "translate to chinese". The design introduces a PromptBuilder API and modular fragment composition to ensure clear separation and prevent metadata-user content confusion.

## Motivation

### Current Problems

1. **Goal placement**: User's goal is buried in the middle of prompts, interleaved with system metadata and policies
2. **Metadata confusion**: LLMs sometimes translate or process system metadata (environment/workspace XML) when given ambiguous user requests
3. **Mixed concerns**: System context, user content, and execution instructions are intermixed without clear boundaries
4. **Ambiguity vulnerability**: No explicit separation between "system context" and "user task", leading to LLM confusion about what to process

### Proposed Solution

Implement a three-layer hierarchical structure with explicit XML containers:

```xml
<SOOTHE_PROMPT>
  <SYSTEM_CONTEXT>
    <!-- Static system metadata: environment, workspace, capabilities, policies -->
  </SYSTEM_CONTEXT>
  
  <USER_TASK>
    <!-- Dynamic user content: goal, prior conversation, evidence -->
  </USER_TASK>
  
  <INSTRUCTIONS>
    <!-- Task format and execution rules -->
  </INSTRUCTIONS>
</SOOTHE_PROMPT>
```

The hierarchical nesting makes it impossible for the LLM to confuse system metadata with user content.

---

## Architecture

### Hierarchical Structure

**Layer 1: SYSTEM_CONTEXT**
- Contains static system metadata providing execution context
- Never processed as user content (explicit container prevents this)
- Sections:
  - `<ENVIRONMENT>`: platform, shell, model, knowledge_cutoff
  - `<WORKSPACE>`: project root, git status, branch info (conditional)
  - `<CAPABILITIES>`: available tools and subagents
  - `<POLICIES>`: delegation rules, granularity rules, workspace rules

**Layer 2: USER_TASK**
- Contains dynamic user-specific content
- Goal is prominent at the top of this section
- Sections:
  - `<GOAL>`: the user's request
  - `<PRIOR_CONVERSATION>`: recent messages from thread (conditional)
  - `<EVIDENCE>`: step results from execution (conditional)

**Layer 3: INSTRUCTIONS**
- Contains output format and execution policies
- Defines how LLM should respond
- Sections:
  - `<OUTPUT_FORMAT>`: JSON schema for Reason response
  - `<EXECUTION_RULES>`: general execution policies

### Example Prompt

```xml
<SOOTHE_PROMPT>
  <SYSTEM_CONTEXT>
    <ENVIRONMENT version="1">
      <platform>Darwin</platform>
      <shell>/bin/zsh</shell>
      <model>coding-plan:kimi-k2.5</model>
      <knowledge_cutoff>2025-01</knowledge_cutoff>
    </ENVIRONMENT>

    <WORKSPACE version="1">
      <root>/Users/chenxm/Workspace/Soothe</root>
      <vcs present="true">
        <branch>develop</branch>
      </vcs>
    </WORKSPACE>

    <CAPABILITIES>
      explore, plan, research
    </CAPABILITIES>

    <POLICIES>
      <DELEGATION>Prefer one subagent delegation per step...</DELEGATION>
      <GRANULARITY>Prefer 1-3 concrete steps per decision...</GRANULARITY>
    </POLICIES>
  </SYSTEM_CONTEXT>

  <USER_TASK>
    <GOAL>translate to chinese</GOAL>

    <PRIOR_CONVERSATION>
      <user>who are you</user>
      <assistant>I'm Soothe, your AI assistant...</assistant>
    </PRIOR_CONVERSATION>
  </USER_TASK>

  <INSTRUCTIONS>
    <OUTPUT_FORMAT>
      Return JSON with status, goal_progress, decision fields...
    </OUTPUT_FORMAT>

    <EXECUTION_RULES>
      - Prioritize user content from PRIOR_CONVERSATION when goal references previous context
      - When goal is ambiguous, return status="continue" with clarification step
      - Never process SYSTEM_CONTEXT metadata as user task content
    </EXECUTION_RULES>
  </INSTRUCTIONS>
</SOOTHE_PROMPT>
```

---

## Module Design

### Directory Structure

```
packages/soothe/src/soothe/core/prompts/
├── __init__.py
├── builder.py              # PromptBuilder class
├── fragments/              # XML fragment templates
│   ├── instructions/       # plan_assess, plan_generate; execution_policies under system/policies/
│   └── ...
└── (see tree in repo; RFC-183 prefetch layout)
```

### PromptBuilder API

```python
class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Internal API for Soothe prompt construction.
    Not exposed to users for configuration.
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize builder with optional config."""
        self.config = config

    def build_reason_prompt(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext
    ) -> str:
        """Build hierarchical Reason prompt.

        Args:
            goal: User's goal description
            state: Current loop state with iteration, evidence
            context: Planning context with workspace, capabilities

        Returns:
            Complete hierarchical prompt string
        """

    def build_plan_prompt(
        self,
        goal: str,
        context: PlanContext
    ) -> str:
        """Build hierarchical planning prompt for initial plan creation."""
```

### Fragment Template Format

Fragments use Jinja2-style templating:

**Example: fragments/system/environment.xml**
```xml
<ENVIRONMENT version="1">
<platform>{{platform}}</platform>
<shell>{{shell}}</shell>
<os_version>{{os_version}}</os_version>
<model>{{model}}</model>
<knowledge_cutoff>{{knowledge_cutoff}}</knowledge_cutoff>
</ENVIRONMENT>
```

**Example: fragments/user/goal.xml**
```xml
<GOAL>{{goal}}</GOAL>
```

**Example: fragments/instructions/execution_rules.xml**
```xml
<EXECUTION_RULES>
- Prioritize user content from PRIOR_CONVERSATION when the goal references previous context
- When goal is incomplete or ambiguous, return status="continue" with a clarification step
- Never process SYSTEM_CONTEXT metadata as user task content
- Step descriptions must be concrete, tool-facing actions
</EXECUTION_RULES>
```

---

## Ambiguity Handling

### Decision Tree

```
User gives ambiguous request (e.g., "translate to chinese")
    ↓
Check PRIOR_CONVERSATION in USER_TASK?
    ├─ YES → Use most recent message as content to process
    └─ NO  → Return status="continue" with clarification step
              (e.g., "What content would you like me to translate?")
```

### Why This Works

1. **Container boundaries**: `<SYSTEM_CONTEXT>` explicitly marks metadata as non-user-content
2. **Execution rules**: Explicit prohibition on processing system metadata
3. **LLM training**: Hierarchical XML structure matches LLM training patterns
4. **Clear intent**: USER_TASK section makes user content unambiguous

---

## Integration

### LLMPlanner Refactor

**Before** (historical `simple.py`; superseded by `packages/soothe/src/soothe/core/agent_loop/core/planner.py`):
```python
async def reason(self, goal, state, context):
    prompt = self._build_reason_prompt(goal, state, context)
    response = await self._invoke(prompt)
    return parse_reason_response_text(response, goal)

def _build_reason_prompt(self, goal, state, context):
    # 200+ lines of prompt construction
    parts = []
    parts.append(build_shared_environment_workspace_prefix(...))
    parts.append(f"Goal: {goal}\n")
    # ... many more parts
    return "\n".join(parts)
```

**After**:
```python
class LLMPlanner:
    def __init__(self, model, config=None):
        self._model = model
        self._config = config
        self._prompt_builder = PromptBuilder(config)  # NEW

    async def reason(self, goal, state, context):
        prompt = self._prompt_builder.build_reason_prompt(goal, state, context)
        response = await self._invoke(prompt)
        return parse_reason_response_text(response, goal)
```

**Removed**:
- `build_loop_reason_prompt()` function
- All direct prompt construction logic from planner classes

---

## Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Separation** | Mixed metadata and user content | Hierarchical XML containers |
| **Goal placement** | Buried in middle | Prominent in USER_TASK section |
| **Ambiguity handling** | Confuses metadata with user content | Explicit boundaries prevent confusion |
| **Maintainability** | Monolithic prompt construction | Modular fragments with single responsibility |
| **Extensibility** | Hard to add sections | Easy to add new fragments |

---

## Testing

### Unit Tests

- Test each fragment renders correctly with various inputs
- Test PromptBuilder assembles fragments in correct order
- Test conditional sections (workspace, prior conversation, evidence)
- Test hierarchical structure is valid XML

### Integration Tests

- Test full prompt construction for various query types
- Test ambiguity handling (no prior conversation → clarification step)
- Verify goal appears in USER_TASK section
- Verify system metadata not processed as user content

---

## Migration

### Breaking Changes

- Direct callers of `build_loop_reason_prompt()` must update to use `PromptBuilder`
- No backward compatibility provided

### Affected Code

- `packages/soothe/src/soothe/core/agent_loop/core/planner.py` (LLMPlanner / RFC-604)
- `packages/soothe/src/soothe/core/prompts/builder.py` (PromptBuilder)
- Any tests that construct prompts directly

---

## Related Specifications

- **RFC-200**: Layer 2 Agentic Goal Execution
- **RFC-100**: Layer 1 CoreAgent Runtime
- **IG-133**: Avoid prior conversation duplication in Reason prompts
- **IG-134**: Layer 2 unified state checkpoint

---

## Changelog

**2026-05-13**:
- Aligned RFC-214 amendment example with execute-step envelope: `<CURRENT_GOAL>` + `<USER_QUERY>` first, then `--- Context ---` + `<DYNAMIC_CONTEXT>`; updated Key Changes item 3 accordingly.
- Execute-step `<CONTEXT_INFO>` documents timestamp, date, response-language hint, and optional workspace state only (no loop-iteration element in the envelope).

**2026-05-04**:
- Documented `instructions/` contents for plan phase: `plan_assess_instructions.xml`, `plan_generate_instructions.xml`; `execution_policies.xml` under `system/policies/` (IG-329 / IG-372). Removed obsolete `plan_execute_instructions.xml`.

**2026-04-08 (created)**:
- Initial RFC defining hierarchical prompt architecture
- Three-layer structure: SYSTEM_CONTEXT, USER_TASK, INSTRUCTIONS
- PromptBuilder API and modular fragment composition
- Ambiguity handling via explicit container boundaries

---

## Amendment: RFC-214 Volatility-Tiered Prompt Architecture

**Date**: 2026-05-08 (revised 2026-05-13 for execute-step envelope ordering)

RFC-214 supersedes the `USER_TASK` layer composition defined in this RFC. The changes are:

### USER_TASK Layer → User Message Envelope

The `USER_TASK` layer's internal structure changes from a single XML block to the user message envelope defined in RFC-214 §2:

**Before (this RFC):**
```xml
<USER_TASK>
  <GOAL>translate to chinese</GOAL>
  <PRIOR_CONVERSATION>
    <user>who are you</user>
    <assistant>I'm Soothe, your AI assistant...</assistant>
  </PRIOR_CONVERSATION>
  <EVIDENCE>step results...</EVIDENCE>
</USER_TASK>
```

**After (RFC-214):**
```xml
<CURRENT_GOAL>goal text</CURRENT_GOAL>

<USER_QUERY>
  Actual user message or orchestration instruction
</USER_QUERY>

--- Context ---

<DYNAMIC_CONTEXT>
  <EXECUTION_HINTS>step-specific guidance</EXECUTION_HINTS>
  <CONTEXT_INFO>timestamp, date, response_language_hint, workspace state</CONTEXT_INFO>
</DYNAMIC_CONTEXT>

<RETRIEVED_KNOWLEDGE>
  <MEMORY>per-turn recalled memories</MEMORY>
  <RAG_DOCS>per-turn retrieved documents</RAG_DOCS>
</RETRIEVED_KNOWLEDGE>
```

### Key Changes

1. **`<PRIOR_CONVERSATION>` eliminated**: Prior thread messages are now native `LoopHumanMessage`/`LoopAIMessage` turns in the ledger portion of the message list, not XML inside the user message. This maximizes prompt-cache prefix reuse between plan-assess and plan-generate calls.

2. **`<EVIDENCE>` eliminated**: Step results are now `LoopAIMessage` entries in the ledger. No separate evidence blocks.

3. **`<GOAL>` → `<CURRENT_GOAL>`**: Goal text moves to a leading `<CURRENT_GOAL>` block (before `<USER_QUERY>`), not nested under `<DYNAMIC_CONTEXT>`. Per-turn hints and timestamps stay under `<DYNAMIC_CONTEXT>` after a `--- Context ---` delimiter.

4. **New sections**: `<EXECUTION_HINTS>`, `<CONTEXT_INFO>`, `<RETRIEVED_KNOWLEDGE>`, `<USER_QUERY>` — all per-turn volatile content that was previously mixed into the system prompt.

### SYSTEM_CONTEXT Layer → Volatility-Tiered System Prompt

The `SYSTEM_CONTEXT` layer is restructured into two tiers per RFC-214 §1:

- **Static tier**: Identity, behavioral rules, tool orchestration guide, execution policies, directives (session-stable, maximum cache hits)
- **Semi-static tier**: Workspace rules, workspace metadata, environment, memory summary, context projection, thread context, protocol summary (goal-stable)

Volatile content (date line, execution hints, per-turn memories) is removed from `SYSTEM_CONTEXT` entirely.

### INSTRUCTIONS Layer

Unchanged. Execution policies remain in the system prompt's static tier. Plan-phase instructions remain in the plan system prompt.

### Preserved from This RFC

- Hierarchical XML container boundaries for LLM comprehension
- `PromptBuilder` API and modular fragment composition
- Ambiguity handling principle (never process system metadata as user content)
- Classification-driven depth adaptation
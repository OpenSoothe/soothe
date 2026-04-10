# RFC-206: Hierarchical Prompt Architecture

**RFC**: 0206  
**Title**: Hierarchical Prompt Architecture with System/User Separation  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-04-08  
**Dependencies**: RFC-201, RFC-100

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
      browser, claude, research
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
src/soothe/prompts/
├── __init__.py
├── builder.py              # PromptBuilder class
├── fragments/              # XML fragment templates
│   ├── system/
│   │   ├── environment.xml
│   │   ├── workspace.xml
│   │   ├── capabilities.xml
│   │   └── policies/
│   │       ├── delegation.xml
│   │       ├── granularity.xml
│   │       └── workspace_rules.xml
│   ├── user/
│   │   ├── goal.xml
│   │   ├── prior_conversation.xml
│   │   └── evidence.xml
│   └── instructions/
│       ├── output_format.xml
│       └── execution_rules.xml
└── README.md
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

### SimplePlanner Refactor

**Before** (`src/soothe/cognition/planning/simple.py`):
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
class SimplePlanner:
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

- `src/soothe/cognition/planning/simple.py`
- `src/soothe/cognition/planning/claude.py` (if exists)
- Any tests that construct prompts directly

---

## Related Specifications

- **RFC-201**: Layer 2 Agentic Goal Execution
- **RFC-100**: Layer 1 CoreAgent Runtime
- **IG-133**: Avoid prior conversation duplication in Reason prompts
- **IG-134**: Layer 2 unified state checkpoint

---

## Changelog

**2026-04-08 (created)**:
- Initial RFC defining hierarchical prompt architecture
- Three-layer structure: SYSTEM_CONTEXT, USER_TASK, INSTRUCTIONS
- PromptBuilder API and modular fragment composition
- Ambiguity handling via explicit container boundaries
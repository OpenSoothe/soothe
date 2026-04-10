# Soothe Prompt Architecture Design

**Status:** Draft
**Created:** 2026-04-08
**Author:** Claude (via brainstorming)

## Problem Statement

Current prompt construction in Soothe has several issues:

1. **Goal placement**: The user's goal is buried in the middle of the prompt, interleaved with system metadata and policies
2. **Metadata confusion**: When users give ambiguous requests like "translate to chinese", the LLM sometimes translates the system metadata (environment/workspace XML) instead of user content
3. **Mixed concerns**: System context, user content, and execution instructions are intermixed without clear boundaries
4. **Ambiguity vulnerability**: No explicit separation between "system context" and "user task", leading to LLM confusion about what content to process

## Goals

- Clear hierarchical separation between system context and user task
- Prominent goal placement that can't be confused with metadata
- Internal modular composition for maintainability
- Robust handling of ambiguous user requests
- Prevent LLM from processing system metadata as user content

## Architecture Overview

The prompt uses a three-layer hierarchical structure with explicit section markers:

```xml
<SOOTHE_PROMPT>
  <SYSTEM_CONTEXT>    <!-- Static system information -->
    <ENVIRONMENT>...</ENVIRONMENT>
    <WORKSPACE>...</WORKSPACE>
    <CAPABILITIES>...</CAPABILITIES>
    <POLICIES>...</POLICIES>
  </SYSTEM_CONTEXT>

  <USER_TASK>         <!-- Dynamic user-specific content -->
    <GOAL>...</GOAL>
    <PRIOR_CONVERSATION>...</PRIOR_CONVERSATION>
    <EVIDENCE>...</EVIDENCE>
  </USER_TASK>

  <INSTRUCTIONS>      <!-- Task format and output specification -->
    <OUTPUT_FORMAT>...</OUTPUT_FORMAT>
    <EXECUTION_RULES>...</EXECUTION_RULES>
  </INSTRUCTIONS>
</SOOTHE_PROMPT>
```

**Key principle**: Everything in `<SYSTEM_CONTEXT>` is metadata/context. Everything in `<USER_TASK>` is user content that could be processed. The hierarchical nesting makes it impossible for the LLM to confuse the two.

## Component Design

### 1. Hierarchical Structure

**SYSTEM_CONTEXT Section**:
- Contains static system metadata that provides execution context
- Never processed as user content (explicit container prevents this)
- Includes: environment info, workspace details, available capabilities, system policies

**USER_TASK Section**:
- Contains dynamic user-specific content
- Goal is prominent at the top of this section
- Includes: goal, prior conversation, evidence from execution
- This section is what the LLM should focus on for user requests

**INSTRUCTIONS Section**:
- Contains output format specification and execution rules
- Defines how the LLM should respond
- Includes: JSON schema for Reason response, general execution policies

### 2. Layered Composition

Prompts are built from modular XML fragments stored internally:

```
src/soothe/prompts/
├── __init__.py
├── builder.py              # PromptBuilder class
├── fragments/              # XML fragment files
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
└── README.md               # Internal documentation
```

**Fragment responsibilities**:
- Each fragment has single responsibility (e.g., environment.xml only renders environment metadata)
- Fragments are loaded and composed by PromptBuilder
- Not user-configurable - internal implementation detail

### 3. PromptBuilder API

```python
# src/soothe/prompts/builder.py
class PromptBuilder:
    """Composes hierarchical prompts from fragments.

    Internal API for Soothe prompt construction.
    Not exposed to users for configuration.
    """

    def __init__(self, config: SootheConfig | None = None):
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
            state: Current loop state with iteration, evidence, etc.
            context: Planning context with workspace, capabilities, etc.

        Returns:
            Complete hierarchical prompt string
        """
        parts = ["<SOOTHE_PROMPT>"]

        # System context
        parts.append("<SYSTEM_CONTEXT>")
        parts.append(self._render_environment())
        if context.workspace:
            parts.append(self._render_workspace(context))
        parts.append(self._render_capabilities(context))
        parts.append(self._render_policies())
        parts.append("</SYSTEM_CONTEXT>")

        # User task
        parts.append("<USER_TASK>")
        parts.append(f"<GOAL>{goal}</GOAL>")
        if context.recent_messages:
            parts.append(self._render_prior_conversation(context))
        if state.step_results:
            parts.append(self._render_evidence(state))
        parts.append("</USER_TASK>")

        # Instructions
        parts.append("<INSTRUCTIONS>")
        parts.append(self._render_output_format())
        parts.append(self._render_execution_rules())
        parts.append("</INSTRUCTIONS>")

        parts.append("</SOOTHE_PROMPT>")
        return "\n".join(parts)

    def build_plan_prompt(self, goal: str, context: PlanContext) -> str:
        """Build hierarchical planning prompt."""
        # Similar structure for initial planning phase
        ...
```

### 4. Fragment Templates

**Example: system/environment.xml**
```xml
<ENVIRONMENT version="1">
<platform>{{platform}}</platform>
<shell>{{shell}}</shell>
<os_version>{{os_version}}</os_version>
<model>{{model}}</model>
<knowledge_cutoff>{{knowledge_cutoff}}</knowledge_cutoff>
</ENVIRONMENT>
```

**Example: instructions/execution_rules.xml**
```xml
<EXECUTION_RULES>
- Prioritize user content from PRIOR_CONVERSATION when the goal references previous context
- When goal is incomplete or ambiguous, return status="continue" with a clarification step
- Never process SYSTEM_CONTEXT metadata as user task content
- Step descriptions must be concrete, tool-facing actions
</EXECUTION_RULES>
```

### 5. Caller Integration

**SimplePlanner update** (`src/soothe/cognition/planning/simple.py`):
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

**ClaudePlanner update**: Similar integration with PromptBuilder

**Remove**:
- `build_loop_reason_prompt()` function (replaced by PromptBuilder)
- All direct prompt construction logic from planner classes

## Ambiguity Handling

When the user gives an ambiguous request (e.g., "translate to chinese"):

**Behavior**:
1. If PRIOR_CONVERSATION exists in USER_TASK: Use most recent message as content to process
2. If NO prior conversation: Return `status="continue"` with a step asking user to specify what to process
3. NEVER process SYSTEM_CONTEXT metadata as user content

**Why this works**:
- Hierarchical structure makes it explicit that SYSTEM_CONTEXT is not user content
- Execution rules explicitly prohibit processing metadata
- LLM sees clear container boundaries: "this is system info, this is user task"

## Data Flow

```
User Query
    ↓
UnifiedClassifier (routing)
    ↓
SimplePlanner.reason()
    ↓
PromptBuilder.build_reason_prompt()
    ↓
[SYSTEM_CONTEXT assembly] → [USER_TASK assembly] → [INSTRUCTIONS assembly]
    ↓
<SOOTHE_PROMPT>...</SOOTHE_PROMPT>
    ↓
LLM invocation
    ↓
Parsed ReasonResult
```

## Benefits

✅ **Clear separation**: Hierarchical XML makes system/user distinction explicit
✅ **Goal prominence**: Goal always in `<USER_TASK>` section, never buried
✅ **Maintainable**: Each fragment has single responsibility, easy to test
✅ **Extensible**: Adding new sections doesn't break existing structure
✅ **Ambiguity-proof**: Container boundaries prevent "translate the metadata" mistakes
✅ **No configuration burden**: Internal implementation, not exposed to users

## Implementation Tasks

1. Create `src/soothe/prompts/` module structure
2. Implement `PromptBuilder` class in `builder.py`
3. Create all fragment XML templates in `fragments/` subdirectories
4. Update `SimplePlanner` to use PromptBuilder
5. Update `ClaudePlanner` to use PromptBuilder
6. Remove `build_loop_reason_prompt()` from `simple.py`
7. Add unit tests for PromptBuilder and fragment rendering
8. Integration tests for full prompt construction

## Testing Strategy

**Unit tests**:
- Test each fragment renders correctly with various inputs
- Test PromptBuilder assembles fragments in correct order
- Test conditional sections (workspace, prior conversation, evidence)

**Integration tests**:
- Test full prompt construction for various query types
- Test ambiguity handling (no prior conversation → clarification step)
- Verify goal appears in USER_TASK section
- Verify system metadata not processed as user content

## Migration Notes

**Breaking change**: Direct callers of `build_loop_reason_prompt()` must update to use `PromptBuilder`.

**Affected code**:
- `src/soothe/cognition/planning/simple.py`
- `src/soothe/cognition/planning/claude.py` (if exists)
- Any tests that construct prompts directly

**No backward compatibility**: Clean break from old prompt construction approach.

## Related Work

- **RFC-201**: Layer 2 Agentic Goal Execution (Reason-Act loop)
- **IG-133**: Avoid prior conversation duplication in Reason prompts
- **IG-134**: Layer 2 unified state checkpoint (recent conversation logging)

## Open Questions

None - design validated through brainstorming process.

---

**Next steps**: Proceed to Platonic Coding Phase 1 RFC formalization.
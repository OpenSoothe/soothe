# Message Passing Architecture Design

**Date**: 2026-04-08
**Status**: Draft
**Scope**: Refactor prompt construction to use proper SystemMessage/HumanMessage separation

---

## Problem Statement

The current message passing architecture sends all context to the LLM as a single HumanMessage, despite clear conceptual separation between:

1. **System context** (environment, workspace, policies, instructions) - relatively static
2. **User task** (goal, evidence, working memory, iteration metadata) - dynamic per iteration

This creates three issues:

1. **Claude API best practices violation**: System context doesn't get proper SystemMessage weight and attention
2. **LLM response quality concern**: System instructions embedded in HumanMessage may not receive appropriate priority from the model
3. **Architectural clarity gap**: Code structure collapses two distinct layers into one message type, making the conceptual separation less explicit

---

## Design Goals

1. Follow Claude API best practices with proper SystemMessage/HumanMessage separation
2. Improve LLM response quality by giving system context proper architectural weight
3. Better architectural clarity where code structure mirrors conceptual separation
4. Minimal disruption - localized to prompt construction and message invocation
5. Maintain ecosystem compatibility with langchain message types and middleware hooks
6. Preserve conversation history handling and test coverage (900+ tests pass)

---

## Architecture Overview

### Message Structure

**Current**: Single HumanMessage containing all context

```
[HumanMessage(environment + workspace + policies + instructions + goal + evidence + ...)]
```

**New**: SystemMessage + HumanMessage separation

```
[SystemMessage] ← Environment, workspace, policies, instructions (static context)
[HumanMessage] ← Goal, iteration metadata, evidence, working memory, prior conversation (dynamic task)
```

### Message Content Mapping

| Section | Message Type | Content |
|---------|--------------|---------|
| `<ENVIRONMENT>` | SystemMessage | Platform, shell, model info, git status |
| `<WORKSPACE>` | SystemMessage | Workspace rules, thread context |
| `<POLICIES>` | SystemMessage | Delegation, granularity policies (XML fragments) |
| `<INSTRUCTIONS>` | SystemMessage | Output format, execution rules (XML fragments) |
| `<GOAL>` | HumanMessage | Goal statement, iteration metadata |
| `<PRIOR_CONVERSATION>` | HumanMessage | Previous messages (conditional) |
| `<EVIDENCE>` | HumanMessage | Step results, structured outcomes |
| `<WORKING_MEMORY>` | HumanMessage | Scratchpad excerpts |
| `<PREVIOUS_REASON>` | HumanMessage | Last assessment |
| `<COMPLETED_STEPS>` | HumanMessage | Step summaries |

**Removed**: `<WAVE_METRICS>` section - internal performance tracking not needed for LLM reasoning

### Key Decisions

1. **Section naming**: Remove `SOOTHE_` prefix from `<ENVIRONMENT>` and `<WORKSPACE>` - SystemMessage context makes the prefix redundant
2. **Wave metrics removal**: Internal metrics don't influence LLM reasoning, kept for logging/tracing only
3. **Static vs Dynamic split**: Environment/workspace/policies/instructions in SystemMessage (relatively static), everything else in HumanMessage (changes per iteration)
4. **Prior conversation**: Remains in HumanMessage as conditional section, logic unchanged

---

## Implementation Design

### Scope of Changes

**Files Modified**:
- `src/soothe/core/prompts/builder.py` - Return message list instead of string
- `src/soothe/cognition/planning/simple.py` - Pass message list to model invocation
- `src/soothe/core/prompts/context_xml.py` - Update XML tag names (remove SOOTHE_ prefix)
- Tests - Update assertions to check message structure

**Files Unchanged**:
- Agent factory (`_builder.py`, `_core.py`)
- Runner (`_runner_agentic.py`)
- Middleware stack (already handles message lists)
- State management (`LoopState`, checkpointing)
- Response parsing (still parses AIMessage.content as JSON)

---

### PromptBuilder Changes

#### Method Signature

**Current**:
```python
def build_reason_prompt(self, goal: str, state: LoopState, context: ReasonContext) -> str
```

**New**:
```python
def build_reason_messages(self, goal: str, state: LoopState, context: ReasonContext) -> List[BaseMessage]
```

#### Implementation Pattern

```python
from langchain_core.messages import SystemMessage, HumanMessage

def build_reason_messages(
    self,
    goal: str,
    state: LoopState,
    context: ReasonContext
) -> List[BaseMessage]:
    """Build SystemMessage + HumanMessage for Reason phase.

    Args:
        goal: User's goal statement.
        state: Current LoopState with iteration, evidence, working memory.
        context: ReasonContext with environment, workspace, capabilities.

    Returns:
        List of [SystemMessage, HumanMessage] to send to LLM.
    """
    system_content = self._build_system_message(state, context)
    human_content = self._build_human_message(goal, state, context)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content)
    ]

def _build_system_message(self, state: LoopState, context: ReasonContext) -> str:
    """Construct static context: environment, workspace, policies, instructions."""
    sections = []

    # Environment section
    if context.environment:
        sections.append(context.environment)

    # Workspace section
    if context.workspace:
        sections.append(self._build_workspace_section(context.workspace))

    # Policy fragments
    sections.append(self._load_fragment("delegation.xml"))
    sections.append(self._load_fragment("granularity.xml"))

    # Instruction fragments
    sections.append(self._load_fragment("output_format.xml"))
    sections.append(self._load_fragment("execution_rules.xml"))

    return "\n\n".join(sections)

def _build_human_message(self, goal: str, state: LoopState, context: ReasonContext) -> str:
    """Construct dynamic task: goal, evidence, working memory, prior conversation."""
    sections = []

    # Goal and iteration
    sections.append(self._build_goal_section(goal, state))

    # Prior conversation (conditional)
    if context.prior_conversation and self._should_show_prior_conversation(state):
        sections.append(self._build_prior_conversation_section(context))

    # Evidence from step_results
    if state.step_results:
        sections.append(self._build_evidence_section(state))

    # Working memory excerpt
    if state.working_memory_excerpt:
        sections.append(self._build_working_memory_section(state))

    # Previous reason assessment
    if state.previous_reason:
        sections.append(self._build_previous_reason_section(state))

    # Completed steps summary
    if state.completed_steps:
        sections.append(self._build_completed_steps_section(state))

    return "\n\n".join(sections)
```

#### Helper Methods

Move section construction into private methods (`_build_*_section`) for:
- `_build_workspace_section()` - Construct workspace rules
- `_build_goal_section()` - Goal statement + iteration metadata
- `_build_prior_conversation_section()` - Previous messages
- `_build_evidence_section()` - Step results
- `_build_working_memory_section()` - Scratchpad excerpts
- `_build_previous_reason_section()` - Last assessment
- `_build_completed_steps_section()` - Step summaries

Each method returns formatted XML section string.

---

### SimplePlanner Changes

**Current**:
```python
async def reason(self, goal: str, state: LoopState, context: ReasonContext) -> ReasonResult:
    prompt = self._prompt_builder.build_reason_prompt(goal, state, context)
    response = await self._invoke(prompt)
    return self._parse_response(response)

async def _invoke(self, prompt: str) -> str:
    response = await self._model.ainvoke([HumanMessage(content=prompt)])
    return response.content
```

**New**:
```python
async def reason(self, goal: str, state: LoopState, context: ReasonContext) -> ReasonResult:
    messages = self._prompt_builder.build_reason_messages(goal, state, context)
    response = await self._invoke_messages(messages)
    return self._parse_response(response)

async def _invoke_messages(self, messages: List[BaseMessage]) -> str:
    """Invoke model with message list instead of single prompt string."""
    response = await self._model.ainvoke(messages)
    return response.content
```

**Change**: Remove HumanMessage wrapping (already in message list), rename method for clarity.

---

### Context XML Changes

**File**: `src/soothe/core/prompts/context_xml.py`

**Current**: Uses `<SOOTHE_ENVIRONMENT>` and `<SOOTHE_WORKSPACE>` tags

**New**: Uses `<ENVIRONMENT>` and `<WORKSPACE>` tags

```python
def build_shared_environment_workspace_prefix(context: ReasonContext) -> str:
    """Build environment and workspace sections for SystemMessage."""
    sections = []

    # Environment section (no SOOTHE_ prefix)
    sections.append(f"<ENVIRONMENT>\n{context.environment_content}\n</ENVIRONMENT>")

    # Workspace section (no SOOTHE_ prefix)
    if context.workspace:
        sections.append(f"<WORKSPACE>\n{context.workspace_content}\n</WORKSPACE>")

    return "\n\n".join(sections)
```

---

### Test Strategy

#### Tests to Update

1. **Prompt structure tests** (`tests/unit/prompts/`):
   - Update assertions to check message list structure
   - Verify SystemMessage contains environment, workspace, policies, instructions
   - Verify HumanMessage contains goal, evidence, working memory, prior conversation

2. **SimplePlanner tests** (`tests/unit/cognition/planning/`):
   - Update mocks to expect message list instead of string
   - Update assertions on message types and content separation

3. **Integration tests**:
   - Should pass unchanged (behavior identical, just structure different)

#### Verification

Run `./scripts/verify_finally.sh` to ensure:
- Code formatting passes
- Linting passes (zero errors)
- All 900+ unit tests pass

---

### Edge Cases

1. **Empty SystemMessage**: Never happens - policies and instructions always present
2. **Empty HumanMessage**: Never happens - goal always present
3. **Prior conversation handling**: Conditional logic preserved - same conditions
4. **Checkpoint compatibility**: Messages ephemeral, not persisted in state

---

### Migration Path

**Step-by-Step Implementation**:

1. **Add new method**: Implement `build_reason_messages()` alongside existing `build_reason_prompt()`
2. **Update SimplePlanner**: Use new method, keep old method for compatibility
3. **Update tests**: Fix assertions incrementally
4. **Remove old method**: Clean up deprecated `build_reason_prompt()`
5. **Run verification**: `./scripts/verify_finally.sh`
6. **Update documentation**: RFC-206, IG-135, CLAUDE.md, docstrings

**Backward Compatibility**: Keep both methods temporarily during migration for incremental test updates.

---

## Architecture Benefits

### Claude API Best Practices ✅

- Proper SystemMessage/HumanMessage separation follows Anthropic's recommended patterns
- System context receives appropriate architectural weight in message structure

### LLM Response Quality ✅

- System instructions in SystemMessage get proper priority from model
- Clear separation helps model distinguish between rules/context and task/evidence

### Architectural Clarity ✅

- Code structure mirrors RFC-206 conceptual layers
- SystemMessage = Layer 1 static context
- HumanMessage = Layer 2 dynamic task
- Easier to understand and maintain

### Minimal Disruption ✅

- Changes localized to `builder.py` and `simple.py`
- Middleware stack unchanged (already handles message lists)
- Agent factory and runner unchanged
- State management unchanged
- Response parsing unchanged

### Ecosystem Compatibility ✅

- Uses langchain `SystemMessage` and `HumanMessage` types
- Compatible with middleware hooks (`awrap_model_call`)
- Works with existing langchain patterns

---

## Documentation Updates

**Files to Update**:

1. **RFC-206** (`docs/specs/RFC-206-prompt-architecture.md`):
   - Update message structure section
   - Reflect SystemMessage/HumanMessage separation
   - Update diagrams and examples

2. **IG-135** (`docs/impl/IG-135-prompt-architecture.md`):
   - Add implementation history entry
   - Document refactoring rationale and changes

3. **CLAUDE.md**:
   - Update architecture section if needed
   - Ensure module map reflects prompt builder role

4. **PromptBuilder docstrings**:
   - Document return type change to `List[BaseMessage]`
   - Add examples showing message structure

---

## Future Considerations

### Potential Follow-up Work

1. **Prompt caching**: SystemMessage is relatively static - could leverage Claude's prompt caching feature to reduce costs across iterations

2. **Dynamic SystemMessage sections**: Certain context might change between iterations (e.g., updated policies) - could implement SystemMessage refresh logic

3. **Conversation history accumulation**: Instead of embedding prior AIMessages in HumanMessage, could build full conversation history with accumulated message list

4. **Message compression**: For long-running agents with extensive evidence, could implement message compression/summarization strategies

These are **out of scope** for this refactoring but worth considering for future iterations.

---

## Success Criteria

1. All tests pass (900+ tests)
2. Linting passes with zero errors
3. Code formatting passes
4. SystemMessage contains environment, workspace, policies, instructions
5. HumanMessage contains goal, evidence, working memory, prior conversation
6. No behavior changes - LLM responses identical in structure and content
7. Documentation updated to reflect new architecture
8. Migration completed with backward compatibility during transition

---

## Summary

This refactoring improves the message passing architecture by introducing proper SystemMessage/HumanMessage separation that mirrors the conceptual layers in RFC-206. The changes are minimal and localized, maintaining ecosystem compatibility and test coverage while achieving better Claude API alignment, improved LLM response quality, and clearer architectural structure.
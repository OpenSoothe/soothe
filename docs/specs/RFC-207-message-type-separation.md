# RFC-207: SystemMessage/HumanMessage Separation

**RFC**: 0207
**Title**: Proper Message Type Separation for System and User Context
**Status**: Draft
**Kind**: Architecture Refinement
**Created**: 2026-04-08
**Dependencies**: RFC-206, RFC-201, RFC-100
**Replaces**: None (refines RFC-206 implementation)

## Abstract

This RFC refines RFC-206's hierarchical prompt architecture by introducing proper langchain message type separation. Instead of embedding all context in a single HumanMessage with XML containers, we split system context and user task into distinct SystemMessage and HumanMessage types. This follows Claude API best practices, improves LLM response quality, and provides better architectural clarity while maintaining RFC-206's conceptual layer separation.

## Motivation

### RFC-206 Foundation

RFC-206 established a three-layer hierarchical structure:
1. SYSTEM_CONTEXT (environment, workspace, policies)
2. USER_TASK (goal, evidence, prior conversation)
3. INSTRUCTIONS (output format, execution rules)

This solved metadata confusion issues through explicit XML container boundaries.

### Remaining Issues

RFC-206's implementation still sends everything as a single HumanMessage:

```python
# Current RFC-206 implementation
prompt = builder.build_reason_prompt(goal, state, context)  # Returns string
response = await model.ainvoke([HumanMessage(content=prompt)])
```

**Problems**:

1. **Claude API best practices violation**: System context doesn't receive proper SystemMessage weight and attention
2. **LLM response quality concern**: System instructions embedded in HumanMessage may not get appropriate priority
3. **Architectural clarity gap**: Code structure collapses distinct conceptual layers into one message type

### Proposed Solution

Use langchain's native message types to mirror RFC-206's conceptual separation:

```python
# New implementation
messages = builder.build_reason_messages(goal, state, context)  # Returns List[BaseMessage]
response = await model.ainvoke(messages)  # [SystemMessage, HumanMessage]
```

**Benefits**:
- SystemMessage for SYSTEM_CONTEXT + INSTRUCTIONS (static, rules-based)
- HumanMessage for USER_TASK (dynamic, task-specific)
- Follows Anthropic's recommended patterns
- Better architectural alignment with RFC-206 layers

---

## Specification

### Message Structure

**Message Types**:

| Message | RFC-206 Layer | Content |
|---------|---------------|---------|
| SystemMessage | SYSTEM_CONTEXT + INSTRUCTIONS | Environment, workspace, policies, output format, execution rules |
| HumanMessage | USER_TASK | Goal, iteration metadata, evidence, working memory, prior conversation, previous reason, completed steps |

**Section Mapping**:

| RFC-206 Section | Message Type | XML Tag |
|-----------------|--------------|---------|
| `<ENVIRONMENT>` | SystemMessage | `<ENVIRONMENT>` (no SOOTHE_ prefix) |
| `<WORKSPACE>` | SystemMessage | `<WORKSPACE>` (no SOOTHE_ prefix) |
| `<POLICIES>` | SystemMessage | `<POLICIES>` |
| `<INSTRUCTIONS>` | SystemMessage | `<INSTRUCTIONS>` |
| `<GOAL>` | HumanMessage | `<GOAL>` |
| `<PRIOR_CONVERSATION>` | HumanMessage | `<PRIOR_CONVERSATION>` |
| `<EVIDENCE>` | HumanMessage | `<EVIDENCE>` |
| `<WORKING_MEMORY>` | HumanMessage | `<WORKING_MEMORY>` |
| `<PREVIOUS_REASON>` | HumanMessage | `<PREVIOUS_REASON>` |
| `<COMPLETED_STEPS>` | HumanMessage | `<COMPLETED_STEPS>` |

**Removed Sections**:
- `<WAVE_METRICS>` - Internal performance tracking (tool call counts, subagent counts) not needed for LLM reasoning

### Key Design Decisions

1. **Section naming simplification**: Remove `SOOTHE_` prefix from `<ENVIRONMENT>` and `<WORKSPACE>` tags. SystemMessage context makes the prefix redundant.

2. **Wave metrics removal**: Internal execution metrics (tool calls, subagent tasks, wave duration) don't influence reasoning. Keep for LLMTracingMiddleware logging only.

3. **INSTRUCTIONS in SystemMessage**: Output format and execution rules are system-level directives, not task-specific content. Placing in SystemMessage gives them proper weight.

4. **Dynamic content in HumanMessage**: Evidence, working memory, prior conversation change each iteration - belongs with task context.

5. **Prior conversation handling**: Conditional logic unchanged from RFC-206. Included in HumanMessage when checkpoint access available.

---

## Implementation

### PromptBuilder API Change

**Current (RFC-206)**:
```python
def build_reason_prompt(
    self,
    goal: str,
    state: LoopState,
    context: ReasonContext
) -> str
```

**New (RFC-207)**:
```python
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage

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

    Note:
        SystemMessage contains RFC-206 SYSTEM_CONTEXT + INSTRUCTIONS layers.
        HumanMessage contains RFC-206 USER_TASK layer.
    """
    system_content = self._build_system_message(state, context)
    human_content = self._build_human_message(goal, state, context)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content)
    ]
```

### Helper Methods

**SystemMessage Construction**:
```python
def _build_system_message(self, state: LoopState, context: ReasonContext) -> str:
    """Construct static context: environment, workspace, policies, instructions.

    Maps RFC-206 SYSTEM_CONTEXT + INSTRUCTIONS layers to SystemMessage.
    """
    sections = []

    # Environment section (SYSTEM_CONTEXT)
    if context.environment:
        sections.append(context.environment)

    # Workspace section (SYSTEM_CONTEXT)
    if context.workspace:
        sections.append(self._build_workspace_section(context.workspace))

    # Policy fragments (SYSTEM_CONTEXT)
    sections.append(self._load_fragment("delegation.xml"))
    sections.append(self._load_fragment("granularity.xml"))

    # Instruction fragments (INSTRUCTIONS)
    sections.append(self._load_fragment("output_format.xml"))
    sections.append(self._load_fragment("execution_rules.xml"))

    return "\n\n".join(sections)
```

**HumanMessage Construction**:
```python
def _build_human_message(self, goal: str, state: LoopState, context: ReasonContext) -> str:
    """Construct dynamic task: goal, evidence, working memory, prior conversation.

    Maps RFC-206 USER_TASK layer to HumanMessage.
    """
    sections = []

    # Goal and iteration (USER_TASK)
    sections.append(self._build_goal_section(goal, state))

    # Prior conversation (USER_TASK, conditional)
    if context.prior_conversation and self._should_show_prior_conversation(state):
        sections.append(self._build_prior_conversation_section(context))

    # Evidence from step_results (USER_TASK)
    if state.step_results:
        sections.append(self._build_evidence_section(state))

    # Working memory excerpt (USER_TASK)
    if state.working_memory_excerpt:
        sections.append(self._build_working_memory_section(state))

    # Previous reason assessment (USER_TASK)
    if state.previous_reason:
        sections.append(self._build_previous_reason_section(state))

    # Completed steps summary (USER_TASK)
    if state.completed_steps:
        sections.append(self._build_completed_steps_section(state))

    return "\n\n".join(sections)
```

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

### Context XML Changes

**File**: `src/soothe/core/prompts/context_xml.py`

**Change**: Remove `SOOTHE_` prefix from XML tags

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

## Scope

### Files Modified

1. `src/soothe/core/prompts/builder.py`:
   - Add `build_reason_messages()` method
   - Add `_build_system_message()` helper
   - Add `_build_human_message()` helper
   - Add `_build_*_section()` helper methods
   - Deprecate `build_reason_prompt()` (keep temporarily for migration)

2. `src/soothe/backends/planning/simple.py`:
   - Update `reason()` to use `build_reason_messages()`
   - Rename `_invoke()` to `_invoke_messages()`
   - Remove HumanMessage wrapping logic

3. `src/soothe/core/prompts/context_xml.py`:
   - Update XML tags: `<SOOTHE_ENVIRONMENT>` → `<ENVIRONMENT>`
   - Update XML tags: `<SOOTHE_WORKSPACE>` → `<WORKSPACE>`

4. Tests:
   - Update prompt structure tests to check message list
   - Update assertions for message type separation
   - Update mocks for message list invocation

### Files Unchanged

- Agent factory (`_builder.py`, `_core.py`)
- Runner (`_runner_agentic.py`)
- Middleware stack (already handles message lists)
- State management (`LoopState`, checkpointing)
- Response parsing (still parses AIMessage.content as JSON)
- Fragment XML files (content unchanged, only section organization changes)

---

## Migration Strategy

### Backward Compatibility

Keep both methods temporarily:

```python
class PromptBuilder:
    def build_reason_prompt(self, goal: str, state: LoopState, context: ReasonContext) -> str:
        """Deprecated: Use build_reason_messages() instead."""
        messages = self.build_reason_messages(goal, state, context)
        # Concatenate for compatibility
        return "\n\n".join([m.content for m in messages])

    def build_reason_messages(self, goal: str, state: LoopState, context: ReasonContext) -> List[BaseMessage]:
        """New method: Returns proper message types."""
        # Implementation as specified above
```

### Migration Steps

1. Implement `build_reason_messages()` with backward-compatible `build_reason_prompt()` wrapper
2. Update SimplePlanner to use new method
3. Update tests incrementally (can use either method during transition)
4. Remove deprecated `build_reason_prompt()` once all tests updated
5. Run `./scripts/verify_finally.sh` (format, lint, tests)
6. Update documentation (RFC-206, IG-135, CLAUDE.md)

---

## Benefits

### Claude API Best Practices

✅ **Proper message type separation**: SystemMessage for system context, HumanMessage for user task
✅ **Anthropic patterns**: Follows recommended Claude API usage
✅ **System context weight**: Receives proper architectural attention

### LLM Response Quality

✅ **Instruction priority**: System instructions in SystemMessage get model attention
✅ **Clear separation**: Model distinguishes rules vs task
✅ **Better reasoning**: Appropriate message types help model understand context

### Architectural Clarity

✅ **Layer alignment**: Code structure mirrors RFC-206 conceptual layers
✅ **SystemMessage** = SYSTEM_CONTEXT + INSTRUCTIONS (Layer 1 + rules)
✅ **HumanMessage** = USER_TASK (Layer 2 dynamic task)
✅ **Maintainability**: Clear separation makes code easier to understand

### Minimal Disruption

✅ **Localized changes**: Only `builder.py`, `simple.py`, `context_xml.py`
✅ **Middleware unchanged**: Already handles message lists via `awrap_model_call`
✅ **Tests manageable**: Incremental migration with backward compatibility
✅ **Behavior unchanged**: LLM responses identical in content

### Ecosystem Compatibility

✅ **Langchain types**: Uses `SystemMessage`, `HumanMessage`, `BaseMessage`
✅ **Middleware hooks**: Compatible with `awrap_model_call` pattern
✅ **LLMTracingMiddleware**: Logs message count (already supports message lists)

---

## Testing

### Unit Tests

**Prompt Structure Tests** (`tests/unit/prompts/`):
- Verify `build_reason_messages()` returns `List[BaseMessage]` with length 2
- Verify first message is `SystemMessage` instance
- Verify second message is `HumanMessage` instance
- Verify SystemMessage contains environment, workspace, policies, instructions sections
- Verify HumanMessage contains goal, evidence, working memory sections
- Verify conditional sections (prior conversation, workspace) work correctly
- Verify XML tags: `<ENVIRONMENT>`, `<WORKSPACE>` (no SOOTHE_ prefix)

**SimplePlanner Tests** (`tests/unit/backends/planning/`):
- Update mocks to expect message list instead of string
- Verify `_invoke_messages()` receives message list
- Verify response parsing unchanged

### Integration Tests

**Agentic Loop Tests**:
- Run full agentic loop execution
- Verify Reason → Act cycle works with new message structure
- Verify evidence accumulation in HumanMessage
- Verify checkpoint handling unchanged
- Verify LLMTracingMiddleware logs message count correctly

### Verification

Run `./scripts/verify_finally.sh`:
- Format check passes
- Linting passes (zero errors)
- All 900+ unit tests pass
- Integration tests pass

---

## Edge Cases

1. **Empty SystemMessage**: Never occurs - policies and instructions always present
2. **Empty HumanMessage**: Never occurs - goal always present
3. **Prior conversation handling**: Conditional logic unchanged from RFC-206
4. **Checkpoint compatibility**: Messages are ephemeral (not persisted in LoopState)
5. **Middleware compatibility**: LLMTracingMiddleware already handles message lists via `awrap_model_call`

---

## Documentation Updates

1. **RFC-206**: Add note referencing RFC-207 as refinement
2. **IG-135**: Add implementation history entry for RFC-207 changes
3. **CLAUDE.md**: Update architecture section if needed
4. **PromptBuilder docstrings**: Document return type change, add message structure examples

---

## Future Considerations

### Potential Follow-up Work

1. **Prompt caching**: SystemMessage is relatively static across iterations - could leverage Claude's prompt caching feature for cost reduction

2. **Conversation history accumulation**: Instead of embedding prior AIMessages in HumanMessage section, build full conversation history with accumulated SystemMessage/HumanMessage/AIMessage list

3. **Dynamic SystemMessage refresh**: Certain context might change between iterations (e.g., workspace rules updated) - implement SystemMessage regeneration logic

4. **Message compression**: For long-running agents with extensive evidence, implement message compression/summarization to reduce token costs

These are **out of scope** for RFC-207 but worth considering for future iterations.

---

## Success Criteria

1. ✅ All 900+ tests pass
2. ✅ Linting passes with zero errors
3. ✅ Code formatting passes
4. ✅ SystemMessage contains: environment, workspace, policies, instructions
5. ✅ HumanMessage contains: goal, evidence, working memory, prior conversation, previous reason, completed steps
6. ✅ No behavior changes - LLM responses identical in structure and content
7. ✅ Wave metrics removed from prompts (kept in LLMTracingMiddleware)
8. ✅ XML tags: `<ENVIRONMENT>`, `<WORKSPACE>` (no SOOTHE_ prefix)
9. ✅ Documentation updated
10. ✅ Migration completed with backward compatibility

---

## Related Specifications

- **RFC-206**: Hierarchical Prompt Architecture (conceptual foundation)
- **RFC-201**: Layer 2 Agentic Goal Execution (Reason/Act loop)
- **RFC-100**: Layer 1 CoreAgent Runtime (BaseChatModel interface)
- **IG-135**: Prompt Architecture Implementation (RFC-206 implementation)
- **IG-136**: LLM Tracing Middleware (message logging support)

---

## Changelog

**2026-04-08 (created)**:
- Initial RFC defining SystemMessage/HumanMessage separation
- Refines RFC-206 implementation with proper message types
- Removes SOOTHE_ prefix from environment/workspace XML tags
- Removes wave metrics from LLM prompts
- Defines migration strategy with backward compatibility
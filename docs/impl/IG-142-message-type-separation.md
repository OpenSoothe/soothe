# IG-142: Message Type Separation (RFC-207)

**Status**: 🚧 In Progress
**Created**: 2026-04-08
**Author**: AI Agent
**Scope**: Prompt architecture refinement, message type separation
**RFC**: RFC-207
**Dependencies**: RFC-206 (implemented via IG-137)

---

## Summary

Implement RFC-207 SystemMessage/HumanMessage separation to refine RFC-206's prompt architecture. Split the single HumanMessage prompt into proper langchain message types: SystemMessage for system context (environment, workspace, policies, instructions) and HumanMessage for user task (goal, evidence, working memory, prior conversation).

---

## Motivation

RFC-206 established hierarchical prompt architecture with XML containers, but implementation still uses a single HumanMessage for all content. RFC-207 refines this to:

1. **Claude API Best Practices**: System context gets proper SystemMessage weight and attention
2. **LLM Response Quality**: System instructions receive appropriate priority from model
3. **Architectural Clarity**: Code structure mirrors RFC-206's conceptual layer separation
4. **Minimal Disruption**: Localized changes to prompt construction only

---

## Goals

1. Add `PromptBuilder.build_reason_messages()` returning `List[BaseMessage]`
2. Add helper methods for SystemMessage and HumanMessage construction
3. Update `SimplePlanner` to use new message-based API
4. Remove `SOOTHE_` prefix from XML tags in `context_xml.py`
5. Remove `<WAVE_METRICS>` section from prompts
6. Update tests to validate message structure
7. Maintain backward compatibility during migration
8. All 900+ tests pass, linting zero errors

---

## Implementation Plan

### Phase 1: PromptBuilder Enhancement

#### 1.1 Add New Method

**File**: `src/soothe/core/prompts/builder.py`

**Current Method**: `build_reason_prompt(goal, state, context) -> str`

**New Method**: `build_reason_messages(goal, state, context) -> List[BaseMessage]`

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
    """
    system_content = self._build_system_message(state, context)
    human_content = self._build_human_message(goal, state, context)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=human_content)
    ]
```

#### 1.2 Add SystemMessage Helper

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

#### 1.3 Add HumanMessage Helper

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

#### 1.4 Add Section Builder Helpers

Add private methods for each section:

- `_build_workspace_section(workspace)` - Construct workspace rules
- `_build_goal_section(goal, state)` - Goal statement + iteration metadata
- `_build_prior_conversation_section(context)` - Previous messages
- `_build_evidence_section(state)` - Step results
- `_build_working_memory_section(state)` - Scratchpad excerpts
- `_build_previous_reason_section(state)` - Last assessment
- `_build_completed_steps_section(state)` - Step summaries

Each method returns formatted XML section string.

#### 1.5 Backward Compatibility Wrapper

Keep old method temporarily for migration:

```python
def build_reason_prompt(self, goal: str, state: LoopState, context: ReasonContext) -> str:
    """Deprecated: Use build_reason_messages() instead.

    Provided for backward compatibility during migration.
    """
    import warnings
    warnings.warn(
        "build_reason_prompt() is deprecated, use build_reason_messages()",
        DeprecationWarning,
        stacklevel=2
    )
    messages = self.build_reason_messages(goal, state, context)
    return "\n\n".join([m.content for m in messages])
```

---

### Phase 2: SimplePlanner Update

#### 2.1 Update reason() Method

**File**: `src/soothe/backends/planning/simple.py`

**Current**:
```python
async def reason(self, goal: str, state: LoopState, context: ReasonContext) -> ReasonResult:
    prompt = self._prompt_builder.build_reason_prompt(goal, state, context)
    response = await self._invoke(prompt)
    return self._parse_response(response)
```

**New**:
```python
async def reason(self, goal: str, state: LoopState, context: ReasonContext) -> ReasonResult:
    messages = self._prompt_builder.build_reason_messages(goal, state, context)
    response = await self._invoke_messages(messages)
    return self._parse_response(response)
```

#### 2.2 Rename _invoke Method

**Current**:
```python
async def _invoke(self, prompt: str) -> str:
    response = await self._model.ainvoke([HumanMessage(content=prompt)])
    return response.content
```

**New**:
```python
async def _invoke_messages(self, messages: List[BaseMessage]) -> str:
    """Invoke model with message list instead of single prompt string."""
    response = await self._model.ainvoke(messages)
    return response.content
```

**Change**: Remove HumanMessage wrapping (already in message list), rename for clarity.

---

### Phase 3: Context XML Update

#### 3.1 Remove SOOTHE_ Prefix

**File**: `src/soothe/core/prompts/context_xml.py`

**Current**: Uses `<SOOTHE_ENVIRONMENT>` and `<SOOTHE_WORKSPACE>` tags

**New**: Uses `<ENVIRONMENT>` and `<WORKSPACE>` tags

Find and replace:
- `<SOOTHE_ENVIRONMENT>` → `<ENVIRONMENT>`
- `</SOOTHE_ENVIRONMENT>` → `</ENVIRONMENT>`
- `<SOOTHE_WORKSPACE>` → `<WORKSPACE>`
- `</SOOTHE_WORKSPACE>` → `</WORKSPACE>`

---

### Phase 4: Remove Wave Metrics

#### 4.1 Remove from PromptBuilder

Remove any wave metrics section construction:

- Remove `_build_wave_metrics_section()` method (if exists)
- Remove wave metrics from `build_reason_messages()` logic
- Remove wave metrics from `_build_human_message()` logic

Wave metrics (tool call counts, subagent counts, wave duration) should not be in prompts.

**Note**: Wave metrics remain in `LoopState` for internal tracking and LLMTracingMiddleware logging.

---

### Phase 5: Test Updates

#### 5.1 Prompt Structure Tests

**Files**: `tests/unit/prompts/` and `tests/unit/core/prompts/`

Tests to update:
- `test_reason_prompt_workspace.py`
- `test_reason_prompt_metrics.py`
- `test_reason_prior_conversation_conditional.py`
- Any tests checking `build_reason_prompt()` output

**Updates**:
- Change assertions to call `build_reason_messages()` instead
- Assert return type is `List[BaseMessage]`
- Assert length is 2 (SystemMessage + HumanMessage)
- Assert first message is `SystemMessage` instance
- Assert second message is `HumanMessage` instance
- Verify SystemMessage content contains: environment, workspace, policies, instructions
- Verify HumanMessage content contains: goal, evidence, working memory
- Verify XML tags: `<ENVIRONMENT>`, `<WORKSPACE>` (no SOOTHE_ prefix)
- Verify no wave metrics in messages

#### 5.2 SimplePlanner Tests

**Files**: `tests/unit/backends/planning/`

Tests to update:
- `test_simple_planner.py`
- Any tests mocking `_invoke()` method

**Updates**:
- Update mocks to expect message list instead of string
- Rename mock `_invoke` to `_invoke_messages`
- Assert message list passed to model invocation

#### 5.3 Integration Tests

**Files**: `tests/integration/`

- Should pass unchanged (behavior identical, just structure different)
- May need to update if tests inspect message structure

---

### Phase 6: Verification

#### 6.1 Run Verification Suite

```bash
./scripts/verify_finally.sh
```

This runs:
- Code formatting check
- Linting (zero errors required)
- Unit tests (900+ tests must pass)

#### 6.2 Success Criteria

1. ✅ All 900+ tests pass
2. ✅ Linting passes with zero errors
3. ✅ Code formatting passes
4. ✅ SystemMessage contains: environment, workspace, policies, instructions
5. ✅ HumanMessage contains: goal, evidence, working memory, prior conversation
6. ✅ No behavior changes - LLM responses identical
7. ✅ Wave metrics removed from prompts
8. ✅ XML tags: `<ENVIRONMENT>`, `<WORKSPACE>` (no SOOTHE_ prefix)
9. ✅ Deprecation warning for old method
10. ✅ Backward compatibility maintained during migration

---

### Phase 7: Cleanup

#### 7.1 Remove Deprecated Method

Once all tests updated and passing:

```python
# Remove build_reason_prompt() method from builder.py
# Remove deprecation warning
```

#### 7.2 Update Imports

If any other files import `build_reason_prompt`, update to use `build_reason_messages`.

---

### Phase 8: Documentation

#### 8.1 Update RFC-206

Add note in RFC-206:
```markdown
**Note**: RFC-207 refines this specification by implementing proper
SystemMessage/HumanMessage separation instead of single HumanMessage approach.
```

#### 8.2 Update IG-135

Add implementation history entry:
```markdown
**2026-04-08**: RFC-207 implementation (IG-142)
- Added build_reason_messages() returning List[BaseMessage]
- SystemMessage/HumanMessage separation
- Removed SOOTHE_ prefix from XML tags
- Removed wave metrics from prompts
```

#### 8.3 Update CLAUDE.md

Add entry in Recent Changes section:
```markdown
### IG-142: Message Type Separation (RFC-207)
- Implemented SystemMessage/HumanMessage separation
- Follows Claude API best practices
- Better architectural clarity
- All tests passing ✅
```

#### 8.4 Update PromptBuilder Docstrings

Add message structure examples in docstrings:
```python
"""
Returns:
    List of [SystemMessage, HumanMessage] to send to LLM.

Example:
    >>> messages = builder.build_reason_messages(goal, state, context)
    >>> isinstance(messages[0], SystemMessage)  # System context
    >>> isinstance(messages[1], HumanMessage)   # User task
"""
```

---

## Files Modified

### Primary Implementation

1. `src/soothe/core/prompts/builder.py`:
   - Add `build_reason_messages()` method
   - Add `_build_system_message()` helper
   - Add `_build_human_message()` helper
   - Add `_build_*_section()` helper methods (7 methods)
   - Deprecate `build_reason_prompt()` temporarily

2. `src/soothe/backends/planning/simple.py`:
   - Update `reason()` to use `build_reason_messages()`
   - Rename `_invoke()` to `_invoke_messages()`
   - Remove HumanMessage wrapping logic

3. `src/soothe/core/prompts/context_xml.py`:
   - Update XML tags: `<SOOTHE_ENVIRONMENT>` → `<ENVIRONMENT>`
   - Update XML tags: `<SOOTHE_WORKSPACE>` → `<WORKSPACE>`

### Tests

4. `tests/unit/prompts/` (or `tests/unit/core/prompts/`):
   - Update assertions for message list structure
   - Verify SystemMessage/HumanMessage types
   - Verify content separation

5. `tests/unit/backends/planning/`:
   - Update mocks for message list invocation
   - Rename `_invoke` to `_invoke_messages`

### Documentation

6. `docs/specs/RFC-206-prompt-architecture.md`:
   - Add note referencing RFC-207 refinement

7. `docs/impl/IG-135-prompt-architecture.md`:
   - Add implementation history entry

8. `CLAUDE.md`:
   - Add IG-142 in Recent Changes section

---

## Files Unchanged

- Agent factory (`_builder.py`, `_core.py`)
- Runner (`_runner_agentic.py`)
- Middleware stack (already handles message lists)
- State management (`LoopState`, checkpointing)
- Response parsing (still parses AIMessage.content as JSON)
- Fragment XML files (content unchanged)
- Integration tests (behavior identical)

---

## Edge Cases

1. **Empty SystemMessage**: Never occurs - policies and instructions always present
2. **Empty HumanMessage**: Never occurs - goal always present
3. **Prior conversation handling**: Conditional logic unchanged from RFC-206
4. **Checkpoint compatibility**: Messages ephemeral (not persisted in LoopState)
5. **Middleware compatibility**: LLMTracingMiddleware already handles message lists

---

## Testing Strategy

### Unit Tests

- Test each section builder helper method
- Test `build_reason_messages()` returns correct message types
- Test SystemMessage/HumanMessage content separation
- Test conditional sections (workspace, prior conversation, evidence)
- Test XML tag names (no SOOTHE_ prefix)
- Test wave metrics absence

### Integration Tests

- Test full agentic loop execution with new message structure
- Verify Reason → Act cycle works correctly
- Verify evidence accumulation in HumanMessage
- Verify checkpoint handling unchanged
- Verify LLMTracingMiddleware logs message count

### Verification

```bash
make format-check    # Check formatting
make lint            # Check linting (zero errors)
make test-unit       # Run 900+ tests
./scripts/verify_finally.sh  # Full verification
```

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Tests fail after message structure change | Backward compatibility wrapper during migration |
| Behavior changes in LLM responses | Verify responses identical in integration tests |
| Middleware incompatibility | LLMTracingMiddleware already handles message lists |
| Import errors after removing old method | Incremental migration, keep deprecated method temporarily |
| Wave metrics removal affects reasoning | Wave metrics never used for reasoning (internal tracking only) |

---

## Dependencies

- **RFC-206**: Hierarchical Prompt Architecture (implemented via IG-137)
- **RFC-201**: Agentic Goal Execution (Reason/Act loop)
- **RFC-100**: CoreAgent Runtime (BaseChatModel interface)
- **IG-137**: Prompts consolidation (module structure)

---

## Success Metrics

- Code quality: Linting zero errors, formatting passes
- Test coverage: All 900+ tests pass
- Behavioral equivalence: LLM responses identical
- Architectural improvement: Clear SystemMessage/HumanMessage separation
- Documentation: RFC, IG, CLAUDE.md updated

---

## Rollback Plan

If issues arise:

1. Revert to `build_reason_prompt()` temporarily
2. Keep backward compatibility wrapper
3. Investigate test failures
4. Fix issues incrementally
5. Re-run verification suite

---

## Next Steps

1. ✅ RFC-207 formalized
2. ✅ IG-142 created (this guide)
3. 🚧 Implement Phase 1: PromptBuilder enhancement
4. 🚧 Implement Phase 2: SimplePlanner update
5. 🚧 Implement Phase 3: Context XML update
6. 🚧 Implement Phase 4: Remove wave metrics
7. 🚧 Implement Phase 5: Test updates
8. 🚧 Run Phase 6: Verification
9. 🚧 Phase 7: Cleanup (remove deprecated method)
10. 🚧 Phase 8: Documentation updates
11. ✅ Mark IG-142 as Completed
12. ✅ Update RFC-207 status to Implemented

---

## Changelog

**2026-04-08 (created)**:
- Initial IG-142 created
- Implementation plan defined
- 8 phases outlined
- Files modified list compiled
- Success criteria defined
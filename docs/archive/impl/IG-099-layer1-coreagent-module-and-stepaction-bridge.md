# IG-099: Layer 1 CoreAgent Module + StepAction Integration Bridge

**Implementation Guide**: IG-099
**RFC**: RFC-100 (Layer 1), RFC-201 (Layer 2)
**Status**: Draft
**Created**: 2026-03-29
**Related**: IG-097 (Layer 2 AgentLoop)

## Overview

This implementation guide addresses two critical architectural gaps:

1. **Distill CoreAgent as a self-contained Layer 1 module** - formalize boundaries, interfaces, and documentation
2. **Implement StepAction → CoreAgent bridge** - fix the missing integration contract where Layer 2's tool/subagent hints are not passed to Layer 1

### Current Gap Analysis

**Problem**: The Executor (`cognition/agent_loop/executor.py`) currently ignores StepAction's `tools` and `subagent` fields:

```python
# Current implementation (executor.py:211)
stream = await self.core_agent.astream(
    input=f"Execute: {step.description}",  # ❌ Only text, no tool/subagent hints
    config={"configurable": {"thread_id": thread_id}}
)
```

**Issue**: Layer 2's Planner decides that certain tools/subagents would be useful (e.g., `tools=["read_file", "grep"]`, `subagent="browser"`), but these hints are never communicated to Layer 1's CoreAgent. The LLM inside CoreAgent then makes its own tool/subagent decisions based on the text description alone, potentially choosing different tools or duplicating the planning effort.

**Architecture Violation**: This violates the three-layer principle where:
- **Layer 2 controls WHAT to execute** (step content + tool/subagent hints)
- **Layer 1 handles HOW to execute** (runtime execution with hints considered)

### Objectives

1. **Define Layer 1 CoreAgent module boundaries** - explicit public interface, documentation, self-containment
2. **Create StepAction integration contract** - structured input format that includes tool/subagent hints
3. **Implement hint propagation** - Executor passes hints to CoreAgent via config or input structure
4. **Test integration bridge** - verify hints influence CoreAgent execution appropriately
5. **Update RFC-100** - document the integration contract formally

## Architecture Design

### CoreAgent (Layer 1) Self-Contained Module

**Module**: `src/soothe/core/agent.py`

**Purpose**: Factory that creates Layer 1 runtime (CompiledStateGraph) with built-in capabilities

**Public Interface**:

```python
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """
    Factory that creates Soothe's Layer 1 CoreAgent runtime.

    Layer 1 Responsibilities:
    - Execute tools/subagents via LangGraph Model → Tools → Model loop
    - Apply middlewares (context, memory, policy, planner)
    - Manage thread state (sequential vs parallel)
    - Consider execution hints from Layer 2 (optional)

    Returns CompiledStateGraph with attached protocol instances:
    - soothe_context: ContextProtocol
    - soothe_memory: MemoryProtocol
    - soothe_planner: PlannerProtocol
    - soothe_policy: PolicyProtocol
    - soothe_durability: DurabilityProtocol
    """
```

**Key Attributes** (attached to graph):
- `soothe_context`, `soothe_memory`, `soothe_planner`, `soothe_policy`, `soothe_durability`
- `soothe_config`, `soothe_subagents`

**Execution Interface**:
```python
agent.astream(
    input: str | dict,  # Text instruction OR structured input with hints
    config: RunnableConfig  # Thread_id, recursion_limit, optional hints
) → AsyncIterator[StreamChunk]
```

**Self-Containment Requirements**:
1. ✅ Own factory function (`create_soothe_agent()`)
2. ✅ Protocol attachments (already implemented)
3. ✅ Built-in capabilities assembly (already implemented)
4. ❌ **MISSING**: Structured input contract for Layer 2 integration
5. ❌ **MISSING**: Hint consideration in execution flow
6. ❌ **MISSING**: Clear Layer 1 documentation in code

### StepAction → CoreAgent Bridge

**Integration Contract**: Layer 2 communicates execution context to Layer 1 via **structured input** or **config metadata**.

**Design Decision**: Use **config metadata** approach (cleaner separation, doesn't require modifying LangGraph input contract).

**Executor → CoreAgent Call Pattern**:

```python
# Proposed implementation
stream = await self.core_agent.astream(
    input=f"Execute: {step.description}",
    config={
        "configurable": {
            "thread_id": thread_id,
            # Layer 2 → Layer 1 hints (optional, advisory)
            "soothe_step_tools": step.tools,  # e.g., ["read_file", "grep"]
            "soothe_step_subagent": step.subagent,  # e.g., "browser"
            "soothe_step_expected_output": step.expected_output,
        }
    }
)
```

**CoreAgent Handling** (in middlewares or execution logic):

Option A: **Middleware intercepts hints** (cleanest)
- New middleware: `ExecutionHintsMiddleware`
- Reads hints from config, injects into system prompt or agent state
- Example: "The planner suggests using: read_file, grep. Consider these tools first."

Option B: **Tool selection middleware uses hints**
- `ParallelToolsMiddleware` or policy middleware considers suggested tools
- Prioritizes suggested tools in execution order

Option C: **LLM prompt includes hints**
- System prompt optimization middleware injects hint context
- Example: "Available suggested tools: read_file, grep. Expected output: file contents matching pattern."

**Recommended**: **Option A** (ExecutionHintsMiddleware) - cleanest separation, explicit Layer 1/2 contract, testable.

## Implementation Phases

### Phase 1: Define CoreAgent Layer 1 Boundaries (Day 1)

**Objective**: Formalize CoreAgent as self-contained Layer 1 module with clear documentation

**Tasks**:
1. Update `core/agent.py` docstring with Layer 1 responsibilities
2. Document public interface (factory, protocols, execution API)
3. Create `core/agent_doc.md` with Layer 1 architecture explanation
4. Update `create_soothe_agent()` to explicitly state "Layer 1 factory"
5. Add type hints for protocol attachments
6. Update RFC-100 reference in code comments

**Files Modified**:
- `src/soothe/core/agent.py` - Enhanced docstrings
- `src/soothe/core/__init__.py` - Export Layer 1 interface
- `docs/core_agent_layer1.md` - New documentation file

**Success Criteria**:
- ✅ `create_soothe_agent()` explicitly documented as Layer 1 factory
- ✅ Protocol attachments clearly documented
- ✅ Execution interface documented with hint support (future)
- ✅ Code comments reference RFC-100

### Phase 2: Create ExecutionHintsMiddleware (Days 2-3)

**Objective**: Implement middleware that processes Layer 2 hints and injects context

**Tasks**:
1. Create `middleware/execution_hints.py`
2. Implement `ExecutionHintsMiddleware` class
3. Read hints from config: `soothe_step_tools`, `soothe_step_subagent`, `soothe_step_expected_output`
4. Inject hints into agent state or system prompt
5. Wire middleware into `create_soothe_agent()` stack (after policy, before context)
6. Write unit tests

**Middleware Design**:

```python
class ExecutionHintsMiddleware(AgentMiddleware):
    """Process Layer 2 execution hints and inject context.

    Reads from config.configurable:
    - soothe_step_tools: Optional suggested tools
    - soothe_step_subagent: Optional suggested subagent
    - soothe_step_expected_output: Expected result description

    Injects into agent context:
    - System prompt addition: "Suggested approach: use tools [X, Y] for [expected output]"
    - Agent state metadata: hints available for tool selection logic
    """

    async def process_agent_input(self, state: AgentState, config: RunnableConfig):
        hints = self._extract_hints(config)
        if hints:
            state["execution_hints"] = hints
            # Inject into system prompt or context
            hint_text = self._format_hints(hints)
            if "system_prompt" in state:
                state["system_prompt"] += f"\n\nExecution hints: {hint_text}"

    def _extract_hints(self, config: RunnableConfig) -> dict | None:
        configurable = config.get("configurable", {})
        tools = configurable.get("soothe_step_tools")
        subagent = configurable.get("soothe_step_subagent")
        expected = configurable.get("soothe_step_expected_output")

        if not any([tools, subagent, expected]):
            return None

        return {
            "tools": tools,
            "subagent": subagent,
            "expected_output": expected
        }

    def _format_hints(self, hints: dict) -> str:
        parts = []
        if hints.get("tools"):
            parts.append(f"Suggested tools: {', '.join(hints['tools'])}")
        if hints.get("subagent"):
            parts.append(f"Suggested subagent: {hints['subagent']}")
        if hints.get("expected_output"):
            parts.append(f"Expected output: {hints['expected_output']}")
        return ". ".join(parts)
```

**Files Created**:
- `src/soothe/middleware/execution_hints.py`

**Files Modified**:
- `src/soothe/core/agent.py` - Wire middleware into stack

**Tests**:
- `tests/unit/test_execution_hints_middleware.py`

**Success Criteria**:
- ✅ Middleware extracts hints from config
- ✅ Hints injected into agent state
- ✅ System prompt enhanced with hint context
- ✅ Unit tests passing

### Phase 3: Update Executor Bridge (Days 4-5)

**Objective**: Modify Executor to pass StepAction hints to CoreAgent

**Tasks**:
1. Update `executor.py` `_execute_step()` method
2. Extract `step.tools`, `step.subagent`, `step.expected_output`
3. Pass hints via config.configurable
4. Update logging to show hints being passed
5. Test hint propagation
6. Verify CoreAgent receives hints

**Executor Implementation**:

```python
async def _execute_step(self, step, thread_id: str) -> StepResult:
    """Execute single step through CoreAgent with hints."""
    start = time.perf_counter()

    try:
        logger.debug(
            "Executing step %s: %s [hints: tools=%s, subagent=%s]",
            step.id,
            step.description[:100],
            step.tools,
            step.subagent
        )

        # Build config with Layer 2 → Layer 1 hints
        config = {
            "configurable": {
                "thread_id": thread_id,
                # Layer 2 execution hints (optional, advisory)
                "soothe_step_tools": step.tools,
                "soothe_step_subagent": step.subagent,
                "soothe_step_expected_output": step.expected_output,
            }
        }

        stream = await self.core_agent.astream(
            input=f"Execute: {step.description}",
            config=config
        )

        output = await self._collect_stream(stream)
        duration_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Step %s completed in %dms (hints applied)",
            step.id,
            duration_ms
        )

        return StepResult(
            step_id=step.id,
            success=True,
            output=output,
            duration_ms=duration_ms,
            thread_id=thread_id,
        )

    except Exception as e:
        # Error handling...
```

**Files Modified**:
- `src/soothe/cognition/agent_loop/executor.py`

**Tests**:
- `tests/integration/test_executor_hints.py`

**Success Criteria**:
- ✅ Executor extracts StepAction hints
- ✅ Hints passed via config.configurable
- ✅ Logging shows hints being applied
- ✅ Integration tests verify hint propagation

### Phase 4: Test Integration Bridge (Days 6-7)

**Objective**: Verify Layer 2 → Layer 1 integration works end-to-end

**Tasks**:
1. Create integration test: Layer 2 decision → Executor → CoreAgent → verify hints used
2. Test scenarios:
   - StepAction with tools hint → CoreAgent uses suggested tools
   - StepAction with subagent hint → CoreAgent invokes suggested subagent
   - StepAction with expected_output → CoreAgent output matches expectation
   - StepAction without hints → CoreAgent decides independently
3. Mock Planner to generate specific StepActions with hints
4. Mock CoreAgent execution to verify hint processing
5. Test error scenarios (invalid hints, missing tools, etc.)

**Test Scenarios**:

```python
# Scenario 1: Tools hint
step = StepAction(
    description="Find files matching pattern",
    tools=["glob", "grep"],
    expected_output="List of matching files"
)
# Expected: CoreAgent receives tools hint, prioritizes glob/grep

# Scenario 2: Subagent hint
step = StepAction(
    description="Browse web page",
    subagent="browser",
    expected_output="Page content extracted"
)
# Expected: CoreAgent receives subagent hint, invokes browser subagent

# Scenario 3: No hints
step = StepAction(
    description="Read config file",
    expected_output="Config contents"
)
# Expected: CoreAgent decides tool independently (likely read_file)

# Scenario 4: Invalid hint
step = StepAction(
    description="Execute command",
    tools=["nonexistent_tool"],
    expected_output="Command output"
)
# Expected: CoreAgent ignores invalid hint, uses available tools
```

**Files Created**:
- `tests/integration/test_layer2_layer1_bridge.py`

**Success Criteria**:
- ✅ Hints propagate from StepAction → Executor → CoreAgent
- ✅ ExecutionHintsMiddleware processes hints correctly
- ✅ CoreAgent execution influenced by hints (verified via logs/mocks)
- ✅ Integration tests passing for all scenarios
- ✅ Error handling tested (invalid hints)

### Phase 5: Documentation and RFC Updates (Day 8)

**Objective**: Document integration contract in RFC-100 and user guide

**Tasks**:
1. Update RFC-100 §4 "Integration Contract" with StepAction hints
2. Add section: "Layer 2 → Layer 1 Execution Hints"
3. Document hint fields: `soothe_step_tools`, `soothe_step_subagent`, `soothe_step_expected_output`
4. Document ExecutionHintsMiddleware behavior
5. Add examples of hint usage
6. Update user guide with Layer 1/2 integration explanation
7. Create architecture diagram showing hint flow

**RFC-100 Update**:

Add section:

```markdown
## Layer 2 Integration Contract

### Execution Hints

Layer 2's ACT phase passes execution hints to Layer 1 CoreAgent via `config.configurable`:

| Hint Field | Purpose | Example |
|------------|---------|---------|
| `soothe_step_tools` | Suggested tools for execution | `["read_file", "grep"]` |
| `soothe_step_subagent` | Suggested subagent to invoke | `"browser"` |
| `soothe_step_expected_output` | Expected result description | `"File contents matching pattern"` |

**Hint Behavior**:
- **Advisory, not mandatory**: Layer 1 considers hints but may choose different tools/subagents if inappropriate
- **ExecutionHintsMiddleware**: Injects hints into agent context/system prompt
- **LLM consideration**: CoreAgent LLM sees hints and decides whether to use suggested approach

**Example**:
```python
# Layer 2 Planner decision
decision = AgentDecision(
    steps=[
        StepAction(
            description="Find configuration files",
            tools=["glob", "grep"],  # Suggest search tools
            expected_output="List of config files"
        )
    ],
    execution_mode="sequential"
)

# Executor passes hints to Layer 1
stream = await core_agent.astream(
    input="Execute: Find configuration files",
    config={
        "configurable": {
            "thread_id": "thread-123",
            "soothe_step_tools": ["glob", "grep"],
            "soothe_step_expected_output": "List of config files"
        }
    }
)

# CoreAgent LLM sees hint: "Suggested tools: glob, grep. Expected output: List of config files"
# → Decides to use glob first, then grep for filtering
```
```

**Files Modified**:
- `docs/specs/RFC-100-coreagent-runtime.md` - Add integration contract section
- `docs/user_guide.md` - Add Layer 1/2 integration explanation
- `docs/core_agent_layer1.md` - Architecture documentation

**Success Criteria**:
- ✅ RFC-100 updated with integration contract
- ✅ Hint fields documented with examples
- ✅ Architecture diagram created
- ✅ User guide updated

## Implementation Summary

### Architecture Bridge Pattern

```
Layer 2 (Planner) → AgentDecision with StepAction
    ↓
StepAction includes:
    - description: "Find config files"
    - tools: ["glob", "grep"]  ← Suggested tools
    - subagent: None
    - expected_output: "List of config files"

Executor (ACT phase)
    ↓
Passes hints via config.configurable:
    - soothe_step_tools: ["glob", "grep"]
    - soothe_step_expected_output: "List of config files"

CoreAgent (Layer 1)
    ↓
ExecutionHintsMiddleware processes hints:
    → Injects: "Suggested tools: glob, grep. Expected output: List of config files"
    → LLM sees hint in system prompt
    → LLM decides: use glob first, then grep
    → Executes tool sequence

Tool execution via LangGraph Model → Tools → Model loop
    ↓
Stream results back to Executor
```

### Key Design Decisions

1. **Hints are advisory, not mandatory** - Layer 1 LLM still decides final execution
2. **Config-based passing** - Cleaner than modifying LangGraph input contract
3. **Middleware processing** - Separation of concerns, testable
4. **System prompt injection** - LLM sees hints naturally in context
5. **Optional hints** - Layer 2 can omit hints if uncertain, Layer 1 decides independently

### Alternative Designs (Considered but Rejected)

**Alternative 1: Mandatory tool forcing**
- Force CoreAgent to use exactly the suggested tools
- ❌ Rejected: Violates Layer 1's execution autonomy, too rigid

**Alternative 2: Structured input format**
- Pass `{"instruction": "...", "hints": {...}}` as input dict
- ❌ Rejected: Requires modifying LangGraph input contract, less clean

**Alternative 3: Direct tool invocation**
- Executor directly calls tools, bypassing CoreAgent
- ❌ Rejected: Violates Layer 1 boundary, loses middleware benefits

## Configuration Updates

**File**: `config/config.yml`

Add execution hints configuration:

```yaml
execution:
  hints:
    enabled: true  # Enable Layer 2 → Layer 1 hints propagation
    advisory: true  # Hints are advisory (LLM decides final execution)
    inject_prompt: true  # Inject hints into system prompt
```

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_execution_hints_middleware.py`
- Test hint extraction from config
- Test hint formatting for prompt
- Test injection into agent state
- Test missing/invalid hints handling

**File**: `tests/unit/test_executor_hints.py`
- Test Executor extracts StepAction fields
- Test hint passing via config
- Test logging output

### Integration Tests

**File**: `tests/integration/test_layer2_layer1_bridge.py`
- Test complete flow: Planner → Executor → CoreAgent
- Test tools hint influences execution
- Test subagent hint invokes subagent
- Test expected_output validation
- Test error scenarios

**File**: `tests/integration/test_coreagent_with_hints.py`
- Test CoreAgent execution with various hint scenarios
- Test ExecutionHintsMiddleware integration
- Test hint consideration in LLM decisions

## Migration Notes

### No Breaking Changes

This implementation is **additive**:
- Executor already calls `core_agent.astream(input, config)` - just adding config fields
- CoreAgent already processes config - just adding middleware to read new fields
- StepAction fields already exist - just using them now

### Backward Compatibility

- Steps without hints work exactly as before
- Existing Executor code unaffected (just enhanced)
- CoreAgent execution unchanged for non-hint cases

## Success Metrics

✅ **Layer 1 CoreAgent formalized** with clear documentation and boundaries
✅ **Integration contract defined** in RFC-100 with examples
✅ **ExecutionHintsMiddleware implemented** and tested
✅ **Executor passes hints** from StepAction to CoreAgent
✅ **Integration tests verify** hint propagation and influence
✅ **RFC-100 updated** with Layer 2 → Layer 1 contract
✅ **All tests passing** (unit + integration)
✅ **Documentation complete** (code, RFC, user guide)

## Timeline

- **Day 1**: CoreAgent Layer 1 documentation
- **Days 2-3**: ExecutionHintsMiddleware implementation
- **Days 4-5**: Executor bridge implementation
- **Days 6-7**: Integration testing
- **Day 8**: Documentation and RFC updates

**Total**: 8 days (1 week)

## Related Documents

- [RFC-100](../specs/RFC-100-coreagent-runtime.md) - Layer 1 Specification
- [RFC-201](../specs/RFC-201-agentic-goal-execution-loop.md) - Layer 2 Specification
- [IG-097](./IG-097-layer2-loopagent-implementation.md) - Layer 2 Implementation Guide

## Changelog

### 2026-03-29
- Initial implementation guide created
- Identified StepAction → CoreAgent integration gap
- Designed ExecutionHintsMiddleware solution
- Defined 5-phase implementation plan
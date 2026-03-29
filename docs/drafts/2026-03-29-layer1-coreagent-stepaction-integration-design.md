# Layer 1 CoreAgent Module + StepAction Integration Bridge Design

**Created**: 2026-03-29
**Status**: Draft
**Purpose**: Formalize CoreAgent as Layer 1 module and implement StepAction → CoreAgent integration bridge

---

## Abstract

This design addresses a critical architectural gap in Soothe's three-layer execution model: Layer 2's Planner specifies tool/subagent suggestions in `StepAction`, but these hints are never passed to Layer 1's CoreAgent. The Executor only sends text descriptions, forcing CoreAgent's LLM to make independent tool decisions without Layer 2's planning context.

We implement an advisory hint propagation system that passes Layer 2's suggestions to Layer 1 through config metadata, processed by a dedicated ExecutionHintsMiddleware that injects hints into the system prompt for LLM consideration. This preserves Layer 1's execution autonomy while honoring Layer 2's planning intelligence.

---

## 1. Problem Statement

### 1.1 Current Integration Gap

**Layer 2 Planner Decision**:

```python
StepAction(
    description="Find configuration files",
    tools=["glob", "grep"],          # ← Suggested tools
    subagent=None,
    expected_output="Config file list"
)
```

**Executor Current Implementation** (`executor.py`):

```python
stream = await self.core_agent.astream(
    input=f"Execute: {step.description}",  # ❌ Only text, no hints!
    config={"configurable": {"thread_id": thread_id}}
)
```

**Result**: StepAction's `tools`, `subagent`, and `expected_output` fields are **never passed to Layer 1**. CoreAgent's LLM makes tool decisions based solely on the text description, potentially:
- Choosing different tools than Layer 2 planned
- Duplicating planning effort (Layer 2 planned, Layer 1 re-plans)
- Missing context about expected output structure
- Ignoring subagent suggestions that would be more efficient

### 1.2 Architecture Violation

This violates the three-layer separation principle:

- **Layer 2 controls WHAT to execute** (step content + tool/subagent hints)
- **Layer 1 handles HOW to execute** (runtime execution with context)

But currently, Layer 1 receives **no context** from Layer 2's planning decisions.

---

## 2. Architectural Decisions

### 2.1 Decision: Advisory Hints (Not Mandatory)

**Question**: Should Layer 2's tool suggestions be mandatory directives or advisory hints?

**Decision**: **Advisory Hints**

**Rationale**:
- Preserves Layer 1 execution autonomy (three-layer architecture principle)
- Layer 1 LLM can override inappropriate suggestions (e.g., deprecated tool, better alternative)
- Honors "Layer 1 handles HOW to execute" principle
- Layer 2 provides intelligence, Layer 1 makes final execution decisions

**Examples**:
- Layer 2 suggests deprecated tool → Layer 1 LLM chooses modern equivalent
- Layer 2 suggests grep, but description implies read_file is better → Layer 1 adapts
- Layer 2 suggests subagent, but simple tool suffices → Layer 1 uses tool

### 2.2 Decision: Config Metadata Passing

**Question**: How should hints be communicated from Layer 2 to Layer 1?

**Decision**: **Config Metadata Passing** via `config.configurable`

**Implementation**:

```python
await core_agent.astream(
    input="Execute: Find config files",
    config={
        "configurable": {
            "thread_id": "thread-123",
            # Layer 2 → Layer 1 hints
            "soothe_step_tools": ["glob", "grep"],
            "soothe_step_subagent": "browser",
            "soothe_step_expected_output": "Config file list"
        }
    }
)
```

**Rationale**:
- Clean separation: doesn't modify LangGraph input contract
- Testable: hints flow through explicit channel
- Middleware can read hints from config systematically
- No breaking changes to existing CoreAgent API

**Alternatives Rejected**:
- **Structured input dict**: Would require modifying LangGraph input contract
- **Prompt injection in Executor**: Tight coupling, harder to test
- **Agent state injection**: Requires state access, less clean than config

### 2.3 Decision: ExecutionHintsMiddleware

**Question**: Where in Layer 1 should hints be processed?

**Decision**: **New Dedicated Middleware: ExecutionHintsMiddleware**

**Rationale**:
- Explicit middleware with single responsibility: process Layer 2 hints
- Clean separation of concerns, testable, reusable
- Wire into middleware stack after policy, before context
- Honors middleware pattern, doesn't conflate existing middleware purposes

**Alternatives Rejected**:
- **SystemPromptOptimizationMiddleware enhancement**: Conflates optimization with hints
- **ParallelToolsMiddleware enhancement**: Hints include more than tools (subagent, expected_output)
- **Direct injection in CoreAgent factory**: Violates middleware pattern, harder to test

### 2.4 Decision: System Prompt Injection

**Question**: How should ExecutionHintsMiddleware inject hints into execution flow?

**Decision**: **System Prompt Injection**

**Implementation**:

```python
# Before
state["system_prompt"]: "You are Soothe agent..."

# After ExecutionHintsMiddleware
state["system_prompt"]: "You are Soothe agent...

Execution hints: Suggested tools: glob, grep. Expected output: Config file list.
Consider using the suggested approach first, but decide based on what works best."
```

**Rationale**:
- Natural integration: LLM sees hints in its decision-making context
- No execution logic changes: tool selection mechanism remains unchanged
- Simple implementation: just prompt manipulation
- Advisory nature preserved: LLM can ignore inappropriate hints
- Testable: can verify prompt content

**Alternatives Rejected**:
- **Agent state metadata only**: Less natural for LLM, requires execution logic changes
- **Dual injection (prompt + state)**: Potentially redundant, over-engineering for advisory hints

---

## 3. Integration Contract Design

### 3.1 Layer 2 → Layer 1 Hint Flow

```
Layer 2 Planner creates StepAction:
    description: "Find config files"
    tools: ["glob", "grep"]          ← Suggested tools
    subagent: None
    expected_output: "Config file list"

Executor extracts hints:
    soothe_step_tools: ["glob", "grep"]
    soothe_step_subagent: None
    soothe_step_expected_output: "Config file list"

Executor → CoreAgent.astream():
    input: "Execute: Find config files"
    config.configurable:
        thread_id: "thread-123"
        soothe_step_tools: ["glob", "grep"]       ← Passed via config
        soothe_step_expected_output: "Config file list"

ExecutionHintsMiddleware processes:
    Reads config.configurable hints
    Formats: "Suggested: glob, grep. Expected: Config file list"
    Injects into state["system_prompt"]

CoreAgent LLM execution:
    Receives enhanced prompt:
    "You are Soothe agent...

    Execution hints: Suggested tools: glob, grep. Expected output: Config file list.
    Consider using the suggested approach first, but decide based on what works best."

    LLM decides: "I'll use glob to find files, then grep to filter" ✓
```

### 3.2 Hint Fields

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `soothe_step_tools` | `list[str] \| None` | Suggested tools for execution | `["glob", "grep"]` |
| `soothe_step_subagent` | `str \| None` | Suggested subagent to invoke | `"browser"` |
| `soothe_step_expected_output` | `str` | Expected result description | `"Config file list"` |

**Naming Convention**: `soothe_step_*` prefix clearly identifies these as Layer 2 → Layer 1 integration fields

### 3.3 Advisory Nature

**Key Principle**: Hints are advisory, not mandatory.

**Behavior**:
- Layer 1 LLM **considers** hints in decision-making context
- Layer 1 LLM **decides** final tool/subagent selection
- Layer 1 LLM **can override** hints if inappropriate
- ExecutionHintsMiddleware **does not enforce** hint usage

**Example Scenarios**:

1. **Valid hint → LLM follows suggestion**:
   - Hint: `tools=["read_file"]`
   - LLM sees: "Suggested tools: read_file"
   - LLM decides: Use read_file ✓

2. **Invalid hint → LLM overrides**:
   - Hint: `tools=["deprecated_tool"]`
   - LLM sees: "Suggested tools: deprecated_tool"
   - LLM decides: Use modern equivalent instead ✓

3. **Missing hint → LLM decides independently**:
   - Hint: `tools=None`
   - LLM sees: "Expected output: file contents"
   - LLM decides: Use appropriate tool based on context ✓

---

## 4. ExecutionHintsMiddleware Design

### 4.1 Module Location

**File**: `src/soothe/middleware/execution_hints.py`

**Purpose**: Process Layer 2 execution hints and inject into Layer 1 agent context

### 4.2 Implementation

```python
from typing import TYPE_CHECKING
from langchain.agents.middleware import AgentMiddleware

if TYPE_CHECKING:
    from langchain.agents.types import AgentState
    from langchain_core.runnables import RunnableConfig

class ExecutionHintsMiddleware(AgentMiddleware):
    """Process Layer 2 execution hints and inject into system prompt.

    Reads from config.configurable:
    - soothe_step_tools: Optional suggested tools (list[str])
    - soothe_step_subagent: Optional suggested subagent (str)
    - soothe_step_expected_output: Expected result description (str)

    Injects into agent context:
    - Enhances system prompt with natural hint text
    - Format: "Suggested tools: X, Y. Expected output: Z."
    - LLM sees hints and decides whether to use suggested approach

    Advisory Nature:
    - Hints are suggestions, not directives
    - LLM can override hints if inappropriate
    - Execution logic unchanged (LLM makes final tool selection)

    Example:
        config.configurable = {
            "thread_id": "thread-123",
            "soothe_step_tools": ["glob", "grep"],
            "soothe_step_expected_output": "Config file list"
        }

        → System prompt enhanced:
        "Execution hints: Suggested tools: glob, grep. Expected output: Config file list.
         Consider using the suggested approach first, but decide based on what works best."
    """

    async def process_agent_input(
        self,
        state: "AgentState",
        config: "RunnableConfig"
    ) -> None:
        """Process hints and inject into agent state.

        Args:
            state: Agent state (will be modified)
            config: Runnable config with hints in configurable
        """
        hints = self._extract_hints(config)

        if not hints:
            # No hints present, skip processing
            return

        # Format hints for LLM consumption
        hint_text = self._format_hints(hints)

        # Inject into system prompt
        if "system_prompt" in state:
            state["system_prompt"] += f"\n\nExecution hints: {hint_text}"

        # Also add to state for potential logging/inspection
        state["execution_hints_received"] = hints

    def _extract_hints(self, config: "RunnableConfig") -> dict | None:
        """Extract Layer 2 hints from config.configurable.

        Args:
            config: Runnable config

        Returns:
            Hints dict if any hints present, None otherwise
        """
        configurable = config.get("configurable", {})

        tools = configurable.get("soothe_step_tools")
        subagent = configurable.get("soothe_step_subagent")
        expected = configurable.get("soothe_step_expected_output")

        # Only return if at least one hint present
        if not any([tools, subagent, expected]):
            return None

        return {
            "tools": tools,
            "subagent": subagent,
            "expected_output": expected
        }

    def _format_hints(self, hints: dict) -> str:
        """Format hints for system prompt injection.

        Args:
            hints: Hints dict from _extract_hints

        Returns:
            Formatted hint text for LLM
        """
        parts = []

        if hints.get("tools"):
            tools_str = ", ".join(hints["tools"])
            parts.append(f"Suggested tools: {tools_str}")

        if hints.get("subagent"):
            parts.append(f"Suggested subagent: {hints['subagent']}")

        if hints.get("expected_output"):
            parts.append(f"Expected output: {hints['expected_output']}")

        hint_str = ". ".join(parts)

        # Add advisory guidance
        return f"{hint_str}. Consider using the suggested approach first, but decide based on what works best."
```

### 4.3 Middleware Stack Position

**In `create_soothe_agent()` (`core/agent.py`)**:

```python
default_middleware: list[AgentMiddleware] = [
    SoothePolicyMiddleware(...),        # Policy checking first
    SystemPromptOptimizationMiddleware(...),  # Prompt optimization
    ExecutionHintsMiddleware(),         # ← NEW: Layer 2 → Layer 1 hints
    SubagentContextMiddleware(...),     # Context injection
    ParallelToolsMiddleware(...),       # Tool parallelism
]
```

**Positioning Rationale**:
- After policy: Policy checks must pass before execution
- After system prompt optimization: Base prompt optimized first
- Before context: Context loaded after hints injected
- Before parallel tools: Tool execution happens last

### 4.4 Behavior Details

**Missing Hints Handling**:
- If `step.tools` is `None` → Skip tools suggestion in formatted text
- If `step.subagent` is `None` → Skip subagent suggestion
- If all hints are `None` → Middleware returns early, no prompt modification

**Example Outputs**:

1. **All hints present**:
   ```
   Execution hints: Suggested tools: glob, grep. Expected output: Config file list.
   Consider using the suggested approach first, but decide based on what works best.
   ```

2. **Only tools hint**:
   ```
   Execution hints: Suggested tools: read_file. Consider using the suggested approach
   first, but decide based on what works best.
   ```

3. **Only expected_output**:
   ```
   Execution hints: Expected output: File contents. Consider using the suggested
   approach first, but decide based on what works best.
   ```

---

## 5. Executor Bridge Design

### 5.1 Module Location

**File**: `src/soothe/cognition/loop_agent/executor.py`

**Method**: `_execute_step()`

### 5.2 Implementation Changes

```python
async def _execute_step(
    self,
    step: StepAction,
    thread_id: str
) -> StepResult:
    """Execute single step through CoreAgent with Layer 2 hints.

    Args:
        step: StepAction with description and optional hints
        thread_id: Thread ID for execution

    Returns:
        StepResult with success/error and duration
    """
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
                # Layer 2 execution hints (advisory)
                "soothe_step_tools": step.tools,
                "soothe_step_subagent": step.subagent,
                "soothe_step_expected_output": step.expected_output,
            }
        }

        stream = await self.core_agent.astream(
            input=f"Execute: {step.description}",
            config=config  # ← Hints passed via config
        )

        output = await self._collect_stream(stream)
        duration_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Step %s completed in %dms (hints: tools=%s)",
            step.id,
            duration_ms,
            step.tools or "none"
        )

        return StepResult(
            step_id=step.id,
            success=True,
            output=output,
            duration_ms=duration_ms,
            thread_id=thread_id,
        )

    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)

        logger.error(
            "Step %s failed after %dms [hints: tools=%s, subagent=%s]: %s",
            step.id,
            duration_ms,
            step.tools,
            step.subagent,
            e,
            exc_info=True
        )

        return StepResult(
            step_id=step.id,
            success=False,
            error=str(e),
            error_type="execution",
            duration_ms=duration_ms,
            thread_id=thread_id,
        )
```

### 5.3 Changes Summary

**Added**:
- Extract `step.tools`, `step.subagent`, `step.expected_output`
- Pass via `config.configurable` with `soothe_step_*` prefix
- Enhanced debug logging to show hints being applied
- Enhanced info logging to show hints in completion message
- Enhanced error logging to show hints in failure context

**Unchanged**:
- `_execute_step()` signature (internal method)
- `core_agent.astream()` call signature
- `StepResult` return structure
- Error handling flow

---

## 6. CoreAgent Layer 1 Documentation

### 6.1 Module Location

**File**: `src/soothe/core/agent.py`

### 6.2 Enhanced Docstring

```python
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """
    Factory that creates Soothe's Layer 1 CoreAgent runtime.

    Layer 1 Responsibilities:
    - Execute tools/subagents via LangGraph Model → Tools → Model loop
    - Apply middlewares (context, memory, policy, planner, hints)
    - Manage thread state (sequential vs parallel execution)
    - Consider execution hints from Layer 2 (advisory suggestions)

    Built-in Capabilities:
    - Tools: execution, websearch, research, etc.
    - Subagents: Browser, Claude, Skillify, Weaver
    - MCP servers: loaded via configuration
    - Middlewares: policy, system prompt optimization, hints, context, memory, parallel tools

    Protocol Attachments:
    - soothe_context: ContextProtocol instance
    - soothe_memory: MemoryProtocol instance
    - soothe_planner: PlannerProtocol instance
    - soothe_policy: PolicyProtocol instance
    - soothe_durability: DurabilityProtocol instance
    - soothe_config: SootheConfig instance
    - soothe_subagents: list of configured subagents

    Execution Interface:
    - agent.astream(input, config) → AsyncIterator[StreamChunk]
    - config.configurable may include Layer 2 hints:
      - soothe_step_tools: suggested tools (advisory)
      - soothe_step_subagent: suggested subagent (advisory)
      - soothe_step_expected_output: expected result (advisory)

    Args:
        config: Soothe configuration

    Returns:
        CompiledStateGraph with attached protocols and middlewares

    Example:
        # Layer 1 factory
        config = SootheConfig.from_file("config.yml")
        agent = create_soothe_agent(config)

        # Layer 2 execution with hints
        stream = await agent.astream(
            input="Execute: Find config files",
            config={
                "configurable": {
                    "thread_id": "thread-123",
                    "soothe_step_tools": ["glob", "grep"],
                    "soothe_step_expected_output": "Config file list"
                }
            }
        )

        # ExecutionHintsMiddleware injects hints into system prompt:
        # "Suggested tools: glob, grep. Expected output: Config file list."
        # LLM decides final tool selection based on context
    """
```

### 6.3 Code Comments

Add inline comments referencing RFC-0023:

```python
# Layer 1 CoreAgent factory (RFC-0023)
# Creates runtime with built-in tools, subagents, middlewares
# Receives execution hints from Layer 2 via config.configurable
agent = create_deep_agent(
    model=resolved_model,
    tools=all_tools or None,
    system_prompt=config.resolve_system_prompt(),
    middleware=all_middleware,  # Includes ExecutionHintsMiddleware
    subagents=all_subagents or None,
    skills=all_skills or None,
    memory=config.memory or None,
    checkpointer=checkpointer,
    store=store,
    backend=resolved_backend,
    interrupt_on=interrupt_on,
    debug=config.debug,
)

# Attach protocol instances for Layer 1 access (RFC-0023)
agent.soothe_context = resolved_context
agent.soothe_memory = resolved_memory
agent.soothe_planner = resolved_planner
agent.soothe_policy = resolved_policy
agent.soothe_durability = goal_engine
agent.soothe_config = config
agent.soothe_subagents = all_subagents
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

**File**: `tests/unit/test_execution_hints_middleware.py`

**Test Cases**:

1. `test_extract_hints_all_present`:
   - Config with all three hints
   - Verify extraction returns all hints

2. `test_extract_hints_tools_only`:
   - Config with only tools hint
   - Verify extraction returns only tools

3. `test_extract_hints_none_present`:
   - Config with no hints
   - Verify extraction returns None

4. `test_format_hints_all_present`:
   - Hints with tools, subagent, expected_output
   - Verify formatted text includes all parts

5. `test_format_hints_missing_tools`:
   - Hints without tools
   - Verify tools not mentioned in formatted text

6. `test_inject_hinto_system_prompt`:
   - Agent state with system_prompt
   - Verify prompt enhanced with hints

7. `test_no_injection_when_no_hints`:
   - Config with no hints
   - Verify state unchanged

**File**: `tests/unit/test_executor_hints.py`

**Test Cases**:

1. `test_executor_passes_tools_hint`:
   - StepAction with tools hint
   - Verify config.configurable includes `soothe_step_tools`

2. `test_executor_passes_subagent_hint`:
   - StepAction with subagent hint
   - Verify config.configurable includes `soothe_step_subagent`

3. `test_executor_passes_expected_output`:
   - StepAction with expected_output
   - Verify config.configurable includes `soothe_step_expected_output`

4. `test_executor_handles_missing_hints`:
   - StepAction with None hints
   - Verify config.configurable includes None values

5. `test_executor_logs_hints`:
   - Verify logging output includes hints information

### 7.2 Integration Tests

**File**: `tests/integration/test_layer2_layer1_bridge.py`

**Test Scenarios**:

1. **Complete Integration Flow**:
   ```python
   # Create Layer 2 decision with hints
   decision = AgentDecision(
       steps=[
           StepAction(
               description="Find config files",
               tools=["glob", "grep"],
               expected_output="Config file list"
           )
       ],
       execution_mode="sequential"
   )

   # Execute via Executor
   executor = Executor(core_agent)
   results = await executor.execute(decision, state)

   # Verify hints passed to CoreAgent
   # (Mock CoreAgent, inspect config.configurable)
   ```

2. **LLM Sees Hints in Prompt**:
   ```python
   # Mock LLM to capture system prompt
   # Execute step with hints
   # Verify LLM received enhanced prompt with hints
   ```

3. **LLM Follows Valid Hint**:
   ```python
   # StepAction with tools=["read_file"]
   # Execute step
   # Verify LLM chose read_file tool
   ```

4. **LLM Overrides Invalid Hint**:
   ```python
   # StepAction with tools=["nonexistent_tool"]
   # Execute step
   # Verify LLM chose different tool
   ```

5. **Step Without Hints Works**:
   ```python
   # StepAction with tools=None
   # Execute step
   # Verify execution succeeds (backward compatibility)
   ```

**File**: `tests/integration/test_coreagent_with_hints.py`

**Test Scenarios**:

1. **Middleware Integration in Stack**:
   - Create CoreAgent with ExecutionHintsMiddleware
   - Execute with hints in config
   - Verify middleware processed hints

2. **End-to-End Execution**:
   - Full CoreAgent execution with hints
   - Verify LLM response includes consideration of hints
   - Verify tool calls match expected behavior

---

## 8. Configuration

### 8.1 Optional Configuration

**File**: `config/config.yml`

Add optional execution hints configuration:

```yaml
execution:
  hints:
    # Enable Layer 2 → Layer 1 hints propagation
    enabled: true

    # Hints are advisory (LLM decides final execution)
    # If false, hints would be mandatory (not implemented)
    advisory: true
```

**Default Behavior**: If configuration section omitted, hints are enabled and advisory by default.

### 8.2 Configuration Access

ExecutionHintsMiddleware can optionally check configuration:

```python
class ExecutionHintsMiddleware(AgentMiddleware):
    def __init__(self, config: SootheConfig | None = None):
        self.config = config
        self.enabled = config.execution.hints.enabled if config else True

    async def process_agent_input(self, state, config):
        if not self.enabled:
            return  # Skip hint processing if disabled

        # ... rest of implementation
```

---

## 9. Migration Notes

### 9.1 Backward Compatibility

**Fully Backward Compatible** - No Breaking Changes:

✅ **API Compatibility**:
- `create_soothe_agent()` signature unchanged
- `agent.astream()` signature unchanged
- `Executor._execute_step()` signature unchanged (internal method)

✅ **Behavior Compatibility**:
- Steps without hints work exactly as before
- ExecutionHintsMiddleware does nothing if no hints present
- CoreAgent execution unchanged for non-hint cases

✅ **Data Compatibility**:
- StepAction fields (`tools`, `subagent`, `expected_output`) already exist
- No schema changes required

### 9.2 Migration Steps

**For Existing Code**:
- No changes required
- Hints are optional, existing steps work unchanged

**For New Layer 2 Integration**:
- Planner can populate `step.tools`, `step.subagent`, `step.expected_output`
- Executor automatically passes hints to CoreAgent
- ExecutionHintsMiddleware automatically processes hints

### 9.3 Version Strategy

**Recommended**: Release as **minor version bump** (backward compatible feature addition)

- Existing users unaffected
- New users can adopt hints incrementally
- No migration guide required

---

## 10. RFC Updates

### 10.1 RFC-0023 Updates

**Add Section**: "Layer 2 Integration Contract"

```markdown
## Layer 2 Integration Contract

### Execution Hints

Layer 2's ACT phase passes advisory execution hints to Layer 1 CoreAgent via `config.configurable`:

| Hint Field | Purpose | Example |
|------------|---------|---------|
| `soothe_step_tools` | Suggested tools for execution | `["read_file", "grep"]` |
| `soothe_step_subagent` | Suggested subagent to invoke | `"browser"` |
| `soothe_step_expected_output` | Expected result description | `"File contents matching pattern"` |

**Hint Behavior**:
- **Advisory, not mandatory**: Layer 1 LLM considers hints but may choose different approach
- **ExecutionHintsMiddleware**: Injects hints into system prompt for LLM consideration
- **Natural integration**: LLM sees hints in decision-making context, decides final execution

**Example Integration**:

```python
# Layer 2 Planner decision
decision = AgentDecision(
    steps=[
        StepAction(
            description="Find configuration files",
            tools=["glob", "grep"],
            expected_output="List of config files"
        )
    ],
    execution_mode="sequential"
)

# Executor passes hints to Layer 1
await core_agent.astream(
    input="Execute: Find configuration files",
    config={
        "configurable": {
            "thread_id": "thread-123",
            "soothe_step_tools": ["glob", "grep"],
            "soothe_step_expected_output": "List of config files"
        }
    }
)

# CoreAgent LLM receives:
# System prompt: "You are Soothe agent...
#
# Execution hints: Suggested tools: glob, grep. Expected output: List of config files.
# Consider using the suggested approach first, but decide based on what works best."
#
# → LLM decides to use glob first, then grep for filtering
```

**Architecture Principle**: This integration honors the three-layer separation:
- Layer 2 controls **what to execute** (step content + tool/subagent suggestions)
- Layer 1 handles **how to execute** (runtime decisions with hints as context)
```

### 10.2 RFC-0008 Updates

**Update Section**: "ACT Phase" to mention hint propagation

```markdown
### ACT Phase Implementation

The ACT phase executes steps via Layer 1 CoreAgent, passing execution hints:

```python
# Executor extracts StepAction hints
config = {
    "configurable": {
        "thread_id": thread_id,
        "soothe_step_tools": step.tools,           # Layer 2 planning
        "soothe_step_subagent": step.subagent,     # Layer 2 planning
        "soothe_step_expected_output": step.expected_output  # Layer 2 planning
    }
}

# Delegate execution to Layer 1
stream = await core_agent.astream(
    input=f"Execute: {step.description}",
    config=config
)
```

**Hint Integration**: Layer 1's ExecutionHintsMiddleware injects hints into system prompt, allowing LLM to consider Layer 2's planning suggestions during execution.
```

---

## 11. Implementation Checklist

### 11.1 Phase 1: CoreAgent Documentation (Day 1)

- [ ] Update `core/agent.py` docstring with Layer 1 responsibilities
- [ ] Add code comments referencing RFC-0023
- [ ] Document protocol attachments
- [ ] Document execution interface with hints support
- [ ] Create `docs/core_agent_layer1.md` architecture overview

### 11.2 Phase 2: ExecutionHintsMiddleware (Day 1-2)

- [ ] Create `middleware/execution_hints.py`
- [ ] Implement `ExecutionHintsMiddleware` class
- [ ] Implement `_extract_hints()` method
- [ ] Implement `_format_hints()` method
- [ ] Implement `process_agent_input()` method
- [ ] Wire middleware into `create_soothe_agent()` stack
- [ ] Write unit tests

### 11.3 Phase 3: Executor Bridge (Day 2)

- [ ] Update `executor.py` `_execute_step()` method
- [ ] Extract `step.tools`, `step.subagent`, `step.expected_output`
- [ ] Pass hints via `config.configurable`
- [ ] Update logging to show hints
- [ ] Write unit tests

### 11.4 Phase 4: Integration Testing (Day 3)

- [ ] Write `test_layer2_layer1_bridge.py`
- [ ] Test complete integration flow
- [ ] Test LLM sees hints in prompt
- [ ] Test LLM follows valid hints
- [ ] Test LLM overrides invalid hints
- [ ] Test steps without hints (backward compatibility)
- [ ] Write `test_coreagent_with_hints.py`

### 11.5 Phase 5: Documentation & RFC (Day 3-4)

- [ ] Update RFC-0023 with integration contract
- [ ] Update RFC-0008 with hint propagation
- [ ] Create architecture diagrams
- [ ] Update user guide
- [ ] Run `./scripts/verify_finally.sh`
- [ ] All tests passing

---

## 12. Success Criteria

✅ **Layer 1 CoreAgent Formalized**:
- Clear documentation of Layer 1 responsibilities
- Public interface documented
- Protocol attachments documented
- RFC-0023 references in code

✅ **Integration Bridge Implemented**:
- ExecutionHintsMiddleware created and wired
- Executor passes hints via config
- Hints propagate from StepAction → CoreAgent
- Advisory nature preserved

✅ **Testing Complete**:
- Unit tests for ExecutionHintsMiddleware passing
- Unit tests for Executor bridge passing
- Integration tests for Layer 2 → Layer 1 flow passing
- Backward compatibility verified

✅ **Documentation Updated**:
- RFC-0023 updated with integration contract
- RFC-0008 updated with hint propagation
- Code comments reference RFCs
- User guide updated

✅ **Verification Passed**:
- `./scripts/verify_finally.sh` succeeds
- All existing tests still pass
- No breaking changes

---

## 13. Timeline

**Total Duration**: 4 days

- **Day 1**: CoreAgent documentation + ExecutionHintsMiddleware implementation
- **Day 2**: Executor bridge implementation + unit tests
- **Day 3**: Integration tests + RFC updates
- **Day 4**: Final verification, documentation polish

---

## 14. Related Documents

- [RFC-0023](../specs/RFC-0023-coreagent-runtime.md) - Layer 1 Specification
- [RFC-0008](../specs/RFC-0008-agentic-goal-execution-loop.md) - Layer 2 Specification
- [RFC-0007](../specs/RFC-0007-autonomous-goal-management-loop.md) - Layer 3 Specification
- [IG-097](./IG-097-layer2-loopagent-implementation.md) - Layer 2 Implementation Guide

---

## 15. Changelog

### 2026-03-29
- Initial design draft created
- CoreAgent Layer 1 formalization design
- StepAction → CoreAgent integration bridge design
- ExecutionHintsMiddleware design
- Executor bridge design
- Testing strategy defined
- RFC update plan defined
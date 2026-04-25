# Analysis: Subagents in Plan Steps

## Question

Can we use subagents in plan steps? Show concrete examples.

## Answer

**Yes, subagents can be used in plan steps.** The architecture supports three mechanisms:

### 1. Explicit Subagent Field in StepAction

**Schema** (`schemas.py:14-31`):
```python
class StepAction(BaseModel):
    """Single step in execution strategy."""
    id: str
    description: str
    tools: list[str] | None = None
    subagent: str | None = None  # ← Subagent field
    expected_output: str
    dependencies: list[str] | None = None
```

**Usage in Executor** (`executor.py:680-681`):
```python
configurable: dict[str, Any] = {
    "thread_id": thread_id,
    "soothe_step_tools": step.tools,
    "soothe_step_subagent": step.subagent,  # ← Passed to CoreAgent
    "soothe_step_expected_output": step.expected_output,
}
```

**Middleware Injection** (`ExecutionHintsMiddleware`):
```python
# Extract hints from config
hints = {
    "tools": ["glob", "grep"],
    "subagent": "browser",  # ← Subagent hint
    "expected_output": "Config file list"
}

# Inject into system prompt
"Suggested subagent: browser"
```

### 2. Execution Hint in PlanStep

**PlanStep Schema** (`protocols/planner.py:12-31`):
```python
class PlanStep(BaseModel):
    id: str
    description: str
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    result: str | None = None
    depends_on: list[str] = []
```

**LLM Planner can set execution_hint** (`planner.py:643-644`):
```python
"- execution_hint: 'tool' (direct tool), 'subagent' (delegate), 'auto' (LLM reasoning)",
"- If user requests specific subagent, set execution_hint='subagent'",
```

### 3. Preferred Subagent Override

**Mechanism** (`planner.py:689-709`):
```python
@staticmethod
def _apply_preferred_subagent(plan: Plan, subagent_name: str) -> Plan:
    """Override plan execution hints to route through an explicitly requested subagent.
    
    Skips the first step (typically "understand requirements") and the last
    step if it looks like a summary/validation step, so only the core action
    steps are delegated.
    """
    action_steps = plan.steps[1:] if len(plan.steps) > 1 else plan.steps
    for step in action_steps:
        if step.execution_hint in ("tool", "auto"):
            step.execution_hint = "subagent"
            lowered = f"{step.description[0].lower()}{step.description[1:]}"
            step.description = f"Using the {subagent_name} subagent, {lowered}"
    logger.info("Applied preferred_subagent=%s to %d step(s)", subagent_name, len(action_steps))
    return plan
```

## Concrete Examples

### Example 1: Browser Subagent in Step

**Test case** (`test_execution_hints_middleware.py:18-27`):
```python
config = {
    "configurable": {
        "thread_id": "test-thread",
        "soothe_step_tools": ["glob", "grep"],
        "soothe_step_subagent": "browser",  # ← Browser subagent
        "soothe_step_expected_output": "Config file list",
    }
}

hints = middleware._extract_hints(config)
assert hints["subagent"] == "browser"
```

### Example 2: Preferred Subagent Configuration

**Test case** (`test_system_prompt_optimization.py:279`):
```python
# Unified classification can specify preferred subagent
preferred_subagent="browser",  # ← Forces browser for action steps
```

**Planner applies preferred subagent** (`planner.py:342-347`):
```python
preferred_subagent = getattr(context.unified_classification, "preferred_subagent", None)
if preferred_subagent:
    plan = self._apply_preferred_subagent(plan, preferred)
```

### Example 3: Multi-Step Plan with Claude Subagent

**Hypothetical scenario** (architecture supports this):
```python
plan = Plan(
    goal="Analyze codebase and generate documentation",
    steps=[
        PlanStep(
            id="step_1",
            description="Understand project structure",
            execution_hint="tool",  # ← Direct tools
        ),
        PlanStep(
            id="step_2",
            description="Analyze code patterns and dependencies",
            execution_hint="subagent",  # ← Claude subagent
        ),
        PlanStep(
            id="step_3",
            description="Generate documentation files",
            execution_hint="tool",  # ← Direct tools
        ),
    ]
)
```

## Display Format

When subagent is used in a step, the CLI display shows:

```
⏩ Analyze code patterns and dependencies
  └─ ⚙ Task(claude, "Analyze code patterns and dependencies")
  └─ ✓ Completed (1500ms)
```

**Key points:**
1. Step header shows step description
2. Task tool shows subagent name + quoted description
3. Result shows brief completion status (IG-261)
4. Tree branch `└─` when inside step context

## Implementation Flow

**Step execution with subagent:**

1. **Planner** creates `StepAction` with `subagent="claude"`
2. **Executor** passes `soothe_step_subagent="claude"` to CoreAgent config
3. **ExecutionHintsMiddleware** extracts hint and injects into system prompt:
   ```
   Suggested subagent: claude
   Expected output: Code pattern analysis report
   ```
4. **CoreAgent** uses hint to prioritize Task tool with specified subagent
5. **Task tool** invoked with `subagent_type="claude"`
6. **Result** captured in StepResult with outcome metadata

## Use Cases

**Appropriate for subagent delegation:**
- Complex multi-step operations (browser automation, code analysis)
- Tasks requiring external context (web research, file exploration)
- Operations needing specialized capabilities (Claude's full agent features)

**Not appropriate:**
- Simple file reads → use `read_file` directly
- Basic shell commands → use `execute` directly
- Single-tool operations → use direct tools

## References

- RFC-404: Planner Protocol Architecture
- RFC-211: Outcome Metadata (Step execution results)
- IG-261: Task tool display polish (quoted descriptions, brief results)
- `schemas.py`: StepAction model (line 14-31)
- `executor.py`: Subagent hint injection (line 680-681)
- `planner.py`: Preferred subagent override (line 689-709)
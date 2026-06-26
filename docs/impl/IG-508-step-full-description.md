# IG-508: Step Full Description for Enhanced Execution Context

**Status**: Implemented (2026-06-26)

## Problem

When a complex goal is decomposed into steps, essential context from the original goal
is lost during execution. The step `description` field is constrained to ~20 words,
losing critical details like file paths, specific identifiers, and key parameters.

Example:
- **Original goal**: `"analyze ~/.soothe/logs/soothe.log of loop 3328, classify errors, analyze why 'Write unit tests' step failed with 'Stream ended unexpectedly'"`
- **Step description**: `"Extract loop 3328 log entries and classify all errors found"` — **Lost: file path, specific failure context**

## Solution

1. Add `full_description` field to `PlanGenerateStep` and `StepAction` schemas
2. Keep `description` as brief summary (~20 words) for TUI display and logging
3. `full_description` contains detailed execution prompt (~50-150 words) with essential inputs
4. Simplify execute-step message: remove INTENT, merge TASK into EXECUTION HINTS

## Changes

### 1. Schema Changes (`schemas.py`)

**PlanGenerateStep**:
```python
class PlanGenerateStep(BaseModel):
    id: str
    description: str  # Brief summary (under 20 words) for TUI/logging
    full_description: str | None = None  # Detailed execution context (50-150 words)
    expected_output: str = "Step completed successfully"
    dependencies: list[str] | None = None
    kind: StepKind = "action"
    questions: list[str] | None = None
```

**StepAction**:
```python
class StepAction(BaseModel):
    id: str
    description: str  # Brief summary (under 20 words) for TUI/logging
    full_description: str | None = None  # Detailed execution context
    expected_output: str = "Step completed successfully"
    dependencies: list[str] | None = None
    kind: StepKind = "action"
    questions: list[str] | None = None
```

**Conversion functions**: Add `full_description` mapping in both directions.

### 2. Planner Prompt Changes (`planner.py`)

Update JSON output spec in `_build_plan_prompt`:
```python
output_spec = [
    '"steps": [',
    '  {',
    '    "id": "S_1",',
    '    "description": "<brief summary, under 20 words>",',
    '    "full_description": "<detailed execution prompt with file paths, identifiers, key inputs>",',
    '    "expected_output": "<expected result>"',
    '    "execution_hint": "tool"',
    '  }',
    ']',
]
```

Add rules:
```
- description: Brief summary for TUI display (under 20 words)
- full_description: Detailed execution context (50-150 words) including:
  - Key file paths, URLs, identifiers
  - Specific parameters or values from the goal
  - Context needed to execute without referencing original goal
```

### 3. Executor Changes (`executor.py`)

Two locations need update (line ~1552 and ~2200):

```python
# Use full_description for execution, fallback to description
step_goal_text = step.full_description or step.description

# Build enhanced EXECUTION HINTS with merged TASK instructions
hints_parts: list[str] = []
if wire_subagent:
    hints_parts.append(f"Suggested subagent: {wire_subagent}")
if step.expected_output:
    hints_parts.append(f"Expected output: {step.expected_output}")

# Merge TASK into EXECUTION HINTS
hints_parts.append(
    "Execute the step described in GOAL above, using suggested approach when provided, "
    "and produce output matching the expected output specification"
)

execution_hints = ". ".join(hints_parts) if hints_parts else None
```

### 4. UserMessageBuilder Changes (`user_message.py`)

`build_execute_step_message`:
- Remove `intent_type` and `task_complexity` parameters (no INTENT section)
- Remove TASK section
- EXECUTION HINTS now contains merged task instructions

```python
def build_execute_step_message(
    self,
    step_description: str,
    *,
    execution_hints: str | None = None,
    workspace_state: str | None = None,
    skill_context: str | None = None,
    mcp_resource_blocks: list[str] | None = None,
) -> str:
    sections: list[tuple[str, str]] = [
        ("GOAL", _goal_text(step_description)),
    ]

    if execution_hints:
        sections.append(("EXECUTION HINTS", execution_hints))

    # ... SKILL CONTEXT, MCP RESOURCES, WORKSPACE STATE, TIMESTAMP ...

    return _render_sections(sections)
```

### 5. Files to Modify

| File | Change |
|------|--------|
| `foundation/loop/state/schemas.py` | Add `full_description` to PlanGenerateStep, StepAction |
| `foundation/loop/planning/planner.py` | Update JSON spec + prompt rules |
| `foundation/loop/engine/executor.py` | Use full_description, merge TASK into hints |
| `foundation/loop/prompts/user_message.py` | Remove INTENT/TASK, simplify signature |
| `foundation/loop/planning/dag.py` | Handle full_description in DAG assembly |
| `foundation/loop/orchestrator/nodes/execute_steps.py` | Pass full_description |
| `tests/unit/core/prompts/test_user_envelope.py` | Update tests |

### 6. Backward Compatibility

- `full_description` is optional (`str | None`)
- Executor falls back to `description` when `full_description` is None
- Old plan JSON without `full_description` works unchanged

## Implementation Order

1. Schema changes (schemas.py)
2. UserMessageBuilder changes (user_message.py)
3. Executor changes (executor.py)
4. Planner changes (planner.py)
5. Tests update
6. Run `./scripts/verify_finally.sh`
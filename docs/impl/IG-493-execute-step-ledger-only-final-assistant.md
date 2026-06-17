# IG-493: Execute-Step Ledger Records Only Final Assistant Response

## Problem

The execute-step to ledger message mapping was capturing `delegate_final` (raw tool output JSON) instead of the final assistant's synthesized response. For example:

**Execute-step output**:
1. AIMessage with task tool call
2. ToolMessage with JSON: `{"target": "...", "summary": "..."}`
3. AIMessage with formatted result: `## Result\n\n**Total Files: 312**...`

**Old behavior**: Ledger recorded `delegate_final` (raw JSON from step 2)
**Expected**: Ledger records final AIMessage (step 3 - user-facing synthesis)

## Solution

Simplify the rule: **Ledger records only CoreAgent input + final assistant response.**

Tool outputs (`delegate_final`, `ToolMessage` content) are never recorded to the ledger. The final assistant response is the user-facing synthesis of all tool results.

## Changes

### `executor.py`

Removed `_is_single_task_delegation_step` and `_extract_post_tool_call_assistant_text` methods.

Simplified `_resolve_execute_step_ledger_ai_content`:
```python
def _resolve_execute_step_ledger_ai_content(
    self, *, step_messages: list[BaseMessage], delegate_final: str | None
) -> str:
    """Resolve execute-step ledger AI content: only final assistant response.

    IG-493: For step execution, the ledger records only:
    1. CoreAgent input message (HumanMessage)
    2. Final assistant response (AIMessage/AIMessageChunk text)

    Tool outputs (delegate_final, ToolMessage content) are never recorded.
    """
    _ = delegate_final  # Ignored per IG-493
    return self._extract_final_assistant_text_from_step_messages(step_messages)
```

### Tests

Updated `test_executor_parallel_ledger_ig374.py` to reflect the new behavior:
- Removed tests for `_is_single_task_delegation_step` and `_extract_post_tool_call_assistant_text`
- Added test verifying delegate_final is ignored
- Updated existing tests to assert final AIMessage content is used

## Impact

- **Plan-assess**: Receives user-facing synthesized output, not raw tool JSON
- **Prior progress digest**: Still captures tool evidence excerpts separately via `_update_prior_progress`
- **TUI/WebSocket**: No change - tool outputs are streamed live via events

## Migration

No migration needed - this is a behavior fix. The ledger content improves but the schema remains unchanged.
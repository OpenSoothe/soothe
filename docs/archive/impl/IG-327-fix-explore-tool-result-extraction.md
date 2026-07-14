# IG-327: Fix explore tool result extraction

## Problem

The explore subagent finds 0 matches because `execute_action_node` extracts findings from `ToolMessage.artifact`, but LangGraph's `ToolNode` populates `ToolMessage.content` instead, leaving `artifact=None`.

**Observed behavior:**
- Explore runs 4 iterations (medium thoroughness)
- Each iteration: "found 0" → continues → still 0 → finishes with 0 matches
- Duration: 2124ms but no results

**Root cause:**
ToolNode wraps tool return values into `content` field:
```python
# Tool returns: ["file1.py", "file2.py"]
# ToolMessage becomes: ToolMessage(content="file1.py\nfile2.py", artifact=None)
```

But engine.py:execute_action_node (lines 228-271) checks `artifact`:
```python
artifact = tool_msg.artifact  # None!
if tool_name == "glob" and isinstance(artifact, list):  # False!
    # findings extraction skipped
```

## Fix

Extract findings from `tool_msg.content` instead of `tool_msg.artifact`.

Different tools return different types:
- glob, ls: return `list[str]` → ToolMessage.content is string (newline-separated) or list
- grep: returns `list[dict]` → ToolMessage.content is string or list
- read_file: returns `str` → ToolMessage.content is string
- file_info: returns `str` → ToolMessage.content is string

**Strategy:**
1. Check both `artifact` (if tool explicitly sets it) and `content`
2. Handle string content by parsing (glob/ls: split by newline)
3. Handle list/dict content directly
4. Add logging to show what's actually extracted

## Implementation

1. Update `execute_action_node` to use `content` field
2. Add result extraction logging for debugging
3. Handle different content formats (str, list, dict)
4. Test with actual filesystem tools

## Verification

✅ All tests passing (1396 passed, 16 skipped)
- Run: `./scripts/verify_finally.sh` ✅
- Fixed TypeError in synthesize_node when snippet is None
- Added logging to show extraction counts per tool

## Impact

Before fix:
- Explore runs 4 iterations with 0 findings each iteration
- Duration: 2124ms but no results
- Tool results ignored because `artifact=None`

After fix:
- Tool results extracted from `ToolMessage.content`
- Findings accumulated across iterations
- Logging shows: "Explore: glob found N paths", "Explore: grep found N matches", etc.
- Synthesize node can build findings detail from actual data
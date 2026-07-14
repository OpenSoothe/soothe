# IG-263: Tool Content Retrieval Fix - Agent/Synthesis Behavior

**Status**: In Progress  
**Date**: 2026-04-25  
**Related**: IG-262 (CLI display fixes)  
**Critical Discovery**: ToolMessage.content already HAS actual content!

---

## CRITICAL DISCOVERY 🎯

### What I Found

**ToolMessage.content ALREADY contains actual file content!**

```python
# Deepagents read_file tool (.venv/lib/python3.12/site-packages/deepagents/middleware/filesystem.py)
def _handle_read_result(...):
    content = read_result.file_data["content"]  # ACTUAL FILE CONTENT
    content = format_content_with_line_numbers(content, ...)  # Add line numbers
    return _truncate(content, ...)  # Returns plain STRING with actual content
```

**For text files**: Returns actual content as plain string  
**For binary files**: Returns ToolMessage with binary blocks  

### Complete Flow Evidence

1. **Tool Execution**: 
   - `read_file("/README.md")` → returns `"# Soothe...\n(actual 10 lines)"`
   - Becomes `ToolMessage.content = "# Soothe...\n(actual 10 lines)"`

2. **Conversation History**: 
   - ToolMessage in conversation HAS actual content ✅

3. **CLI Display (stderr)**: 
   - `ToolOutputFormatter.format()` creates `"✓ Read 5.5 KB (100 lines)"` (semantic summary)
   - **ONLY for stderr display** - keeps output clean

4. **Agent Execution**:
   - CoreAgent sees ToolMessage.content = actual content
   - Agent outputs `"Successfully read..."` (completion reasoning, NOT content) ⚠️

5. **Synthesis**:
   - Method 1 (reuse): `last_execute_assistant_text = "Successfully read..."` (NO CONTENT)
   - Method 2 (synthesis): CoreAgent sees ToolMessage but agent doesn't output content

---

## Root Cause

**ToolMessage ALREADY has actual content!**

The issue is NOT ToolMessage structure - it's agent/synthesis behavior:

1. Agent sees ToolMessage with actual content during Execute
2. Agent outputs completion reasoning instead of content
3. Therefore: both synthesis methods cannot produce content

**Previous recommendation was WRONG** ❌  
**No need to change ToolMessage structure** ✅

---

## NEW Recommendation

**Fix agent/synthesis behavior to extract content from ToolMessage!**

### Option A: Agent Outputs Content During Execute

**Location**: Agent system prompt or behavior

**Change**: When agent processes ToolMessage with file content, it should output:
```
"Here are the 10 lines of README.md:

# Soothe — Beyond Yet-Another-Agent Framework
<logo>
...
```

**Pros**:
- Simple fix - agent outputs what user expects
- Works with Method 1 (reuse)

**Cons**:
- Requires agent prompt changes
- Agent might still misinterpret intent

### Option B: Synthesis Extracts Content from ToolMessage

**Location**: agent_loop.py synthesis logic (lines 330-399)

**Change**: When `run_synth=True`, synthesis request should instruct CoreAgent:
```python
report_request = f"""Based on the complete execution history, generate a comprehensive final report.

IMPORTANT: For content-retrieval tools (read_file, web_search, etc.), INCLUDE THE ACTUAL CONTENT from tool results.

Tool results are in ToolMessage.content - extract and present actual content, not just summaries.
```

**Pros**:
- More reliable - synthesis directly accesses ToolMessage.content
- Works for complex multi-tool scenarios
- Better for Method 2 (synthesis)

**Cons**:
- More complex synthesis logic

---

## Recommended Fix: Hybrid A+B

**Phase 1**: Update synthesis request to extract content (Option B)
**Phase 2**: Consider agent prompt improvements (Option A) as enhancement

---

## Implementation Plan

### Phase 1: Analysis ✅ Complete

- ✅ Discovered ToolMessage.content has actual content
- ✅ Verified semantic summary is only for display
- ✅ Identified root cause: agent/synthesis behavior

### Phase 2: Synthesis Extraction Fix

- [ ] Modify synthesis request in agent_loop.py (lines 352-360)
- [ ] Add explicit instruction to extract content from ToolMessage
- [ ] Test with read_file scenarios
- [ ] Verify final stdout shows actual content

### Phase 3: Agent Behavior Improvement (Optional)

- [ ] Update agent system prompts
- [ ] Instruct agent to output content for "read/show" intents
- [ ] Test agent outputs content during Execute

---

## Technical Details

### Current Synthesis Request

```python
# agent_loop.py lines 352-360
report_request = f"""Based on the complete execution history in this thread, generate a comprehensive final report for the goal: {goal}

The report should:
1. Summarize what was accomplished
2. Highlight key findings or outputs
3. Provide actionable results or deliverables
4. Be well-structured with clear sections

Use all tool results and AI responses available in the conversation history to create a comprehensive, coherent final report."""
```

### Proposed Synthesis Request

```python
report_request = f"""Based on the complete execution history in this thread, generate a comprehensive final report for the goal: {goal}

The report should:
1. Summarize what was accomplished
2. **INCLUDE ACTUAL CONTENT** from content-retrieval tools (read_file, web_search, fetch_url, etc.)
   - Extract content directly from ToolMessage.content in conversation history
   - Present the actual content, not just semantic summaries
3. Provide actionable results or deliverables
4. Be well-structured with clear sections

For file reading tasks: Include the actual file content (line-numbered format).
For web/research tasks: Include actual search results or fetched content.

Use all tool results and AI responses available in the conversation history to create a comprehensive, coherent final report."""
```

---

## No Need for ToolMessage Changes

**ToolMessage structure is already correct!**

- ToolMessage.content = actual file content ✅
- ToolOutputFormatter creates semantic summaries for display ✅  
- Conversation history has actual content ✅

**Only need to fix synthesis/agent behavior!**

---

## Progress

- ✅ Phase 1: Analysis complete (major discovery - ToolMessage.content has actual content)
- ✅ Phase 2: Synthesis extraction fix implemented
- ⬜ Phase 3: Agent behavior improvement optional
- 🔄 Running verification suite

### Implementation Details

**Modified file**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`
**Lines**: 350-366 (synthesis request message)

**Changes**:
- Added explicit instruction to extract content from ToolMessage
- Listed content-retrieval tools (read_file, web_search, etc.)
- Emphasized "show actual content, not just summaries"
- Added "IMPORTANT" note to guide CoreAgent behavior

**Expected result**: When synthesis runs (Method 2), CoreAgent will extract actual file content from ToolMessage and present it in final report.

### Testing Needed

Manual test:
```bash
soothe --no-tui -p "read 10 lines of project readme"
```

Expected output:
- stderr: Shows semantic summary "✓ Read 5.5 KB (100 lines)"
- stdout: Shows actual README content (10 lines)
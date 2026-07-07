# IG-262 & IG-263: CLI Display Fixes - Current Status

**Date**: 2026-04-25
**Status**: Partial completion - synthesis fix working but emission pipeline broken

---

## Executive Summary

### IG-262: Indentation Fix ✅ COMPLETE

**Issue**: Reasoning lines showed unexpected indentation after [keep] judgement
**Fix**: Changed `format_reasoning()` from `level=3` (indented) to `level=2` (flat)
**Status**: ✅ Fixed, verified, ready to commit

### IG-263: Missing File Content ⚠️ PARTIAL

**Issue**: User expects to see actual file content, but only sees completion message
**Discovery**: ToolMessage.content ALREADY has actual content! (not a structure problem)
**Fix**: Updated synthesis request to extract content from ToolMessage
**Status**: ✅ Synthesis working perfectly, ❌ Emission pipeline broken

---

## Critical Discoveries

### Discovery 1: ToolMessage Has Actual Content 🎯

**Previous assumption (WRONG)**: ToolMessage.content = semantic summary "Read 5.5 KB"
**Actual reality (CORRECT)**: ToolMessage.content = actual file content "# Soothe...\n..."

```python
# Deepagents read_file tool:
def _handle_read_result(...):
    content = read_result.file_data["content"]  # ACTUAL FILE CONTENT
    return _truncate(content, ...)  # Returns actual content as string

# This becomes:
ToolMessage(content="# Soothe — Beyond...\n(actual 10 lines)...")  ✅
```

**Implications**:
- Semantic summary is ONLY for stderr display (ToolOutputFormatter)
- Conversation history HAS actual content
- Both synthesis methods (reuse/synthesis) have access to content
- Problem is NOT ToolMessage structure

### Discovery 2: Synthesis Fix Works Perfectly ✅

**What we did**: Modified synthesis request to instruct CoreAgent to extract content from ToolMessage

**Modified code**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py` lines 350-366

**Synthesis request now says**:
```python
report_request = f"""...generate final report...

2. **Include actual content** from content-retrieval tools (read_file, web_search, etc.)
   - Extract content from ToolMessage.content
   - Present actual file content, not just summaries
   - For file reading: show actual content (with line numbers)

IMPORTANT: User wants to see actual content, not confirmation messages.
```

**Verification**: Logs show CoreAgent generated:
```
'# Final Report: Read 10 Lines of Project README

## 2. Actual Content Retrieved

     1\t# ✨ Soothe — Beyond Yet-Another Agent
     2\t<div align="center">
     3\t  <img src="assets/soothe-logo.png"...>
     ...
     (1426 chars with complete README content!)
```

**Status**: ✅ Synthesis works perfectly - CoreAgent followed instructions and extracted content!

### Discovery 3: Emission Pipeline Broken ❌

**Issue**: Synthesized content (1426 chars) generated but NOT displayed to user

**Evidence**:
- User output shows only: "Successfully read README.md..."
- Logs show synthesis generated 1426 chars with actual content
- Content exists in `plan_result.full_output`
- Content lost somewhere in emission pipeline

**Flow trace**:
```python
✅ final_output = 1426 chars (synthesized content)
✅ plan_result.full_output = final_output (1426 chars)
✅ yield ("completed", {"result": plan_result})
✅ final_result = plan_result (with full_output=1426 chars)
❓ text = _agentic_final_stdout_text(full_output=1426 chars)
❓ final_stdout = text (should have content)
❓ AgenticLoopCompletedEvent(final_stdout_message=final_stdout)
❓ CLI renderer receives event with final_stdout_message
❌ stdout shows no content (BUG HERE!)
```

**Problem location**: Runner emission logic in `_runner_agentic.py` or CLI renderer emission

---

## Implementation Details

### Files Modified

**IG-262 (Indentation)**:
- `packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py`
  - Changed `format_reasoning()` from `level=3` to `level=2`
  - Status: ✅ Complete

**IG-263 (Synthesis)**:
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`
  - Lines 350-366: Updated synthesis request message
  - Added content extraction instructions
  - Status: ✅ Synthesis working, ❌ Emission broken

### Documentation Created

- `docs/impl/IG-262-cli-display-fixes.md` ✅
- `docs/impl/IG-263-tool-content-retrieval-fix.md` ✅
- `docs/impl/IG-262-263-current-status.md` ✅ (this file)

---

## What's Fixed

### ✅ IG-262: Indentation

**Before**:
```
● 🌟 [keep] Task complete...
  ● 💭 Successfully read...  (2-space indent - wrong!)
```

**After**:
```
● 🌟 [keep] Task complete...
● 💭 Successfully read...  (flat - correct!)
```

**Files**: `formatter.py` modified
**Verification**: Manual test confirmed flat layout
**Status**: Ready to commit

### ✅ IG-263: Synthesis Logic

**Before**: Synthesis request didn't instruct CoreAgent to extract content
**After**: Synthesis request explicitly instructs content extraction from ToolMessage

**Verification**: Logs show CoreAgent generated final report with actual README content (1426 chars)

**Evidence**:
```
16:29:01 - Stream completed: accumulated_chunks=1426 chars
16:29:01 - Final report generated via CoreAgent (1426 chars)
Log shows: '# Final Report...\n(actual 10 lines with content)'
```

**Status**: Synthesis logic working perfectly

---

## What's Still Broken

### ❌ IG-263: Emission Pipeline

**Issue**: Synthesized content (1426 chars) not reaching user stdout

**Symptoms**:
- User sees only: "Successfully read README.md..." (completion message)
- No actual file content displayed
- Synthesis generated content but it's lost in emission

**Hypothesis**: Problem in runner's `_agentic_final_stdout_text()` or CLI emission logic

**Need to investigate**:
1. Does `_agentic_final_stdout_text()` process the 1426 char content correctly?
2. Does it truncate/transform the content?
3. Is `final_stdout_message` populated in event correctly?
4. Does CLI renderer receive the event with correct content?
5. Does `should_emit_final_report()` return True?
6. Does `_write_stdout_final_report()` execute?
7. Where does the content get lost?

---

## Root Cause Analysis

### Original Problem

User asks: "read 10 lines of project readme"
Expected: See actual file content (10 lines)
Actual: See only completion message

### Initial Hypothesis (WRONG)

Thought: ToolMessage contains semantic summary, not actual content
Planned: Implement dual-content structure (display summary + actual content)

### Corrected Understanding (RIGHT)

Discovery: ToolMessage.content ALREADY has actual file content!
- Semantic summary is ONLY for stderr display (ToolOutputFormatter)
- Conversation history has actual content
- Problem is agent/synthesis behavior, not ToolMessage structure

### Current Understanding

1. ✅ ToolMessage has actual content (verified)
2. ✅ Synthesis extracts content correctly (verified in logs)
3. ❓ Content lost in emission pipeline (investigation needed)

---

## Next Steps Required

### Phase 1: Trace Emission Pipeline

**Priority**: HIGH - content exists but not displayed

**Investigation needed**:
1. Check `_agentic_final_stdout_text()` in `runner_agentic.py`:
   - Does it process 1426 chars correctly?
   - Does it truncate or transform content?
   - Check `_normalize_agentic_body()` implementation

2. Add debug logging to emission pipeline:
   - Log `final_stdout_message` value in event
   - Log `should_emit_final_report()` decision
   - Log `_write_stdout_final_report()` execution
   - Log content length at each step

3. Check if content IS in `final_stdout_message` but gets filtered/suppressed

**Files to investigate**:
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py` (lines 92-121, 550-564)
- `packages/soothe-cli/src/soothe_cli/cli/renderer.py` (lines 336-350)
- `packages/soothe-cli/src/soothe_cli/shared/suppression_state.py` (lines 64-92)

### Phase 2: Fix Emission Bug

**Once identified**: Fix the emission pipeline to correctly display synthesized content

**Expected behavior**:
- stderr: Shows semantic summary "✓ Read 5.5 KB (100 lines)" (progress)
- stdout: Shows synthesized content with actual README (final output)

### Phase 3: Verify End-to-End

**Test**: `soothe --no-tui -p "read 10 lines of project readme"`

**Expected output**:
```
stderr:
● I'll read the first 10 lines...
○ 🌟 [new] Read README.md...
  └─ ⚙ Read File(/README.md)
  └─ ✓ Read 5.5 KB (100 lines)  ← Semantic summary (correct)
  └─ Done [1 tools]

stdout:
# Final Report: Read 10 Lines of Project README

## 2. Actual Content Retrieved

     1\t# ✨ Soothe — Beyond Yet-Another Agent
     2\t<div align="center">
     3\t  <img src="assets/soothe-logo.png"...>
     ...  ← Actual README content (10 lines)
```

---

## Test Results

### Manual Test: April 25, 2026

**Command**: `soothe --no-tui -p "read 10 lines of project readme"`

**Result**:
```
stderr output:
● I'll read the first 10 lines...
○ 🌟 [new] Read README.md from project root...
  └─ ⚙ Read File(/README.md)
  └─ ✓ Read 517 B (10 lines)  ← Semantic summary (correct)
  └─ Done [1 tools] (6.4s)
● 🌟 [keep] Task complete: README.md first 10 lines retrieved
● 💭 Successfully read README.md...  ← NO ACTUAL CONTENT

stdout output:
(empty)  ← NO CONTENT DISPLAYED
```

**Analysis**:
- ✅ Indentation fix working (reasoning at same level as judgement)
- ✅ Synthesis generated content (verified in logs: 1426 chars)
- ❌ Content NOT displayed to user (emission pipeline broken)

---

## Code Changes Ready to Commit

### IG-262: Indentation Fix ✅

**Files**:
- `packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py`
- `packages/soothe-cli/src/soothe_cli/shared/tool_formatters/__init__.py` (import sorting)
- `packages/soothe-cli/src/soothe_cli/shared/tool_output_formatter.py` (import sorting)

**Changes**:
- `format_reasoning()` uses `level=2` (flat) instead of `level=3` (indented)
- Import sorting fixes (auto-fix by ruff)

**Status**: ✅ Verified, ready to commit

### IG-263: Synthesis Fix ✅ (Partial)

**Files**:
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

**Changes**:
- Lines 350-366: Updated synthesis request message
- Added explicit content extraction instructions
- Instructed CoreAgent to extract actual content from ToolMessage

**Status**: ✅ Synthesis working, ❌ Emission broken (don't commit yet)

---

## Recommendations

### Immediate Actions

1. **Commit IG-262**: Indentation fix is complete and verified
2. **Investigate IG-263 emission**: Trace where synthesized content gets lost
3. **Add debug logging**: Instrument emission pipeline to identify bug location
4. **Fix emission pipeline**: Once identified, fix the content display logic
5. **Verify end-to-end**: Test complete flow with actual file content display

### Future Improvements

**Option A (if needed)**: Update agent behavior during Execute phase
- Instruct agent to output content directly when processing ToolMessage
- This would enable Method 1 (reuse) to work better
- But synthesis fix already works, so this is optional enhancement

**Option B**: Keep synthesis fix as primary solution
- Synthesis (Method 2) works perfectly now
- Just need to fix emission pipeline
- More reliable than agent behavior changes

---

## Technical Details

### Current Synthesis Request

```python
report_request = f"""Based on the complete execution history in this thread, generate a comprehensive final report for the goal: {goal}

The report should:
1. Summarize what was accomplished
2. **Include actual content** from content-retrieval tools (read_file, web_search, fetch_url, ls, glob, etc.)
   - ToolMessage.content contains the actual file content, search results, etc.
   - Extract and present this actual content directly, not just summaries
   - For file reading: show the actual file content (with line numbers if applicable)
   - For web/research: show actual search results or fetched content
3. Provide actionable results or deliverables
4. Be well-structured with clear sections

IMPORTANT: The user wants to see the actual content retrieved, not just confirmation messages. Extract content from ToolMessage.content in the conversation history and present it comprehensively.

Use all tool results and AI responses available in the conversation history to create a comprehensive, coherent final report."""
```

**Status**: ✅ Works perfectly - CoreAgent follows these instructions

### ToolMessage Flow

```
Tool execution (deepagents):
  read_file("/README.md") → "# Soothe...\n(actual content)"
  ToolMessage.content = "# Soothe...\n(actual content)" ✅

CLI display (stderr):
  ToolOutputFormatter.format() → "✓ Read 5.5 KB (100 lines)"
  Semantic summary for stderr ✅

Conversation history:
  ToolMessage in thread → has actual content ✅

Synthesis (Method 2):
  CoreAgent extracts from ToolMessage → generates final report ✅
  
Emission pipeline:
  final_output → final_stdout_message → stdout ❌ (broken here)
```

---

## Questions to Investigate

1. Why does synthesized content (1426 chars) not reach stdout?
2. Does `_agentic_final_stdout_text()` truncate the content?
3. Is there a size limit or transformation happening?
4. Does CLI renderer receive the event correctly?
5. Does suppression logic prevent content emission?
6. Where exactly does the content get lost?

---

## Logs Evidence

### Synthesis Working

```
16:28:47 - Synthesis request sent (with content extraction instructions)
16:29:01 - LLM Response: '# Final Report...\n(actual README content)'
16:29:01 - Stream completed: accumulated_chunks=1426 chars
16:29:01 - Final report generated via CoreAgent (1426 chars)
```

### Emission Pipeline Missing

**No logs showing**:
- `final_stdout_message` value
- `_agentic_final_stdout_text()` processing
- Content emission to stdout

---

## Summary

**IG-262**: ✅ Complete - indentation fixed
**IG-263**: ⚠️ Partial - synthesis works but emission broken

**Critical findings**:
1. ToolMessage already has actual content (not a structure problem)
2. Synthesis fix works perfectly (CoreAgent generates content)
3. Emission pipeline has bug (content not reaching user)

**Next priority**: Fix emission pipeline to display synthesized content

**Files ready**: IG-262 can commit, IG-263 needs emission fix first

---

## Appendix: Key Code Locations

### ToolMessage Creation
- `.venv/lib/python3.12/site-packages/deepagents/middleware/filesystem.py`
- Lines 656-800: `read_file`, `ls`, `glob` tools
- Returns: actual content (plain string for text files)

### Semantic Summary Creation
- `packages/soothe-cli/src/soothe_cli/shared/tool_output_formatter.py`
- Creates semantic summaries for stderr display (ONLY)

### Synthesis Logic
- `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`
- Lines 330-415: Synthesis decision and execution
- Line 350-366: Synthesis request message (modified)

### Emission Pipeline
- `packages/soothe/src/soothe/core/runner/_runner_agentic.py`
- Lines 92-121: `_agentic_final_stdout_text()` (investigate this)
- Lines 550-564: Event population (investigate this)

### CLI Renderer
- `packages/soothe-cli/src/soothe_cli/cli/renderer.py`
- Lines 336-350: Emission logic (investigate this)
- Lines 141-160: `_write_stdout_final_report()` (investigate this)

### Suppression Logic
- `packages/soothe-cli/src/soothe_cli/shared/suppression_state.py`
- Lines 64-92: `should_emit_final_report()` (verify working)

---

**End of Status Report**
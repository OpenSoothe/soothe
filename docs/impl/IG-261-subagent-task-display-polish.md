# IG-261: Subagent Task CLI Display Polish

## Status: ✅ Completed

## Summary

**Implementation completed successfully.** All tests passing.

**Key changes:**
1. Task tool calls show quoted descriptions: `Task(claude, "description")`
2. Task/Research results show brief status: `✓ Completed` (no long content preview)
3. Tree branch indentation already implemented for step context
4. SubagentFormatter created for subagent category tools
5. Error handling preserved: `✗ Failed (error message)`

**Display examples:**
```
⏩ Analyze README structure
  └─ ⚙ Task(claude, "Read the first 10 lines of README")
  └─ ✓ Completed (150ms)
```

```
⚙ Task(browser, "Navigate to website")
✓ Completed (230ms)
```

## Git Changes

**Modified files:**
- `packages/soothe-cli/src/soothe_cli/shared/message_processing.py` - Quoted description args
- `packages/soothe-cli/src/soothe_cli/shared/tool_formatters/subagent.py` - New SubagentFormatter
- `packages/soothe-cli/src/soothe_cli/shared/tool_formatters/__init__.py` - Export SubagentFormatter
- `packages/soothe-cli/src/soothe_cli/shared/tool_output_formatter.py` - Route subagent category

**New file:**
- `docs/impl/IG-261-subagent-task-display-polish.md` - Implementation guide

## Overview

Polish the CLI display for subagent task (Task tool) to show consistent tree-like structure and brief results matching tool display patterns.

## Current Behavior (Before)

```
⚙ Task(claude, Read the first 10 lines of the projec...)
✓ Here are the first 10 lines of the project READ... (Here are the first 10 lines of the project README file: ``` # ✨ Soothe — Bey...) (duration)
```

**Issues:**
- Description argument not quoted
- Result showed full content preview (very long)

## Final Behavior (After)

```
└─ ⚙ Task(claude, "Read the first 10 lines of the projec...")
└─ ✓ Completed (duration_ms)
```

**Improvements:**
1. ✅ Show tree branch (`└─`) when inside step context (already implemented)
2. ✅ Quote description arguments: `Task(subagent_type, "description preview")`
3. ✅ Show brief result status: "✓ Completed" instead of long content preview

## Implementation Plan

### Phase 1: Review Current Implementation (✅ Completed)

**Findings:**
- Tree branch indentation is already implemented in CLI renderer (lines 236-238 in renderer.py)
- Task tool is registered in metadata registry with `has_header_info=True`
- Formatter functions already exist for tool calls and results

### Phase 2: Polish Display Format (✅ Completed)

**Files modified:**
1. `packages/soothe-cli/src/soothe_cli/shared/message_processing.py` - Add quoting for Task tool description
2. `packages/soothe-cli/src/soothe_cli/shared/tool_formatters/subagent.py` - New formatter for brief Task results
3. `packages/soothe-cli/src/soothe_cli/shared/tool_formatters/__init__.py` - Export SubagentFormatter
4. `packages/soothe-cli/src/soothe_cli/shared/tool_output_formatter.py` - Route subagent category to SubagentFormatter

**Changes implemented:**
- Added special handling in `format_tool_call_args` to quote description arguments for Task tool
- Format: `Task(claude, "Read the first 10 lines of the projec...")` with quotes around description
- Logic: For `task` tool, quote all arg values except `subagent_type` (which is an identifier)
- Preview length: 40 chars for description (existing truncation)
- Created SubagentFormatter to show brief "✓ Completed" status instead of full result content
- Task/Research tools no longer show long result previews inline

### Phase 3: Testing (✅ Completed)

**Verification:**
- Tree branch indentation is already implemented in CLI renderer (lines 236-237, 292-293)
- Task tool displays tree branch `└─` when inside step context
- Task tool displays flat when invoked directly by agent (not in a step)

**Test scenarios verified:**
1. ✅ Single tool call outside step context: Flat display (no tree branch)
2. ✅ Task tool inside step context: Shows tree branch `└─ ⚙ Task(...)`
3. ✅ Task result inside step context: Shows tree branch `└─ ✓ result (duration_ms)`
4. ✅ Description is quoted: `Task(claude, "description preview")`

## Success Criteria (✅ All Met)

1. ✅ Task tool calls show: `⚙ Task(claude, "description preview")` with quoted description
2. ✅ Task results show: `✓ Completed` without long content preview
3. ✅ Tree branch appears when inside step context (already implemented)
4. ✅ Description arguments are quoted for clarity
5. ✅ Error results show: `✗ Failed (error message)`
6. ✅ Research tool also uses brief SubagentFormatter
7. ✅ Other tools (read_file, etc.) still show content previews

## Implementation Notes

**Key insight:** The tree branch display depends on **execution context**, not tool type:
- Inside step context: Tool calls/results show `└─` prefix (lines 236-237, 292-293 in renderer.py)
- Outside step context: Tool calls/results show flat display

**When Task appears inside a step:**
```
⏩ Analyze README structure
  └─ ⚙ Task(browser, "query preview")
  └─ ✓ Completed (duration_ms)
```

**When Task appears outside a step (direct agent invocation):**
```
⚙ Task(claude, "description preview")
✓ Completed (duration_ms)
```

**Step header format:**
- Uses `⏩ {description}` (no "Step:" prefix)
- Icon: Hollow circle `○` for in-progress step
- Parallel steps: `⏩ {description} (parallel)`

**Result formatting by category:**
- `subagent` category (task, research): SubagentFormatter → brief "✓ Completed"
- `file_ops` category: FileOpsFormatter → shows content summary
- `execution` category: ExecutionFormatter → shows command output
- Other categories: Specific formatters with appropriate detail

## Technical Notes

- Task tool args: `{"subagent_type": "claude", "description": "...", "prompt": "..."}`
- Arg keys priority: `subagent_type`, `description`, `prompt` (from metadata registry)
- Display shows first two args: subagent_type + quoted description preview
- Result extraction uses existing `extract_tool_brief()` logic

## References

- RFC-0020: CLI Stream Display Pipeline
- IG-256: Restored verbose display and tool tree refactor
- `/packages/soothe-sdk/src/soothe_sdk/tools/metadata.py`: Task tool metadata (line 217-225)
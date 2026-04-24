# IG-257: Tool Tree Display Refactor - Implementation Summary

## Status: Completed ✅

## Overview

Refactored tool and Task display to show as indented tree nodes (children) under step headers using Unicode tree branch characters.

## Changes Made

### 1. Tool Tree Display (Unicode Tree Branches)

**File: packages/soothe-cli/src/soothe_cli/cli/renderer.py**

- Added `_is_inside_step_context()` helper to check if tool is inside active step
- Modified `on_tool_call()` to add `"  └─ "` prefix when inside step
- Modified `on_tool_result()` to add `"  └─ "` prefix when inside step
- Uses Unicode U+2514 "└─" (Box Drawings Light Up and Right) for clean tree structure

**Result:**
```
○ Step description
  └─ ⚙ ToolName(args)
  └─ ✓ Result
  └─ Done [1 tools]
```

### 2. Step Result Tree Branch (Unicode)

**File: packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py**

- Updated `format_step_done()` to use Unicode "└─" instead of ASCII "|__"
- Applied to both success and error cases

### 3. Reasoning Display Polish

**Files: packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py and formatter.py**

- Removed Assessment display (IG-257)
- Show Plan reasoning without "Plan:" prefix (just emoji + text)
- Updated `format_plan_phase_reasoning()` to handle empty label case

**Result:**
```
● 💭 Simple file read operation to get README content  ← No "Plan:" prefix
```

### 4. Subagent Event Suppression

**File: packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py**

- Suppressed explicit subagent event processing (return empty list)
- Task tool events flow through naturally as regular tools
- Creates consistent tree structure for all tools including Task/subagent calls

## Tests

All 1279 unit tests passed ✅
Linting passed ✅
Formatting passed ✅

## Next Investigation

User asked: "what subagent events emit from daemon is unused and could be deleted for performance improvement"

Based on IG-256 suppression:
- CLI suppresses all soothe.capability.* and .subagent.* events
- TUI still processes soothe.capability.* events (textual_adapter.py line 277)
- Events defined in: subagents/claude/events.py, subagents/browser/events.py

**Potential deletions:**
- CLI-side processing of subagent events (already suppressed)
- But need to check TUI usage before deleting daemon emission

## Issues Remaining

User reported indentation issue on reasoning line:
```
● 🌀 [keep] Report completion...
  ● 💭 Successfully read...  ← Has 2-space indent (should be flat)
```

Tests show indent should be empty, but actual output shows indentation.
Need to investigate where extra indentation is being added.
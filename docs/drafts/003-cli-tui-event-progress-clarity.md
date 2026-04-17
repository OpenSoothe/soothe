# Design Draft: CLI/TUI Event Progress Clarity Improvements

**Date**: 2026-03-26
**Status**: Draft
**Scope**: UX improvements for headless CLI and TUI event rendering

---

## Problem Statement

Current CLI/TUI event progress output has critical usability issues:

### 1. Malformatted Text (Critical)
Text from AI responses appears without proper spacing:
```
[plan] Plan: /browser iran wars (1 steps)
I'llsearchforinformationaboutIranwarsusingthebrowsertool.
```

**Root Cause**: Text concatenation without space preservation during formatting.

### 2. Verbose/Overwhelming Output
Large blocks of unformatted text dump to terminal:
```
[tool] Result (search_web): 10 results in 7.6s for "Iran wars history conflicts"
Basedonthesearchresults,here'sanoverviewof**Iran'smajorwarsandconflicts**:##MajorConflictsInvolvingIran...
```

**Root Cause**:
- No truncation/summarization of long tool results
- AI response text not formatted for terminal display
- Missing newlines and structure

### 3. Poor Visual Hierarchy
All events use same `[tag]` format regardless of importance:
```
[thread] Thread created: xqrlpr212rs3
[thread] Thread started: xqrlpr212rs3 [context, memory, planner]
[context] Projected 0 entries (0 tokens)
[plan] Plan: /browser iran wars (1 steps)
[tool] Calling: search_web
```

**Root Cause**: Flat presentation without semantic grouping or emphasis.

### 4. Information Density Issues
- Raw `<search_data>` XML tags visible in output
- Tool result content not summarized effectively
- No distinction between user-facing vs. debug information

---

## Proposed Solution Architecture

### Design Principles

1. **Progressive Disclosure**: Show summary first, details on demand (or in debug mode)
2. **Semantic Formatting**: Use visual hierarchy to indicate importance
3. **Terminal-Optimized**: Respect terminal width and readability constraints
4. **Smart Truncation**: Summarize long content intelligently
5. **Consistent Spacing**: Ensure proper whitespace in all text output

### Component Improvements

#### A. Text Formatting Fixes (Critical)

**Issue**: Text concatenation without spaces

**Solution**: Add whitespace preservation in text processing
- Location: `ux/shared/message_processing.py` → `strip_internal_tags()`
- Add post-processing to ensure proper spacing
- Validate text rendering with spacing tests

**Priority**: P0 (Critical bug fix)

#### B. Tool Call Tree Structure (Core Improvement)

**Current**: Flat sequence of unrelated events
```
[tool] Calling: search_web
[tool] 10 results in 7.6s for "Iran wars history conflicts"
<search_data>...
[tool] Result (search_web): 10 results in 7.6s...
```

**Proposed**: Two-level tree structure for every tool call

**Default Pattern** (applies to 90% of tools):
```
⚙ WebSearch("Iran wars history conflicts")
  └ ✓ 10 results in 7.6s
```

**Structure**:
- **Level 1 (Parent)**: Tool start event with name and key argument(s)
- **Level 2 (Child)**: Tool complete event with summary result
- **Indentation**: Use `  └ ` tree connector for child
- **Icons**: ⚙ (in progress) → ✓ (success) or ✗ (error)

**Start Event Format**:
```
⚙ ToolName(key_argument_value)
```
- Extract most relevant argument (path, query, url, command)
- Use `format_tool_call_args()` logic (already exists)
- Show tool display name (CamelCase)
- Yellow color while running, green when complete

**Complete Event Format**:
```
  └ ✓ summary_result
```
- One-line summary of result
- Extract using `extract_tool_brief()` (already exists)
- Truncate to 60 chars max
- Show duration if available

**Priority**: P0 (Core UX pattern)

**Implementation**:
1. Track tool call state in renderer (tool_call_id → parent_line)
2. Render start event immediately
3. When complete event arrives, render as indented child
4. Use terminal escape codes to move cursor up and update parent icon (if supported)
5. Fallback: Keep both lines separate if cursor movement not supported

#### C. Special Tool Behaviors

Some tools need additional progress events or different formatting:

**Browser Subagent** (multi-step):
```
⚙ Browser("iran wars")
  ├ Step 1: navigate @ wikipedia.org
  ├ Step 2: extract_content
  └ ✓ Completed in 45.2s
```

**Research Tool** (multi-phase):
```
⚙ Research("quantum computing")
  ├ Generated 3 queries
  ├ Gathering from arxiv.org
  └ ✓ Synthesized 15 sources (2.3k chars)
```

**File Operations** (simple):
```
⚙ ReadFile("config.yml")
  └ ✓ 245 lines (8.2kb)
```

**Execution Tools** (show output preview):
```
⚙ RunCommand("npm test")
  └ ✓ Passed 42/42 tests in 3.2s
```

**Implementation**:
- Create `ToolBehavior` registry
- Map tool names to custom rendering functions
- Default behavior for unregistered tools
- Allow tools to emit intermediate progress events (rendered as intermediate tree nodes)

**Priority**: P1 (Enhancement for complex tools)

#### D. Plan Display Improvements

**Current**: Verbose plan output
```
[plan] Plan: /browser iran wars (1 steps)
I'llsearchforinformationaboutIranwarsusingthebrowsertool.
```

**Proposed**: Compact tree structure
```
● Plan: Search for Iran wars information (1 step)
  └ ⚙ Step 1: Browse web for "Iran wars"
```

**Multi-step Plan**:
```
● Plan: Analyze codebase (3 steps)
  ├ ✓ Step 1: List project structure
  ├ ⚙ Step 2: Read key files
  └ ⏳ Step 3: Generate summary
```

**Implementation**:
- Use tree rendering from tool calls
- Add progress indicators per step
- Show only in verbose mode or TUI
- In CLI normal mode: single line "Executing plan: ..."

**Priority**: P1 (High impact)

#### E. Protocol Events (Verbose Mode Only)

**Current**: All protocol events shown
```
[thread] Thread created: xqrlpr212rs3
[thread] Thread started: xqrlpr212rs3 [context, memory, planner]
[context] Projected 0 entries (0 tokens)
[memory] Stored memory from thread xqrlpr212rs3
```

**Proposed**: Hide in normal mode, show in debug mode
- Thread lifecycle: debug only
- Context projection: debug only
- Memory storage: debug only
- Checkpoint: debug only

**Normal Mode Focus**:
- User queries
- Tool calls and results
- Plan progress
- Errors

**Priority**: P2 (Verbosity reduction)

#### F. AI Text Response Handling

**Current**: Dump entire AI response text
```
[tool] Result (search_web): 10 results...
Basedonthesearchresults,here'sanoverviewof**Iran'smajorwars...
```

**Proposed**:
- **CLI Normal Mode**: Don't show AI text (use tool results only)
- **CLI Verbose Mode**: Show formatted AI text (strip tags, add line breaks)
- **TUI Mode**: Show in dedicated panel, format with markdown

**Implementation**:
- Keep AI text in `full_response` state
- Only render in verbose mode
- Use `strip_internal_tags()` + proper formatting
- Add markdown-to-terminal conversion (optional)

**Priority**: P2 (Polish)

---

## Implementation Approach

### Phase 1: Critical Bug Fixes (P0)
**Scope**: Fix immediate text formatting issues

**Tasks**:
1. Fix text spacing in `strip_internal_tags()`
   - Add whitespace normalization post-processing
   - Ensure spaces between words in AI text
2. Add unit tests for spacing edge cases
3. Verify with manual test run

**Files**:
- `src/soothe/ux/shared/message_processing.py`
- `tests/ux/test_message_processing.py` (new)

**Effort**: 2-3 hours
**Impact**: Critical bug fix

### Phase 2: Tool Call Tree Structure (P0)
**Scope**: Implement two-level tree rendering for tool calls

**Tasks**:
1. Design `ToolCallTracker` class
   - Map tool_call_id → parent event data
   - Track start/complete pairs
2. Update `CliEventRenderer`
   - Render start event immediately
   - Store parent reference
   - Render complete as indented child
   - Add tree connector (`└`)
3. Implement cursor movement (optional)
   - Update parent icon from ⚙ → ✓
   - Fallback to two-line display
4. Add unit tests for tree rendering
5. Manual testing with various tools

**Files**:
- `src/soothe/ux/cli/rendering/cli_event_renderer.py`
- `src/soothe/ux/cli/rendering/tool_call_tracker.py` (new)
- `tests/ux/cli/test_tree_rendering.py` (new)

**Effort**: 4-5 hours
**Impact**: Core UX improvement

### Phase 3: Special Tool Behaviors (P1)
**Scope**: Custom rendering for complex tools

**Tasks**:
1. Create `ToolBehaviorRegistry`
   - Map tool names to render functions
   - Default behavior for unknown tools
2. Implement special cases:
   - Browser: show steps as intermediate nodes
   - Research: show phases
   - File operations: show size/line count
3. Update tool implementations to emit progress events
4. Add tests for each special tool
5. Documentation for tool developers

**Files**:
- `src/soothe/ux/cli/rendering/tool_behaviors.py` (new)
- `src/soothe/subagents/browser/implementation.py`
- `src/soothe/tools/research/implementation.py`
- `docs/tool_development.md` (update)

**Effort**: 3-4 hours
**Impact**: Enhanced UX for complex tools

### Phase 4: Plan & Protocol Improvements (P1)
**Scope**: Clean up plan display and protocol events

**Tasks**:
1. Update plan rendering with tree structure
2. Move protocol events to debug mode
3. Update verbosity filters
4. Add tests
5. Update user documentation

**Files**:
- `src/soothe/ux/cli/rendering/cli_event_renderer.py`
- `src/soothe/ux/shared/progress_verbosity.py`
- `docs/user_guide.md`

**Effort**: 2-3 hours
**Impact**: Cleaner output

---

## Success Criteria

1. **No malformatted text**: All output has proper spacing
2. **Two-level tool tree**: Every tool shows start + complete as parent/child
3. **Readable summaries**: Tool results fit in 1 line, truncated to 60 chars
4. **Clear visual hierarchy**: Icons (⚙ ✓ ✗) indicate status at a glance
5. **Terminal-optimized**: Output respects 80-char width
6. **Debug mode preserves detail**: All information available when needed
7. **Special tools supported**: Complex tools can add intermediate progress nodes

---

## Example Output Comparison

### Before (Current)
```
[thread] Thread created: xqrlpr212rs3
[thread] Thread started: xqrlpr212rs3 [context, memory, planner]
[context] Projected 0 entries (0 tokens)
[plan] Plan: /browser iran wars (1 steps)
I'llsearchforinformationaboutIranwarsusingthebrowsertool.
[tool] Calling: search_web
[tool] 10 results in 7.6s for "Iran wars history conflicts"

<search_data>
1. Iran war continues, Lafayette
[tool] Result (search_web): 10 results in 7.6s for "Iran wars history conflicts"
Basedonthesearchresults,here'sanoverviewof**Iran'smajorwarsandconflicts**:##MajorConflictsInvolvingIran...
[context] Ingested from agent: I'll search for information about Iran wars using the browse
[memory] Stored memory from thread xqrlpr212rs3
[plan] Step step_1 ✓ (0ms)
[plan] Plan accepted: 1/1 steps completed successfully
[checkpoint] Checkpoint saved: 1 steps, 0 goals
[thread] Thread saved: xqrlpr212rs3
[thread] Thread ended: xqrlpr212rs3
```

### After (Proposed - Normal Mode)
```
● Plan: Search for Iran wars information (1 step)
  └ ⚙ Step 1: Browse web for "Iran wars"

⚙ WebSearch("Iran wars history conflicts")
  └ ✓ 10 results in 7.6s

  [AI response formatted with proper spacing]
  Based on the search results, here's an overview of Iran's major wars:

  • Iran-Iraq War (1980-1988) - The bloodiest conflict...
  • Current tensions with Israel (2024-2026)
  • Regional proxy conflicts

● Plan completed: 1/1 steps ✓
```

### After (Proposed - Debug Mode)
```
[thread] Thread created: xqrlpr212rs3
[thread] Thread started: xqrlpr212rs3 [context, memory, planner]
[context] Projected 0 entries (0 tokens)

● Plan: Search for Iran wars information (1 step)
  └ ⚙ Step 1: Browse web for "Iran wars"

⚙ WebSearch("Iran wars history conflicts")
  └ ✓ 10 results in 7.6s

[context] Ingested from agent: I'll search for information...
[memory] Stored memory from thread xqrlpr212rs3
[plan] Step step_1 ✓ (0ms)
[checkpoint] Checkpoint saved: 1 steps, 0 goals
[thread] Thread saved: xqrlpr212rs3
[thread] Thread ended: xqrlpr212rs3
```

---

## Special Tool Examples

### Browser Subagent (Multi-step)
```
⚙ Browser("iran wars")
  ├ Step 1: navigate @ en.wikipedia.org
  ├ Step 2: extract_content
  └ ✓ Completed in 45.2s (3 pages)
```

### Research Tool (Multi-phase)
```
⚙ Research("quantum computing advances 2024")
  ├ Generated 3 queries: "quantum", "computing", "2024"
  ├ Gathering from arxiv.org (12 results)
  └ ✓ Synthesized 15 sources (2.3k chars)
```

### File Operations
```
⚙ ReadFile("config.yml")
  └ ✓ 245 lines (8.2kb)

⚙ WriteFile("output.json")
  └ ✓ Written 1.2kb
```

### Execution
```
⚙ RunCommand("npm test")
  └ ✓ Passed 42/42 tests in 3.2s

⚙ RunCommand("make build")
  └ ✗ Failed: compilation error at line 42
```

### Web Search (Default)
```
⚙ WebSearch("python async best practices")
  └ ✓ 15 results in 2.3s

⚙ CrawlWeb("https://docs.python.org/3/library/asyncio.html")
  └ ✓ 45.2kb in 1.8s
```

---

## Technical Implementation Details

### Tool Call Tracking System

**Class**: `ToolCallTracker`

**Purpose**: Match tool start events with their completion events

**Data Structure**:
```python
@dataclass
class ToolCallState:
    tool_name: str
    tool_call_id: str
    start_time: float
    parent_line_index: int  # Terminal line where parent was rendered
    args_summary: str
```

**Methods**:
- `register_start(tool_name, tool_call_id, args_summary) -> int`
  - Returns line index where parent was rendered
- `register_complete(tool_call_id, result_summary) -> ToolCallState`
  - Returns state for rendering child
- `get_pending() -> list[ToolCallState]`
  - For cleanup/debug

**Rendering Logic**:
1. When tool call starts:
   - Render `⚙ ToolName(args)`
   - Store state in tracker
   - Return line index
2. When tool call completes:
   - Retrieve state from tracker
   - Render `  └ ✓ result_summary` on next line
   - (Optional) Use cursor movement to update parent icon

### Event Flow Example

**Events Received**:
1. `soothe.tool.websearch.search_started` → render parent
2. `soothe.tool.websearch.search_completed` → render child

**Terminal Output**:
```
⚙ WebSearch("Iran wars history conflicts")
  └ ✓ 10 results in 7.6s
```

### Cursor Movement Approach (Optional Enhancement)

**Goal**: Update parent icon in-place when child completes

**Implementation**:
```python
def update_parent_icon(line_index: int, new_icon: str):
    # Move cursor up to parent line
    sys.stderr.write(f"\033[{line_index}A")
    # Move to start of line
    sys.stderr.write("\r")
    # Clear line
    sys.stderr.write("\033[K")
    # Rewrite with new icon
    sys.stderr.write(f"{new_icon} {tool_name}({args})\n")
    # Move cursor back down
    sys.stderr.write(f"\033[{line_index}B")
```

**Fallback**: If terminal doesn't support ANSI codes, render child on new line

### Tool Behavior Registry

**Purpose**: Allow custom rendering for special tools

**Structure**:
```python
class ToolBehavior(Protocol):
    def render_start(self, event: dict) -> str:
        """Custom start event rendering"""
        ...

    def render_progress(self, event: dict, state: ToolCallState) -> str | None:
        """Optional intermediate progress nodes"""
        ...

    def render_complete(self, event: dict, state: ToolCallState) -> str:
        """Custom complete event rendering"""
        ...
```

**Registry**:
```python
TOOL_BEHAVIORS: dict[str, ToolBehavior] = {
    "browser": BrowserBehavior(),
    "research": ResearchBehavior(),
    # Default for unregistered tools
    "default": DefaultBehavior(),
}
```

**Usage**:
```python
behavior = TOOL_BEHAVIORS.get(tool_name, TOOL_BEHAVIORS["default"])
start_line = behavior.render_start(event)
```

---

## Testing Strategy

### Unit Tests

**Text Formatting**:
- Whitespace preservation in `strip_internal_tags()`
- Space normalization between words
- Internal tag removal

**Tool Call Tracker**:
- Start/complete matching
- Line index tracking
- Pending state cleanup

**Tree Rendering**:
- Parent/child indentation
- Icon updates
- Truncation at 60 chars

**Tool Behaviors**:
- Custom rendering for each special tool
- Default behavior fallback

### Integration Tests

**CLI Rendering**:
- Run test commands with various tools
- Compare output to expected tree structure
- Verify ANSI codes (or fallback)

**Verbosity Levels**:
- Normal mode: only tool trees + plan
- Debug mode: all protocol events
- Verify no information loss

### Manual Testing Scenarios

**Basic Tools**:
- Web search with results
- File read/write
- Command execution (success/failure)

**Complex Tools**:
- Browser subagent (multi-step)
- Research tool (multi-phase)

**Edge Cases**:
- Tool timeout
- Tool error
- Very long arguments (truncation)
- Very long results (truncation)

**Terminal Compatibility**:
- Modern terminals (iTerm2, Alacritty)
- Basic terminals (linux console)
- CI/CD environments (no ANSI codes)

---

## Open Questions

1. **Q**: Should we preserve markdown formatting in AI text?
   **A**: Convert to terminal-friendly format (e.g., `**bold**` → ANSI bold)

2. **Q**: How to handle very long tool results (e.g., file reads)?
   **A**: Truncate to configurable max lines (default: 1 line in CLI, expandable in TUI)

3. **Q**: Should protocol events (context/memory) be shown in normal mode?
   **A**: No, move to debug mode. Focus on user-visible progress.

---

## Next Steps

1. **Validate design** with stakeholder
2. **Generate RFC** from this draft
3. **Create implementation guide**
4. **Implement in phases**
5. **Review and test**

---

## References

- Current implementation: `src/soothe/ux/cli/rendering/cli_event_renderer.py`
- TUI renderer: `src/soothe/ux/tui/renderers.py`
- Message processing: `src/soothe/ux/shared/message_processing.py`
- Event catalog: `src/soothe/core/event_catalog.py`
- RFC-400: Event System Design
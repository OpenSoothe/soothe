# RFC-0020: Event Display Architecture

**RFC**: 0020
**Title**: Event Display Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-26
**Updated**: 2026-03-27
**Dependencies**: RFC-0001, RFC-0002, RFC-0013, RFC-0015, RFC-0019

## Abstract

This RFC establishes the architectural foundation for displaying agent activity events across CLI and TUI interfaces using a **registry-driven, two-level tree display system**. Events register their display metadata (templates, verbosity) at definition time, enabling automatic integration without renderer modifications.

## Design Principles

### Principle 1: Registry-Driven Display Metadata

**Rule**: All display-relevant event metadata must be registered at event definition time.

**What This Means**:
- Event types register `summary_template` strings with field interpolation
- Event types declare `verbosity` categories for visibility filtering
- Renderers query the registry for templates, never hardcode strings

**Example**:
```
Event: BrowserStepEvent
  - type: "soothe.subagent.browser.step"
  - summary_template: "Step {step}"
  - verbosity: "subagent_progress"
```

### Principle 2: Two-Level Tree Structure

**Rule**: All activity events display as a two-level tree: summary + details.

**Display Pattern**:
```
Level 1 (Summary):  ● EventSummary
Level 2 (Details):    └ Additional context or results
```

**When Details Appear**:
- Tool results show completion status
- Subagent steps show progress events
- Text events show content preview
- Result events show metrics

### Principle 3: Progressive Disclosure via Verbosity

**Verbosity Categories**:
- `assistant_text`: AI responses (normal mode)
- `protocol`: Core agent activity (normal mode)
- `subagent_progress`: Subagent steps (normal mode)
- `tool_activity`: Granular tool execution (verbose mode)
- `debug`: Internal details (debug mode)

**Display Rules**:
- Normal mode: `assistant_text`, `protocol`, `subagent_progress`, `error`
- Verbose mode: Adds `tool_activity`
- Debug mode: All categories

### Principle 4: Template Interpolation

**Rule**: Event summaries use template strings with field interpolation.

**Examples**:
- `"Step {step}"` → "Step 1"
- `"Tool: {tool}"` → "Tool: read_file"
- `"Done (${cost_usd}, {duration_ms}ms)"` → "Done ($0.0023, 1234ms)"

### Principle 5: Visual Consistency via Display Helpers

**Required Helpers**:
- `make_dot_line(color, summary, details)` → Two-level tree output
- `make_tool_block(name, args, result, status)` → Tool call display
- `format_event_summary(event_type, data, registry)` → Registry-driven summary

## Event Display Patterns

### Pattern: Tool Activity

**Registration**:
- Type: `soothe.tool.<tool_name>.call_started`
- Template: `<tool_name>({args_summary})`
- Verbosity: `tool_activity`

**Display**:
```
⚙ ToolName("key_argument")
  └ ✓ Result summary (duration)
```

**Note**: Tool activity filtered at normal verbosity. Only subagent tools with `subagent_progress` appear in normal mode.

#### Tool Output Formatting (RFC-0020 Enhancement)

**Problem**: Previous implementation showed verbose, meaningless tool result output with simple truncation, making it difficult to quickly scan tool execution results.

**Solution**: Implement semantic, tool-specific result summarization using a formatter-based pipeline that extracts meaningful metrics instead of raw content truncation.

**Formatter Pipeline**:
```
Tool Result → Tool Classifier → Tool-Specific Formatter → ToolBrief → RFC-0020 Display
```

**Key Components**:

1. **ToolBrief**: Structured summary dataclass
   - `icon`: Status indicator (✓, ✗, ⚠)
   - `summary`: One-line summary (max 50 chars)
   - `detail`: Optional detail line (max 80 chars)
   - `metrics`: Optional metadata dict (size, duration, count, etc.)

2. **Tool Classifier**: Routes tool results to appropriate formatters
   - Detects tool category by name (file_ops, execution, media, goals, web)
   - Detects result type (ToolOutput, dict, str)
   - Priority: ToolOutput > category-specific > fallback

3. **Tool-Specific Formatters**: Semantic summarization by category
   - FileOpsFormatter: Size, line count, item count
   - ExecutionFormatter: Done/Failed status, PID, error messages
   - MediaFormatter: Duration, resolution, format
   - GoalFormatter: Goal ID, count, status
   - StructuredFormatter: ToolOutput handling with error classification
   - FallbackFormatter: Simple truncation for unknown tools

**Tool-Specific Summary Patterns**:

| Category | Tool | Success Pattern | Example Output |
|----------|------|----------------|----------------|
| FileOps | read_file | "Read {size} ({lines} lines)" | "✓ Read 2.3 KB (42 lines)" |
| FileOps | write_file | "Wrote {size}" | "✓ Wrote 1.5 KB" |
| FileOps | list_files | "Found {count} items" | "✓ Found 15 items" |
| FileOps | glob | "Found {count} files" | "✓ Found 42 files" |
| Execution | run_command | "Done" or "Failed: {reason}" | "✓ Done" or "✗ Failed: timeout" |
| Execution | run_background | "Started PID {pid}" | "✓ Started PID 12345" |
| Media | transcribe_audio | "Transcribed {duration}s" | "✓ Transcribed 45.2s (en)" |
| Media | get_video_info | "Video: {duration}s" | "✓ Video: 120s (1920x1080)" |
| Goals | create_goal | "Created goal {id}" | "✓ Created goal g1" |
| Goals | list_goals | "Found {count} goals" | "✓ Found 3 goals" |

**Edge Cases**:
- Empty results: "✓ Found 0 items", "✓ Read 0 B (empty file)"
- Large output: Truncate to 50/80 chars with ellipsis
- Errors: "✗ Failed: {error_message}"
- Unknown tools: Fallback to simple truncation (backward compatible)
- Formatter errors: Graceful fallback with logging

**Implementation Requirements**:
- Replace `extract_tool_brief()` with semantic formatting
- Handle dict and ToolOutput result types (not just str)
- Error handling with fallback to prevent crashes
- Maintain RFC-0020 compliance (50/80 char limits)
- Backward compatible with existing tools

**Integration Points**:
- `src/soothe/ux/core/message_processing.py::extract_tool_brief()`
- `src/soothe/ux/core/tool_output_formatter.py` (NEW)
- `src/soothe/ux/core/tool_formatters/` (NEW package)

**Success Criteria**:
- Semantic summaries show meaningful metrics instead of raw truncation
- Each tool type has customized, scannable summary format
- Unknown tools continue to work with fallback formatter
- Formatter errors don't crash the display system
- All summaries respect 50/80 character limits

### Pattern: Subagent Activity

**Registration**:
- Dispatch event: `soothe.subagent.<name>.dispatched`
- Step events: `soothe.subagent.<name>.step`
- Completion event: `soothe.subagent.<name>.completed`

**Display**:
```
⚙ AgentName("task dispatched to agent")
  └ ✓ Step 1: Navigate to page | https://example.com
  └ ✓ Step 2: Extract key words | hello world
  └ ✓ Completed in 45.2s
```

**Key Differences from Tools**:
- **Parent line** shows agent dispatch with task description
- **Multiple child events** can appear as steps complete
- **Each step** gets its own line with ✓ indicator
- **Final line** shows completion summary

**Verbosity**: `subagent_progress` (visible in normal mode)

### Pattern: Protocol Events

**Registration**:
- Type: `soothe.protocol.<component>.<action>`
- Template: Concise status message
- Verbosity: `protocol`

**Display**:
```
● Thread xqrlpr212rs3 created
● Plan: Search for information (3 steps)
  └ ⚙ Step 1: Browse web
  └ ✓ Step 1 completed
```

### Pattern: Error Events

**Registration**:
- Type: `soothe.error.<component>.<type>`
- Verbosity: `error` (always visible)

**Display**:
```
✗ Tool execution failed
  └ compilation error at line 42
```

## Implementation Requirements

### Event Registration

**Required Metadata**:
1. **Event Type String**: `soothe.<domain>.<component>.<action>` format
2. **Summary Template**: Format string with field interpolation (< 50 characters)
3. **Verbosity Category**: One of the standard categories

**Registration Pattern**:
```
1. Define Pydantic model with 'type' field default
2. Call register_event() with event class, verbosity, summary_template
3. Event automatically available to all renderers
```

### Renderer Implementation

**Summary Building**:
```
1. Query REGISTRY.get_meta(event_type)
2. If meta.summary_template exists: format with event data
3. Handle formatting errors gracefully
```

**Detail Extraction for Subagents**:
```
Subagent dispatch events:
  - Track agent start
  - Accumulate step events as children
  - Display as multi-line tree with one line per step

Subagent step events:
  - Format as: "Step N: action | details"
  - Add ✓ icon for completed steps
```

**Visual Consistency**:
- Use `make_dot_line()` for two-level trees
- Colors: blue (assistant), green (success), red (error), yellow (progress), magenta (subagent)
- Icons: ● (in progress), ✓ (success), ✗ (error), ⚙ (tool/agent)

## Verbosity Classification

**Category Definitions**:
- **assistant_text**: AI responses (normal mode)
- **protocol**: Core lifecycle events (normal mode)
- **subagent_progress**: Subagent activity (normal mode)
- **tool_activity**: Granular tool execution (verbose mode)
- **debug**: Internal details (debug mode)

**Domain Defaults** (when verbosity not set):
- **lifecycle** → `protocol`
- **protocol** → `protocol`
- **subagent** → `subagent_progress`
- **tool** → `tool_activity`
- **output** → `assistant_text`
- **error** → `error` (always visible)

## Terminal Formatting

**Width Constraints**:
- Default terminal width: 80 characters
- Maximum summary: 50 characters
- Maximum detail: 80 characters
- Indentation: 2 spaces + connector

**Text Preservation**:
- Normalize whitespace to single spaces
- Truncate at word boundaries when possible
- Add ellipsis (...) for truncated text

**Error Handling**:
- Template errors → Log and skip (never crash)
- Missing metadata → Skip display
- Malformed data → Log warning and skip
- Width detection failure → Fall back to 80 chars

## Extensibility

**Adding New Events**:
```
1. Define event model
2. Register with template and verbosity
3. Emit event
→ Automatically displays without renderer changes
```

**Adding New Categories**:
```
1. Add to ProgressCategory type
2. Update should_show() logic
3. Use in register_event() calls
→ Renderers need no changes
```

## Success Criteria

1. **Registry-Driven**: All summaries use templates (no hardcoded strings)
2. **Consistent Display**: All events follow two-level tree pattern
3. **Extensible**: New events display with zero renderer changes
4. **Progressive Disclosure**: Verbosity filtering works correctly
5. **Resilient**: Errors don't crash display system
6. **Terminal-Optimized**: Respects width constraints

## Dependencies

- **RFC-0001**: System Conceptual Design
- **RFC-0002**: Core Modules Architecture
- **RFC-0013**: Unified Daemon Communication Protocol
- **RFC-0015**: Event System Design
- **RFC-0019**: Unified Event Processing

## Related Documents

- [RFC-0013](./RFC-0013-daemon-communication-protocol.md) - Daemon protocol
- [RFC-0015](./RFC-0015-progress-event-protocol.md) - Event system
- [RFC-0019](./RFC-0019-unified-event-processing.md) - Event processing
- [IG-066](../impl/IG-066-subagent-event-display-fix.md) - Implementation example

---

*This RFC establishes the registry-driven display architecture for consistent, extensible event display.*
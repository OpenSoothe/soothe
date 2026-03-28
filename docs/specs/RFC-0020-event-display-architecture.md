# RFC-0020: Event Display Architecture

**RFC**: 0020
**Title**: Event Display Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-26
**Updated**: 2026-03-28
**Dependencies**: RFC-0001, RFC-0002, RFC-0003, RFC-0013, RFC-0015, RFC-0019

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

### Principle 3: Shared Presentation Policy Across Headless and TUI

**Rule**: Verbosity semantics must be defined once and shared across both headless CLI and TUI surfaces.

**What This Means**:
- A shared presentation policy decides which events are visible at each verbosity level.
- Headless and TUI use the same semantic visibility rules, but render them differently.
- Visibility decisions are not duplicated separately in headless and TUI renderers.

**Surface Model**:
- **Shared presentation policy**: classifies events, cleans text, decides visibility, emits presentation items
- **Headless renderer**: prints presentation items as separated text blocks
- **TUI renderer**: maps presentation items into conversation/activity/plan widgets

**Verbosity Levels**:
- `quiet`: automation-friendly extracted answer or compact fallback
- `normal`: default user-facing mode with plan updates, milestones, concise result
- `detailed`: richer progress and tool summaries
- `debug`: full internal visibility

### Principle 4: Template Interpolation

**Rule**: Event summaries use template strings with field interpolation.

**Examples**:
- `"Step {step}"` → "Step 1"
- `"Tool: {tool}"` → "Tool: read_file"
- `"Done (${cost_usd}, {duration_ms}ms)"` → "Done ($0.0023, 1234ms)"

### Principle 5: Surface-Aware Rendering with Shared Semantics

**Rule**: Presentation semantics are shared, but final formatting is surface-aware.

**Required Helpers**:
- `classify_display_event(namespace, mode, data)` → semantic classification
- `build_presentation_item(event, registry, verbosity)` → shared presentation item creation
- `clean_response_text(text)` → strip brand and embellishment
- `extract_quiet_answer(text)` → answer extraction with fallback confidence
- `render_headless_block(item)` → headless text block output
- `render_tui_item(item)` → TUI widget mapping

**Formatting Rule**:
- Headless output prepends one empty line before every displayed block.
- TUI preserves the same separation intent via layout spacing rather than literal blank-line messages.

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

### Shared semantic event classes

The display system first classifies raw stream events into semantic classes:
- `assistant_response`
- `plan_update`
- `milestone`
- `tool_summary_candidate`
- `error`
- `lifecycle_internal`
- `protocol_internal`
- `debug_internal`

The classifier should be conservative: if uncertain, classify as internal to avoid leaking low-value internals into `normal`.

### Verbosity behavior

#### `quiet`
Show:
- extracted final answer when confidence is high
- compact structured fallback when extraction is uncertain
- concise actionable errors

Hide:
- lifecycle events
- protocol events
- plan updates
- milestones
- raw tool activity

#### `normal` (default)
Show:
- plan updates
- brief progress milestones
- concise tool summaries when they add clarity
- cleaned final response
- user-facing errors

Hide:
- lifecycle events
- protocol counters
- thread IDs
- daemon state and PID details
- plan reasoning
- raw step states such as `[pending]`
- raw tool invocation spam

#### `detailed`
Show:
- plan updates
- milestones
- tool summaries
- cleaned final response
- richer operational detail than `normal`

#### `debug`
Show all categories, including internal events.

## Presentation and Formatting Rules

### Shared response cleaning

Before final assistant text is shown in `quiet`, `normal`, and `detailed`, the system must:
- remove greeting and brand intro text
- remove creator attribution in response body
- remove decorative filler such as `Let me know if...`
- remove non-essential embellishment
- preserve factual correctness and actionable guidance

### Plan update rendering

Plan updates must be rewritten into user-facing summaries.

Allowed examples:
- `Plan: Search arxiv for recent quantum computing papers`
- `Plan: Analyze codebase structure`

Not allowed in `normal`:
- reasoning paragraphs
- raw plan tree output
- dependency markers
- status markers like `[pending]`

### Milestone rendering

Milestones must be brief and outcome-oriented.

Examples:
- `Done: found 10 papers`
- `Done: analyzed 15 modules`
- `Done: generated report`

### Headless formatting

**Separator Rule**:
Every displayed headless output block must begin with exactly one empty line.

Examples:
```text

Plan: Search arxiv for recent quantum computing papers

Done: found 10 papers

I found 10 recent papers...
```

### TUI formatting

TUI must preserve the same semantic separation intent using widget spacing, margins, or grouped rows rather than literal blank-line messages.

### Width Constraints
- Default terminal width: 80 characters
- Maximum summary: 50 characters
- Maximum detail: 80 characters
- Indentation: 2 spaces + connector

### Text Preservation
- Normalize whitespace to single spaces
- Truncate at word boundaries when possible
- Add ellipsis (...) for truncated text

### Error Handling
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

1. **Registry-Driven**: All summaries use templates or shared presentation transforms rather than ad hoc renderer strings
2. **Cross-Surface Consistency**: Headless and TUI share the same verbosity semantics
3. **Normal-Mode Cleanliness**: `normal` hides lifecycle/protocol internals while showing plan updates and milestones
4. **Quiet-Mode Usefulness**: `quiet` extracts answers when confidence is high and falls back safely otherwise
5. **Extensible**: New events display with zero or minimal renderer changes
6. **Resilient**: Errors don't crash display system
7. **Readable Formatting**: Headless uses blank-line block separation; TUI preserves equivalent visual separation

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
# RFC-0020: Event Display Architecture

**RFC**: 0020
**Title**: Event Display Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-26
**Updated**: 2026-03-30
**Dependencies**: RFC-0001, RFC-0002, RFC-0003, RFC-0013, RFC-0015, RFC-0019, RFC-0024

**Note**: Rendering architecture is defined by RFC-0019 (`RendererProtocol` callbacks). This RFC defines the display patterns, verbosity behavior, and formatting rules that renderers follow.

## Abstract

This RFC establishes the architectural foundation for displaying agent activity events across CLI and TUI interfaces using a **registry-driven, three-level tree display system**. Events register their display metadata (templates, verbosity) at definition time, enabling automatic integration without renderer modifications.

**Maximum Three Levels**: The display hierarchy is strictly limited to 3 levels (goal → step → result) to maintain user experience and terminal readability.

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
  - verbosity: VerbosityTier.NORMAL  # RFC-0024
```

### Principle 2: Three-Level Tree Structure

**Rule**: All activity events display as a three-level tree: summary → step → result.

**Display Pattern**:
```
Level 1 (Summary):  ● EventSummary
Level 2 (Step):       └ Step description
Level 3 (Result):        └ ✓ Result metrics
```

**Maximum Three Levels**: Deeper nesting degrades user experience and terminal readability. The hierarchy is strictly limited to 3 levels.

**Level Definitions**:

| Level | Name | Content | Icon |
|-------|------|---------|------|
| 1 | Summary | Goal or phase description | `●` |
| 2 | Step | Individual action description | `└` |
| 3 | Result | Outcome, metrics, status | `└ ✓/✗` |

**Example Display**:
```
● Listing all README.md files
  └ Find files using glob
     └ ✓ Found 42 files in 1.2s
  └ Count and summarize
     └ ✓ 42 total, 8 directories
● Done: listed all README.md files
```

**What Gets Hidden**: Internal details not shown to end users:
- Iteration count (Iteration 1/3)
- Step IDs (step_0, s1)
- DAG dependency details
- Planning decisions
- Judge confidence scores

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

### Principle 5: Surface-Aware Rendering via RendererProtocol

**Rule**: Presentation semantics are shared, but final formatting is surface-aware.

**Architecture** (per RFC-0019):
- `EventProcessor` handles unified event routing, state management, and verbosity filtering
- `RendererProtocol` callbacks define the rendering interface
- `CliRenderer` and `TuiRenderer` implement mode-specific display

**Shared Semantics**:
- `classify_event_to_tier(event_type, namespace)` → `VerbosityTier` (RFC-0024)
- `build_event_summary(event_type, data)` → formatted string from registry template
- `DisplayPolicy.filter_content(text)` → strip internal tags and embellishment
- `DisplayPolicy.extract_quiet_answer(text)` → answer extraction with fallback
- `should_show(tier, verbosity)` → visibility check via integer comparison

**RendererProtocol Callbacks**:
- `on_assistant_text()` → streaming text output
- `on_tool_call()` / `on_tool_result()` → tool execution display
- `on_progress_event()` → custom event handling
- `on_plan_created/step_started/step_completed()` → plan progress

**Formatting Rule**:
- Headless output prepends one empty line before every displayed block.
- TUI preserves the same separation intent via layout spacing rather than literal blank-line messages.

## Event Display Patterns

### Pattern: Tool Activity

**Implementation**: Tool display is handled by `CliRenderer.on_tool_call`/`on_tool_result` via `EventProcessor` processing LangChain `tool_calls` from `AIMessage` and `ToolMessage`. This is NOT event-based display.

**Display**:
```
⚙ ToolName("key_argument")
  └ ✓ Result summary (duration)
```

**Verbosity**: Tool calls are visible at `VerbosityTier.NORMAL` (shown at normal verbosity and above).

**Tool Events**: Custom tool events (e.g., `soothe.tool.file_ops.read`) are `VerbosityTier.DETAILED` for internal progress tracking. They are NOT used for CLI display.

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

**Verbosity**: `VerbosityTier.NORMAL` (visible in normal mode)

### Pattern: Agentic Loop Progress

**Registration**:
- Loop started: `soothe.agentic.loop.started`
- Step started: `soothe.agentic.step.started`
- Step completed: `soothe.agentic.step.completed`
- Loop completed: `soothe.agentic.loop.completed`

**Display**:
```
● Listing all README.md files
  └ Find files using glob
     └ ✓ Found 42 files in 1.2s
  └ Count and summarize
     └ ✓ 42 total, 8 directories
● Done: listed all README.md files
```

**Key Principles**:
- **Goal-level** events appear at Level 1
- **Step** descriptions appear at Level 2
- **Result** metrics appear at Level 3
- **Iteration boundaries** are hidden from users (internal detail)

**Events**:

| Event | Level | VerbosityTier | Template |
|-------|-------|---------------|----------|
| `AgenticLoopStartedEvent` | 1 | `NORMAL` | `{goal}` |
| `AgenticStepStartedEvent` | 2 | `DETAILED` | `{description}` |
| `AgenticStepCompletedEvent` | 3 | `NORMAL` | `{summary} ({duration_ms}ms)` |
| `AgenticLoopCompletedEvent` | 1 | `QUIET` | `Done: {evidence_summary}` |

**Verbosity Behavior**:

| Event | quiet | normal | detailed |
|-------|-------|--------|----------|
| Loop started | ✗ | ✓ | ✓ |
| Step started | ✗ | ✗ | ✓ |
| Step completed | ✗ | ✓ | ✓ |
| Loop completed | ✓ | ✓ | ✓ |

**Hidden Internal Details**:
- Iteration count (e.g., "Iteration 1/3")
- Step IDs (e.g., "step_0")
- DAG dependency information
- Planning decision reasoning
- Judge confidence scores

### Pattern: Protocol Events

**Registration**:
- Type: `soothe.protocol.<component>.<action>`
- Template: Concise status message
- Verbosity: `VerbosityTier.DETAILED`

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
- Verbosity: `VerbosityTier.QUIET` (always visible)

**Display**:
```
✗ Tool execution failed
  └ compilation error at line 42
```

## Implementation Requirements

### RendererProtocol Implementation (RFC-0019)

Each renderer implements `RendererProtocol` callbacks for mode-specific display:

**CliRenderer** (`src/soothe/ux/cli/renderer.py`):
- `on_tool_call()` → writes `⚙ ToolName(args)` to stderr
- `on_tool_result()` → writes `└ ✓ result (duration)` to stderr
- `on_assistant_text()` → streams text to stdout
- `on_progress_event()` → delegates to `StreamDisplayPipeline`

**TuiRenderer** (`src/soothe/ux/tui/renderer.py`):
- Implements same callbacks with Rich widget output
- Uses `VerbosityTier` for visibility filtering
- Maintains display state (streaming buffers, panel updates)

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
- Use `make_dot_line()` for tree indentation
- Colors: blue (assistant), green (success), red (error), yellow (progress), magenta (subagent)
- Icons: ● (in progress), ✓ (success), ✗ (error), ⚙ (tool/agent)
- Indentation: 2 spaces per level (Level 1 = 0 spaces, Level 2 = 2 spaces, Level 3 = 5 spaces)

**Three-Level Tree Formatting**:
```
● Level 1: Goal/Summary
  └ Level 2: Step description
     └ ✓ Level 3: Result metrics
```

## Verbosity Classification

### VerbosityTier Mapping (RFC-0024)

The display system uses RFC-0024's unified `VerbosityTier` for visibility classification:

| VerbosityTier | Integer | Description |
|---------------|---------|-------------|
| `QUIET` | 0 | Always visible (errors, assistant text, final reports) |
| `NORMAL` | 1 | Standard progress (plan updates, milestones, agentic loop) |
| `DETAILED` | 2 | Detailed internals (protocol events, tool calls, subagent activity) |
| `DEBUG` | 3 | Everything including internals (thinking, heartbeats) |
| `INTERNAL` | 99 | Never shown at any verbosity level |

Visibility check: `tier <= verbosity` (integer comparison).

The classifier should be conservative: if uncertain, classify as `DETAILED` or `INTERNAL` to avoid leaking low-value internals into `normal`.

### Verbosity behavior

#### `quiet`
Show (VerbosityTier `QUIET` = 0):
- extracted final answer when confidence is high
- compact structured fallback when extraction is uncertain
- concise actionable errors
- assistant text
- final reports

Hide (VerbosityTier > 0):
- lifecycle events (`DETAILED`)
- protocol events (`DETAILED`)
- plan updates (`NORMAL`)
- milestones (`NORMAL`)
- raw tool activity (`DETAILED`)

#### `normal` (default)
Show (VerbosityTier ≤ 1):
- plan updates (`NORMAL`)
- brief progress milestones (`NORMAL` or `QUIET`)
- concise tool summaries when they add clarity (`NORMAL` for subagent tools)
- cleaned final response (`QUIET`)
- user-facing errors (`QUIET`)
- agentic loop events (`NORMAL`)

Hide (VerbosityTier > 1):
- lifecycle events (`DETAILED`)
- protocol counters (`DETAILED`)
- thread IDs (`DETAILED`)
- daemon state and PID details (`DETAILED`)
- plan reasoning (`DETAILED`)
- raw step states such as `[pending]` (`DETAILED`)
- raw tool invocation spam (`DETAILED`)
- subagent internals (`DETAILED`)

#### `detailed`
Show (VerbosityTier ≤ 2):
- plan updates (`NORMAL`)
- milestones (`NORMAL` or `QUIET`)
- tool summaries (`DETAILED`)
- cleaned final response (`QUIET`)
- richer operational detail than `normal` (`DETAILED`)
- subagent activity (`DETAILED`)

Hide (VerbosityTier > 2):
- thinking events (`DEBUG`)
- heartbeats (`DEBUG`)
- internal events (`INTERNAL`)

#### `debug`
Show all VerbosityTier values except `INTERNAL`:
- All above categories
- thinking events (`DEBUG`)
- heartbeats (`DEBUG`)

## Presentation and Formatting Rules

### Shared response cleaning

Before final assistant text is shown in `quiet`, `normal`, and `detailed`, the system must:
- remove internal JSON blocks and search data tags
- remove decorative filler such as `Let me know if...`
- remove non-essential embellishment
- normalize whitespace
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
2. Register with template and VerbosityTier
3. Emit event
→ Automatically displays without renderer changes
```

**Adding New VerbosityTier Values** (rare):
```
1. Add to VerbosityTier enum in verbosity_tier.py (RFC-0024)
2. Update _VERBOSITY_LEVEL_VALUES mapping
3. Use in register_event() calls
→ Renderers need no changes (integer comparison handles new values)
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
- **RFC-0024**: VerbosityTier Unification

## Related Documents

- [RFC-0013](./RFC-0013-daemon-communication-protocol.md) - Daemon protocol
- [RFC-0015](./RFC-0015-progress-event-protocol.md) - Event system
- [RFC-0019](./RFC-0019-unified-event-processing.md) - Event processing
- [RFC-0024](./RFC-0024-verbosity-tier-unification.md) - VerbosityTier unification
- [IG-066](../impl/IG-066-subagent-event-display-fix.md) - Implementation example

## CLI Stream Display Pipeline

This section defines the CLI-specific stream display pipeline that processes events into a streaming narrative with goal/step/subagent context.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Event Processing Paths                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  LangChain Messages (AIMessage.tool_calls, ToolMessage)                 │
│       ↓                                                                  │
│  EventProcessor._handle_ai_message() / _handle_tool_message()           │
│       ↓                                                                  │
│  CliRenderer.on_tool_call() / on_tool_result()                          │
│       ↓                                                                  │
│  ⚙ ToolName(args)  ───────────────────────────────────────────────────► │
│     └ ✓ Result (duration)                                                │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Custom Events (goal, step, subagent)                                   │
│       ↓                                                                  │
│  CliRenderer.on_progress_event()                                        │
│       ↓                                                                  │
│  StreamDisplayPipeline.process(event, verbosity)                         │
│       ↓                                                                  │
│  DisplayLine[]                                                           │
│       ↓                                                                  │
│  CliRenderer.write_lines()                                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key Separation**:
- **Tool display**: Handled by `CliRenderer.on_tool_call`/`on_tool_result` via `EventProcessor` processing LangChain `tool_calls`
- **Goal/Step/Subagent display**: Handled by `StreamDisplayPipeline` processing custom events

### Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `DisplayLine` | `stream/display_line.py` | Structured output unit |
| `PipelineContext` | `stream/context.py` | Goal/step state tracking |
| `StreamDisplayPipeline` | `stream/pipeline.py` | Goal/step/subagent event processing |
| `CliRenderer` | `renderer.py` | Tool display + pipeline output to stdout/stderr |
| `EventProcessor` | `core/event_processor.py` | LangChain message routing |

### DisplayLine Structure

```python
@dataclass
class DisplayLine:
    level: int  # 1=goal, 2=step/tool, 3=result
    content: str
    icon: str  # "●", "└", "⚙", "✓", "✗"
    indent: str  # computed from level
    status: str | None  # "running" for parallel tools
    duration_ms: int | None  # timing suffix
```

### Indent Levels

| Level | Indent | Usage |
|-------|--------|-------|
| 1 | `""` | Goal header, completion |
| 2 | `"  └ "` | Step header, tool call (via CliRenderer) |
| 3 | `"     └ "` | Tool result, milestone |

### CLI Event Visibility (NORMAL Verbosity)

| Event Type | Tier | Output Format |
|------------|------|---------------|
| `soothe.agentic.loop.started` | NORMAL | `● Goal: {goal}` |
| `soothe.cognition.plan.step_started` | NORMAL | `  └ Step {n}: {description}` |
| `soothe.subagent.*.dispatched` | NORMAL | `  ⚙ {name}_subagent({query})` |
| `soothe.subagent.*.step` | NORMAL | `     └ ✓ {milestone}` |
| `soothe.subagent.*.completed` | NORMAL | `     └ ✓ Done: {summary} ({duration}s)` |
| `soothe.cognition.plan.step_completed` | NORMAL | `  ✓ Step {n} done ({duration}s)` |
| `soothe.agentic.loop.completed` | QUIET | `● Goal: {goal} (complete, {steps} steps, {total}s)` |

**Note**: Tool calls (`⚙ ToolName(args)`) are displayed by `CliRenderer.on_tool_call`/`on_tool_result` via `EventProcessor`, not through the pipeline. Tool events (`soothe.tool.*`) are `DETAILED` verbosity for internal progress tracking.

### Parallel Tool Handling

When multiple tools execute concurrently:

```
  └ Step {n}: {description} (parallel)
  ⚙ {name}({args}) [running]
  ⚙ {name2}({args}) [running]
     └ ✓ {name}: {summary} ({duration}ms)
     └ ✓ {name2}: {summary} ({duration}ms)
```

### Subagent Compact Hybrid

Subagent activity shows key milestones only:

```
  ⚙ research_subagent("query")
     └ ✓ arxiv: 15 results
     └ ✓ Done: 5 papers (45.2s)
```

Hidden: internal LLM reasoning, result parsing, synthesis steps.

### CLI Example Output

```
● Goal: Analyze codebase structure
  └ Step 1: Read configuration files

  ⚙ ReadFile("config.yml")
     └ ✓ Read 2.3 KB (42 lines) (150ms)

  ⚙ Glob("*.py")
     └ ✓ Found 150 files (80ms)

  ✓ Step 1 done (3.2s)

  └ Step 2: Parse dependencies

  ⚙ ReadFile("requirements.txt")
     └ ✓ Read 1.1 KB (95ms)
  ⚙ ReadFile("pyproject.toml")
     └ ✓ Read 2.4 KB (120ms)

  ✓ Step 2 done (1.8s)

● Goal: Analyze codebase structure (complete, 2 steps, 5.0s)

The codebase contains 150 Python files...
```

**Note**: Tool calls (⚙ ReadFile) are displayed by `CliRenderer` via `EventProcessor`, not through events. Goal/Step display comes from the pipeline processing events.

---

*This RFC establishes the registry-driven display architecture for consistent, extensible event display.*
# RFC-0020: Event Display Architecture

**RFC**: 0020  
**Title**: Event Display Architecture  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-03-26  
**Updated**: 2026-03-30  
**Dependencies**: RFC-0001, RFC-0002, RFC-0003, RFC-0013, RFC-0015, RFC-0019, RFC-0024

> **Note**: Rendering architecture is defined by RFC-0019 (`RendererProtocol` callbacks). This RFC defines display patterns, verbosity behavior, and formatting rules.

## Abstract

This RFC establishes the **registry-driven, three-level tree display system** for agent activity events across CLI and TUI interfaces. Events register display metadata (templates, verbosity) at definition time, enabling automatic integration without renderer modifications.

**Core Constraint**: Display hierarchy is strictly limited to **3 levels** (goal → step → result) to maintain terminal readability.

---

## 1. Three-Level Tree Structure

### 1.1 Level Definitions

| Level | Name | Indent | Icons | Content |
|-------|------|--------|-------|---------|
| 1 | Goal | `""` | `●` | Goal/phase start or completion |
| 2 | Step/Tool | `"  "` | `└`, `⚙`, `✓` | Step description, tool call, step completion |
| 3 | Result | `"     "` | `└ ✓/✗` | Outcome, metrics, status |

### 1.2 Icon Reference

| Icon | Meaning | Level |
|------|---------|-------|
| `●` | Goal/phase marker | 1 |
| `└` | Step/action connector | 2, 3 |
| `⚙` | Tool or subagent execution | 2 |
| `✓` | Success indicator | 2 (completion), 3 (result) |
| `✗` | Error indicator | 2, 3 |

### 1.3 Canonical Display Format

```
● Goal: {description}
  └ Step 1: {step_description}
  ⚙ ToolName("argument")
     └ ✓ Result summary (150ms)
  ✓ Step 1 done (3.2s)
  └ Step 2: {step_description}
  ⚙ AnotherTool("args")
     └ ✓ Result (80ms)
  ✓ Step 2 done (1.8s)
● Goal: {description} (complete, 2 steps, 5.0s)

{assistant response}
```

**Hidden Details** (internal, never shown):
- Iteration count, Step IDs, DAG dependencies, planning decisions, judge scores

---

## 2. Design Principles

### 2.1 Registry-Driven Display Metadata

Events register at definition time:
- `summary_template`: Format string with field interpolation (e.g., `"Step {step}"`)
- `verbosity`: VerbosityTier for visibility filtering (RFC-0024)

Renderers query the registry; never hardcode strings.

### 2.2 Shared Presentation Policy

Verbosity semantics defined once, shared across headless CLI and TUI:
- **Shared policy**: classifies events, cleans text, decides visibility
- **Headless**: prints as separated text blocks
- **TUI**: maps into conversation/activity/plan widgets

### 2.3 Surface-Aware Rendering (RFC-0019)

| Component | Responsibility |
|-----------|----------------|
| `EventProcessor` | Unified event routing, state management, verbosity filtering |
| `RendererProtocol` | Callback interface for rendering |
| `CliRenderer` | CLI-specific display (stdout/stderr) |
| `TuiRenderer` | Rich widget output |

**RendererProtocol Callbacks**:
- `on_assistant_text()` → streaming text
- `on_tool_call()` / `on_tool_result()` → tool display
- `on_progress_event()` → custom events
- `on_plan_created/step_started/step_completed()` → plan progress

---

## 3. Verbosity Classification (RFC-0024)

### 3.1 VerbosityTier Mapping

| Tier | Value | Show at Level | Description |
|------|-------|---------------|-------------|
| `QUIET` | 0 | quiet+ | Errors, final answer, assistant text |
| `NORMAL` | 1 | normal+ | Plan updates, milestones, tool summaries |
| `DETAILED` | 2 | detailed+ | Protocol events, subagent internals |
| `DEBUG` | 3 | debug | Thinking, heartbeats |
| `INTERNAL` | 99 | never | Never displayed |

**Visibility Rule**: `tier <= verbosity` (integer comparison)

### 3.2 Verbosity Behavior Summary

| Content | quiet | normal | detailed | debug |
|---------|-------|--------|----------|-------|
| Final answer | ✓ | ✓ | ✓ | ✓ |
| Errors | ✓ | ✓ | ✓ | ✓ |
| Plan updates | ✗ | ✓ | ✓ | ✓ |
| Tool summaries | ✗ | ✓ | ✓ | ✓ |
| Milestones | ✗ | ✓ | ✓ | ✓ |
| Protocol/lifecycle | ✗ | ✗ | ✓ | ✓ |
| Subagent internals | ✗ | ✗ | ✓ | ✓ |
| Thinking/heartbeats | ✗ | ✗ | ✗ | ✓ |

---

## 4. Event Display Patterns

### 4.1 Tool Activity

**Display** (via `CliRenderer.on_tool_call`/`on_tool_result`):
```
  ⚙ ReadFile("config.yml")
     └ ✓ Read 2.3 KB (42 lines) (150ms)
```

**Verbosity**: `NORMAL`

**Tool Output Formatting Pipeline**:
```
Tool Result → Classifier → Tool-Specific Formatter → ToolBrief → Display
```

| Category | Pattern | Example |
|----------|---------|---------|
| FileOps | `Read {size} ({lines} lines)` | `✓ Read 2.3 KB (42 lines)` |
| FileOps | `Found {count} files` | `✓ Found 42 files` |
| Execution | `Done` / `Failed: {reason}` | `✓ Done` / `✗ Failed: timeout` |
| Media | `Transcribed {duration}s` | `✓ Transcribed 45.2s` |

### 4.2 Subagent Activity

**Events**: `soothe.subagent.<name>.{dispatched,step,completed}`

**Display**:
```
  ⚙ browser_subagent("search for docs")
     └ ✓ Navigate to page | https://example.com
     └ ✓ Extract content | hello world
     └ ✓ Done (45.2s)
```

**Verbosity**: `NORMAL`

### 4.3 Agentic Loop Progress

**Events**: `soothe.agentic.{loop,step}.{started,completed}`

| Event | Level | Tier | Template |
|-------|-------|------|----------|
| `loop.started` | 1 | `NORMAL` | `● Goal: {goal}` |
| `step.started` | 2 | `DETAILED` | `  └ Step {n}: {description}` |
| `step.completed` | 2 | `NORMAL` | `  ✓ Step {n} done ({duration}s)` |
| `loop.completed` | 1 | `QUIET` | `● Goal: {goal} (complete, {steps} steps)` |

### 4.4 Error Events

**Type**: `soothe.error.<component>.<type>`  
**Verbosity**: `QUIET` (always visible)

```
✗ Tool execution failed
  └ compilation error at line 42
```

---

## 5. CLI Stream Display Pipeline

### 5.1 Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  LangChain Messages (AIMessage.tool_calls, ToolMessage)        │
│       ↓                                                        │
│  EventProcessor._handle_ai_message() / _handle_tool_message()  │
│       ↓                                                        │
│  CliRenderer.on_tool_call() / on_tool_result()                 │
│       ↓                                                        │
│  ⚙ ToolName(args)                                              │
│     └ ✓ Result (duration)                                      │
├────────────────────────────────────────────────────────────────┤
│  Custom Events (goal, step, subagent)                          │
│       ↓                                                        │
│  CliRenderer.on_progress_event()                               │
│       ↓                                                        │
│  StreamDisplayPipeline.process(event, verbosity)               │
│       ↓                                                        │
│  DisplayLine[] → CliRenderer.write_lines()                     │
└────────────────────────────────────────────────────────────────┘
```

**Key Separation**:
- **Tool display**: `CliRenderer` via `EventProcessor` processing LangChain `tool_calls`
- **Goal/Step/Subagent**: `StreamDisplayPipeline` processing custom events

### 5.2 Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `DisplayLine` | `stream/display_line.py` | Structured output unit |
| `PipelineContext` | `stream/context.py` | Goal/step state tracking |
| `StreamDisplayPipeline` | `stream/pipeline.py` | Event processing |
| `CliRenderer` | `renderer.py` | Output to stdout/stderr |
| `EventProcessor` | `core/event_processor.py` | Message routing |

### 5.3 Parallel Tool Handling

```
  └ Step 1: Analyze files (parallel)
  ⚙ ReadFile("a.py") [running]
  ⚙ ReadFile("b.py") [running]
     └ ✓ Read 1.2 KB (80ms)
     └ ✓ Read 2.4 KB (120ms)
  ✓ Step 1 done (150ms)
```

---

## 6. Formatting Rules

### 6.1 Width Constraints

| Constraint | Value |
|------------|-------|
| Default terminal width | 80 chars |
| Maximum summary | 50 chars |
| Maximum detail | 80 chars |
| Indentation | 2 spaces + connector |

### 6.2 Text Processing

- Normalize whitespace to single spaces
- Truncate at word boundaries with ellipsis (...)
- Remove internal JSON blocks, decorative filler, embellishment
- Preserve factual correctness and actionable guidance

### 6.3 Output Separation

- **Headless**: Every block begins with one empty line
- **TUI**: Equivalent visual separation via widget spacing

### 6.4 Error Handling

| Error | Action |
|-------|--------|
| Template error | Log and skip (never crash) |
| Missing metadata | Skip display |
| Malformed data | Log warning and skip |
| Width detection failure | Fall back to 80 chars |

---

## 7. Extensibility

**Adding New Events**:
1. Define event model with `type` field
2. Register with `register_event(class, verbosity, template)`
3. Emit event → Automatically displays

**Adding VerbosityTier Values** (rare):
1. Add to `VerbosityTier` enum (RFC-0024)
2. Update `_VERBOSITY_LEVEL_VALUES` mapping
3. Use in `register_event()` → Renderers need no changes

---

## 8. Success Criteria

1. **Registry-Driven**: All summaries use templates, not ad hoc strings
2. **Cross-Surface Consistency**: Headless and TUI share verbosity semantics
3. **Normal-Mode Cleanliness**: Hides internals, shows plan/milestones
4. **Quiet-Mode Usefulness**: Extracts answers with safe fallback
5. **Extensible**: New events work without renderer changes
6. **Resilient**: Errors don't crash display system
7. **Readable**: Clear visual hierarchy with consistent formatting

---

## References

| RFC | Title |
|-----|-------|
| RFC-0001 | System Conceptual Design |
| RFC-0002 | Core Modules Architecture |
| RFC-0013 | Unified Daemon Communication Protocol |
| RFC-0015 | Event System Design |
| RFC-0019 | Unified Event Processing |
| RFC-0024 | VerbosityTier Unification |

---

*This RFC establishes the registry-driven display architecture for consistent, extensible event display.*

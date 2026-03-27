# IG-082: TUI Event Display Polish

## Summary

Enhance TUI event processing display with domain-specific icons, semantic colors, improved formatting, and better progress visualization while preserving all CLI functionality through the RendererProtocol interface.

## Motivation

The current TUI uses simple colored dot prefixes (●) and basic tree structures, making it difficult to:
- Distinguish event categories at a glance
- Track progress of plan steps and iterations
- Understand execution flow hierarchy
- Identify subagent activities by namespace

Visual polish will dramatically improve readability and user experience without affecting CLI output.

## Scope

**In Scope:**
- Enhanced color palette with 15+ semantic categories
- Domain-specific Unicode icons for instant event recognition
- Improved tool execution display with progress indicators
- Better error visualization with severity classification
- Enhanced plan step and iteration tracking
- Subagent namespace-specific styling
- Progress bar visualization in PlanTree widget
- Enhanced InfoBar status display

**Out of Scope:**
- Any changes to RendererProtocol interface
- Any changes to CliRenderer implementation
- Any changes to EventProcessor logic
- Any changes to event registry or event types
- CLI output format modifications
- Performance optimization beyond visual rendering

## Architecture Context

### Shared Infrastructure

The TUI and CLI share a unified event processing architecture:

```
Daemon/Agent Stream → EventProcessor → RendererProtocol callbacks
                                      ↓
                            ┌─────────┴─────────┐
                            ↓                   ↓
                      TuiRenderer          CliRenderer
                    (panel widgets)     (stdout/stderr)
```

**Critical Constraint:** All changes must be confined to TuiRenderer internal methods and TUI-only utilities. The RendererProtocol interface contract must remain unchanged.

### Current State

**TuiRenderer** (`src/soothe/ux/tui/renderer.py`):
- Implements RendererProtocol callbacks
- Uses `DOT_COLORS` (6 basic colors) for colored dots
- Simple tree structure for tool calls/results
- Progress events with basic formatting

**Utilities** (`src/soothe/ux/tui/utils.py`):
- `DOT_COLORS`: `{"assistant": "blue", "success": "green", "error": "red", ...}`
- `make_dot_line()`: Creates `● ` prefix lines
- `make_tool_block()`: Tool call/result tree blocks

**Widgets** (`src/soothe/ux/tui/widgets.py`):
- `ConversationPanel`: RichLog for scrollable chat
- `PlanTree`: Static widget for plan visualization
- `InfoBar`: Status line with thread ID

### Target State

**Enhanced Visual System:**
- `DOT_COLORS`: 15+ semantic colors (tool_running, plan_step_active, subagent_browser, etc.)
- `EVENT_ICONS`: Domain-specific Unicode icons (🤖, ⚙, 📋, 🌐, 📚, etc.)
- Enhanced `make_dot_line()` with icon parameter
- Category-specific event routing in `on_progress_event()`
- Better duration formatting with context-aware precision
- Error severity classification with suggestions

**Widget Improvements:**
- PlanTree: Progress bar `[████░░░] 50%`, dependency arrows `← step1`
- InfoBar: Enhanced status (⏳ running, ✓ idle), subagent summary

## Implementation Plan

### Phase 1: Foundation (Priority: HIGH)

**Goal:** Establish enhanced visual foundation

#### 1.1 Enhanced Color Palette

**File:** `src/soothe/ux/tui/utils.py`

Expand `DOT_COLORS` dictionary (lines 12-19):

```python
DOT_COLORS: dict[str, str] = {
    # Primary agent activities
    "assistant": "bold blue",
    "assistant_streaming": "cyan",
    "user_input": "bold bright_white",

    # Tool execution lifecycle
    "tool_running": "yellow",
    "tool_success": "green",
    "tool_error": "bold red",

    # Protocol/infrastructure events
    "protocol": "dim white",
    "protocol_highlight": "dim cyan",

    # Subagent namespace colors
    "subagent_browser": "magenta",
    "subagent_research": "blue_magenta",
    "subagent_claude": "cyan_magenta",
    "subagent_general": "magenta",

    # Cognition/planning events
    "plan_created": "bold cyan",
    "plan_step_active": "yellow",
    "plan_step_done": "green",
    "plan_step_failed": "red",

    # Progress/iteration tracking
    "iteration": "dim yellow",
    "goal": "cyan",

    # Error handling
    "error": "bold red",
    "error_context": "dim red",
    "warning": "yellow",
    "critical": "bold red",

    # Success states
    "success": "bold green",
    "success_dim": "dim green",

    # Lifecycle events
    "lifecycle": "dim blue",
    "checkpoint": "dim cyan",
}
```

**Testing:** Verify colors work in dark/light terminal themes.

#### 1.2 Icon System

**File:** `src/soothe/ux/tui/utils.py`

Create `EVENT_ICONS` dictionary after `DOT_COLORS`:

```python
EVENT_ICONS: dict[str, str] = {
    # Agent activities
    "assistant": "🤖",
    "assistant_streaming": "💬",
    "user_input": ">",

    # Tool execution
    "tool_running": "⚙",
    "tool_success": "✓",
    "tool_error": "✗",

    # Planning/cognition
    "plan_created": "📋",
    "plan_step_active": "◐",
    "plan_step_done": "●",
    "plan_step_failed": "✗",
    "goal": "🎯",

    # Subagent types
    "subagent_browser": "🌐",
    "subagent_research": "📚",
    "subagent_claude": "🧠",
    "subagent_general": "🤖",

    # Protocol/infrastructure
    "protocol": "●",
    "memory": "💾",
    "context": "📄",
    "checkpoint": "📌",

    # Progress tracking
    "iteration": "🔄",
    "progress": "⏳",

    # Status
    "error": "❌",
    "warning": "⚠",
    "success": "✅",

    # Lifecycle
    "thread_created": "🆕",
    "thread_saved": "💾",
    "thread_resumed": "▶",
}
```

Add fallback helper for terminals without Unicode support:

```python
def get_icon(category: str, unicode_supported: bool = True) -> str:
    """Get icon for category with fallback for non-Unicode terminals.

    Args:
        category: Icon category key.
        unicode_supported: Whether terminal supports Unicode.

    Returns:
        Icon string or ASCII fallback.
    """
    if unicode_supported:
        return EVENT_ICONS.get(category, "●")

    # ASCII fallbacks
    ascii_fallbacks = {
        "assistant": ">",
        "assistant_streaming": ">",
        "tool_running": "*",
        "tool_success": "+",
        "tool_error": "x",
        "plan_created": "#",
        "plan_step_active": "~",
        "plan_step_done": "*",
        "plan_step_failed": "x",
        "subagent_browser": "@",
        "subagent_research": "@",
        "subagent_claude": "@",
        "subagent_general": "@",
        "error": "!",
        "warning": "?",
        "success": "+",
        "iteration": "~",
        "goal": "#",
    }
    return ascii_fallbacks.get(category, "●")
```

#### 1.3 Enhanced Rendering Helpers

**File:** `src/soothe/ux/tui/utils.py`

Update `make_dot_line()` to accept icon parameter:

```python
def make_dot_line(
    color: str,
    text: str | Text,
    body: str | Text | None = None,
    icon: str | None = None,
    unicode_supported: bool = True,
) -> Text:
    """Create Claude Code-style line with icon or colored dot prefix.

    Args:
        color: Rich color name.
        text: Main text to display.
        body: Optional body content on subsequent lines.
        icon: Optional icon category key (uses EVENT_ICONS).
        unicode_supported: Whether terminal supports Unicode.

    Returns:
        Rich Text with icon/dot prefix, main text, and optional body.
    """
    # Use icon if provided, else fallback to dot
    prefix_icon = get_icon(icon, unicode_supported) if icon else "●"
    prefix = Text(prefix_icon + " ", style=color)

    main_text = Text(text) if isinstance(text, str) else text

    result = Text()
    result.append(prefix)
    result.append(main_text)

    if body is not None:
        result.append("\n")
        if isinstance(body, str):
            lines = body.split("\n")
            for i, line in enumerate(lines):
                connector = "  └ " if i == 0 else "    "
                result.append(Text(connector, style="dim"))
                result.append(line)
                if i < len(lines) - 1:
                    result.append("\n")
        else:
            result.append(Text("  └ ", style="dim"))
            result.append(body)

    return result
```

Add duration formatting helper:

```python
def format_duration_enhanced(duration_ms: int, context: str = "general") -> tuple[str, str]:
    """Format duration with context-aware precision and color.

    Args:
        duration_ms: Duration in milliseconds.
        context: Display context ("general", "long_running", "tool", "plan").

    Returns:
        (formatted_string, color_style) tuple.
    """
    if duration_ms >= 60000:  # >= 1 minute
        seconds = duration_ms / 1000
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s", "bold dim" if context == "long_running" else "dim"

    if duration_ms >= 5000:  # >= 5 seconds
        return f"{duration_ms / 1000:.1f}s", "bold dim"

    if duration_ms >= 1000:  # >= 1 second
        return f"{duration_ms / 1000:.2f}s", "dim"

    if duration_ms >= 100:  # >= 100ms
        return f"{duration_ms}ms", "dim"

    # < 100ms - very fast
    return f"{duration_ms}ms", "dim italic"
```

Update `make_tool_block()` to use icons:

```python
def make_tool_block(
    name: str,
    args_summary: str,
    output: str | None = None,
    status: str = "running",
    unicode_supported: bool = True,
) -> Text:
    """Create tool block with icon prefix and progress placeholder.

    Args:
        name: Tool name.
        args_summary: Args summary string.
        output: Optional output to show.
        status: Tool status ('running', 'success', 'error').
        unicode_supported: Whether terminal supports Unicode.

    Returns:
        Rich Text formatted as:
            ⚙ ToolName(args_summary)
              └ output
    """
    # Determine icon and color based on status
    icon_category = {
        "running": "tool_running",
        "success": "tool_success",
        "error": "tool_error",
    }.get(status, "tool_running")

    color = DOT_COLORS.get(f"tool_{status}", "yellow")

    # Build tool call line
    tool_text = Text()
    tool_text.append(name, style="bold")
    tool_text.append(f"({args_summary})")

    # Add progress placeholder for running tools
    if status == "running":
        tool_text.append(" ⏳", style="dim yellow")

    return make_dot_line(color, tool_text, output, icon=icon_category, unicode_supported=unicode_supported)
```

**Testing:** Visual inspection in TUI for icon display, fallback behavior.

### Phase 2: Event Display Enhancements (Priority: HIGH)

#### 2.1 Enhanced Tool Execution Display

**File:** `src/soothe/ux/tui/renderer.py`

Update `on_tool_call()` (lines 157-193):

```python
def on_tool_call(
    self,
    name: str,
    args: dict[str, Any],
    tool_call_id: str,
    *,
    is_main: bool,  # noqa: ARG002
) -> None:
    """Write tool call block with progress indicator.

    Args:
        name: Tool name.
        args: Parsed arguments.
        tool_call_id: Tool call identifier.
        is_main: True if from main agent.
    """
    if not self._on_panel_write:
        return

    display_name = get_tool_display_name(name)
    args_summary = format_tool_call_args(name, {"args": args})

    # Detect long-running tools for special indicator
    is_long_running = self._is_long_running_tool(name)

    if tool_call_id:
        self._state.current_tool_calls[tool_call_id] = {
            "name": display_name,
            "args_summary": args_summary,
        }
        self._state.tool_call_start_times[tool_call_id] = time.time()

    # Finalize streaming before tool block
    if self._state.streaming_active:
        self._state.streaming_active = False
        self._state.streaming_text_buffer = ""

    # Use enhanced tool block
    self._on_panel_write(make_tool_block(display_name, args_summary, status="running"))

    # Optional: Add separate progress bar for long-running tools
    if is_long_running:
        progress_line = Text()
        progress_line.append("  ⏳ ", style="dim yellow")
        progress_line.append("Running...", style="dim")
        self._on_panel_write(progress_line)
```

Add helper method:

```python
def _is_long_running_tool(self, name: str) -> bool:
    """Detect if tool typically takes >5 seconds.

    Args:
        name: Tool name.

    Returns:
        True if tool is known to be long-running.
    """
    long_running_tools = {
        "web_search",
        "research_subagent",
        "browser_subagent",
        "claude_subagent",
        "execute_bash_command",
    }
    return any(lr in name for lr in long_running_tools)
```

Update `on_tool_result()` (lines 195-238):

```python
def on_tool_result(
    self,
    name: str,  # noqa: ARG002
    result: str,
    tool_call_id: str,
    *,
    is_error: bool,
    is_main: bool,  # noqa: ARG002
) -> None:
    """Write tool result with enhanced duration formatting.

    Args:
        name: Tool name.
        result: Result content.
        tool_call_id: Tool call identifier.
        is_error: True if result indicates error.
        is_main: True if from main agent.
    """
    if not self._on_panel_write:
        return

    if tool_call_id:
        self._state.current_tool_calls.pop(tool_call_id, None)

    # Calculate duration
    duration_ms = 0
    if tool_call_id and tool_call_id in self._state.tool_call_start_times:
        start_time = self._state.tool_call_start_times.pop(tool_call_id)
        duration_ms = int((time.time() - start_time) * 1000)

    # Format duration with enhanced formatting
    duration_str, duration_style = format_duration_enhanced(duration_ms, context="tool")

    # Choose icon and color
    icon_category = "tool_error" if is_error else "tool_success"
    icon = get_icon(icon_category)
    color = DOT_COLORS[icon_category]

    # Create result line
    result_line = Text()
    result_line.append("  └ ", style="dim")
    result_line.append(icon + " ", style=color)
    result_line.append(result[:120], style="dim")

    # Add duration with appropriate styling
    if duration_ms > 0:
        result_line.append(f" [{duration_str}]", style=duration_style)

    self._on_panel_write(result_line)
```

#### 2.2 Enhanced Error Handling

**File:** `src/soothe/ux/tui/renderer.py`

Update `on_error()` (lines 249-257):

```python
def on_error(self, error: str, *, context: str | None = None) -> None:
    """Write error with severity classification and suggestion.

    Args:
        error: Error message.
        context: Optional error context.
    """
    if not self._on_panel_write:
        return

    # Classify severity
    severity = self._classify_error_severity(error, context)

    # Choose icon and color based on severity
    icon_category = {
        "critical": "critical",
        "warning": "warning",
        "error": "error",
    }.get(severity, "error")

    icon = get_icon(icon_category)
    color = DOT_COLORS[icon_category]

    # Create error line
    error_line = Text()
    error_line.append(f"{icon} ", style=color)

    if context:
        error_line.append(f"[{context}] ", style="dim red")

    error_line.append(error[:120], style=color)

    self._on_panel_write(error_line)

    # Add suggestion if available
    suggestion = self._get_error_suggestion(error, context)
    if suggestion:
        suggestion_line = Text()
        suggestion_line.append("  💡 ", style="dim cyan")
        suggestion_line.append("Suggestion: ", style="dim italic")
        suggestion_line.append(suggestion, style="dim cyan")
        self._on_panel_write(suggestion_line)
```

Add helper methods:

```python
def _classify_error_severity(self, error: str, context: str | None) -> str:
    """Classify error severity for appropriate display.

    Args:
        error: Error message.
        context: Error context.

    Returns:
        Severity level: "critical", "warning", or "error".
    """
    error_lower = error.lower()

    # Critical: system failures
    if any(term in error_lower for term in ["connection", "daemon", "socket", "fatal", "critical"]):
        return "critical"

    # Warning: recoverable issues
    if any(term in error_lower for term in ["retry", "timeout", "warning", "deprecated"]):
        return "warning"

    return "error"

def _get_error_suggestion(self, error: str, context: str | None) -> str | None:
    """Provide actionable suggestion for common errors.

    Args:
        error: Error message.
        context: Error context.

    Returns:
        Suggestion string or None.
    """
    error_lower = error.lower()

    if "connection" in error_lower:
        return "Check if daemon is running: soothe daemon status"

    if "timeout" in error_lower:
        return "Operation may take longer. Try again or check logs."

    if "permission" in error_lower:
        return "Check file permissions or run with appropriate access."

    if "not found" in error_lower and context == "thread":
        return "Thread may have expired. Use 'soothe thread list' to see available threads."

    return None
```

#### 2.3 Enhanced Progress Events

**File:** `src/soothe/ux/tui/renderer.py`

Refactor `on_progress_event()` (lines 259-369) with category routing:

```python
def on_progress_event(
    self,
    event_type: str,
    data: dict[str, Any],
    *,
    namespace: tuple[str, ...],
) -> None:
    """Write progress event with category-specific formatting.

    Args:
        event_type: Event type string.
        data: Event payload.
        namespace: Subagent namespace.
    """
    if not self._on_panel_write:
        return

    # Determine event category
    category = self._classify_event_category(event_type)

    # Route to category-specific display
    if category == "subagent":
        self._display_subagent_event(event_type, data, namespace)
    elif category == "plan":
        self._display_plan_event(event_type, data)
    elif category == "context":
        self._display_context_event(event_type, data)
    elif category == "memory":
        self._display_memory_event(event_type, data)
    elif category == "iteration":
        self._display_iteration_event(event_type, data)
    elif category == "lifecycle":
        self._display_lifecycle_event(event_type, data)
    else:
        # Generic display
        self._display_generic_event(event_type, data, namespace)
```

Add classification helper:

```python
def _classify_event_category(self, event_type: str) -> str:
    """Classify event type into category for routing.

    Args:
        event_type: Event type string.

    Returns:
        Category: "subagent", "plan", "context", "memory", "iteration", "lifecycle", or "general".
    """
    if "subagent" in event_type:
        return "subagent"
    if "plan" in event_type or "goal" in event_type:
        return "plan"
    if "context" in event_type:
        return "context"
    if "memory" in event_type:
        return "memory"
    if "iteration" in event_type or "loop" in event_type:
        return "iteration"
    if "lifecycle" in event_type or "checkpoint" in event_type:
        return "lifecycle"
    return "general"
```

Add category-specific display methods:

```python
def _display_subagent_event(
    self,
    event_type: str,
    data: dict[str, Any],
    namespace: tuple[str, ...],
) -> None:
    """Subagent event with namespace-specific styling.

    Args:
        event_type: Event type.
        data: Event payload.
        namespace: Namespace tuple.
    """
    # Extract subagent type
    subagent_type = self._extract_subagent_type(namespace)

    # Get icon and color
    icon_category = f"subagent_{subagent_type}"
    icon = get_icon(icon_category)
    color = DOT_COLORS.get(icon_category, DOT_COLORS["subagent_general"])

    # Build summary
    summary = self._build_event_summary(event_type, data)

    # Get details
    details = self._format_subagent_details(event_type, data, subagent_type)

    # Create namespace label
    namespace_label = self._resolve_namespace_label(namespace)

    # Create line
    line = Text()
    line.append(f"{icon} ", style=color)
    line.append(f"[{namespace_label}] ", style="bold")
    line.append(summary, style=color)

    if details:
        line.append("\n")
        line.append("  └ ", style="dim")
        line.append(details, style="dim")

    self._on_panel_write(line)

def _extract_subagent_type(self, namespace: tuple[str, ...]) -> str:
    """Extract subagent type from namespace.

    Args:
        namespace: Namespace tuple.

    Returns:
        Subagent type: "browser", "research", "claude", or "general".
    """
    for segment in namespace:
        segment_str = str(segment).lower()
        if "browser" in segment_str:
            return "browser"
        if "research" in segment_str:
            return "research"
        if "claude" in segment_str:
            return "claude"
    return "general"

def _format_subagent_details(
    self,
    event_type: str,
    data: dict[str, Any],
    subagent_type: str,
) -> str | None:
    """Format subagent-specific details.

    Args:
        event_type: Event type.
        data: Event payload.
        subagent_type: Subagent type.

    Returns:
        Details string or None.
    """
    # Browser: show action + URL
    if subagent_type == "browser" and "step" in event_type:
        parts = []
        if action := data.get("action"):
            parts.append(f"→ {action}")
        if url := data.get("url"):
            parts.append(f"🔗 {url[:60]}")
        return " | ".join(parts) if parts else None

    # Research: show query/topic
    if subagent_type == "research":
        if "query" in data:
            return f"🔍 {data['query'][:60]}"
        if "topic" in data:
            return f"📖 {data['topic'][:60]}"

    # Claude: show cost
    if subagent_type == "claude" and "result" in event_type:
        cost = data.get("cost_usd", 0)
        duration_ms = data.get("duration_ms", 0)
        if cost > 0:
            duration_str, _ = format_duration_enhanced(duration_ms, "tool")
            return f"💰 ${cost:.2f} ({duration_str})"

    return None

def _display_plan_event(self, event_type: str, data: dict[str, Any]) -> None:
    """Plan event with progress indicators.

    Args:
        event_type: Event type.
        data: Event payload.
    """
    if "created" in event_type:
        self._display_plan_created(data)
    elif "step_started" in event_type:
        self._display_plan_step_started(data)
    elif "step_completed" in event_type:
        self._display_plan_step_completed(data)
    else:
        # Generic plan event
        summary = self._build_event_summary(event_type, data)
        icon = get_icon("plan_created")
        color = DOT_COLORS["plan_created"]
        self._on_panel_write(make_dot_line(color, summary, icon="plan_created"))

def _display_plan_created(self, data: dict[str, Any]) -> None:
    """Plan creation display.

    Args:
        data: Plan data.
    """
    goal = data.get("goal", "")
    steps = data.get("steps", [])
    reasoning = data.get("reasoning")

    icon = get_icon("plan_created")
    color = DOT_COLORS["plan_created"]

    # Header
    header = Text()
    header.append(f"{icon} ", style=color)
    header.append("Plan: ", style="bold")
    header.append(goal[:80], style="cyan")
    header.append(f" ({len(steps)} steps)", style="dim")

    self._on_panel_write(header)

    # Reasoning
    if reasoning:
        reasoning_line = Text()
        reasoning_line.append("  💭 ", style="dim italic")
        reasoning_line.append("Reasoning: ", style="dim italic")
        reasoning_line.append(reasoning[:100], style="dim")
        self._on_panel_write(reasoning_line)

    # First few steps
    for i, step in enumerate(steps[:5]):
        step_id = step.get("id", str(i))
        desc = step.get("description", "")
        depends_on = step.get("depends_on", [])

        step_line = Text()
        step_line.append("  ├ ", style="dim")
        step_line.append(step_id, style="dim cyan")
        step_line.append(": ", style="dim")
        step_line.append(desc[:60], style="dim")

        if depends_on:
            deps = ", ".join(depends_on)
            step_line.append(f" (← {deps})", style="dim italic cyan")

        self._on_panel_write(step_line)

    if len(steps) > 5:
        more_line = Text()
        more_line.append(f"  └ ... {len(steps) - 5} more steps", style="dim italic")
        self._on_panel_write(more_line)

def _display_plan_step_started(self, data: dict[str, Any]) -> None:
    """Plan step started display.

    Args:
        data: Step data.
    """
    step_id = data.get("step_id", "")
    description = data.get("description", "")

    icon = get_icon("plan_step_active")
    color = DOT_COLORS["plan_step_active"]

    line = Text()
    line.append(f"{icon} ", style=color)
    line.append(f"Step {step_id}: ", style="bold yellow")
    line.append(description[:60], style="yellow")
    line.append(" ⏳", style="dim")

    self._on_panel_write(line)

def _display_plan_step_completed(self, data: dict[str, Any]) -> None:
    """Plan step completed display.

    Args:
        data: Step data.
    """
    step_id = data.get("step_id", "")
    success = data.get("success", False)
    duration_ms = data.get("duration_ms", 0)

    icon_category = "plan_step_done" if success else "plan_step_failed"
    icon = get_icon(icon_category)
    color = DOT_COLORS[icon_category]

    line = Text()
    line.append(f"{icon} ", style=color)
    line.append(f"Step {step_id}: ", style=color)
    line.append("completed" if success else "failed", style=color)

    if duration_ms > 0:
        duration_str, _ = format_duration_enhanced(duration_ms, "plan")
        line.append(f" [{duration_str}]", style="dim")

    self._on_panel_write(line)
```

Continue with context, memory, iteration, lifecycle displays...

### Phase 3: Widget Enhancements (Priority: MEDIUM)

**Implementation deferred to later iteration.**

Will enhance:
- PlanTree with progress bar visualization
- InfoBar with richer status display

These are widget-only changes with no protocol interaction.

### Phase 4: Streaming Polish (Priority: LOW)

**Implementation deferred to later iteration.**

Optional enhancements:
- Markdown awareness in streaming text
- Typing animation during streaming

## Verification Strategy

### After Phase 1

```bash
# Visual testing
soothe --tui "test query"

# Verify:
# - Icons display correctly
# - Colors match semantic categories
# - Fallback works in non-Unicode terminals
```

### After Phase 2

```bash
# Tool execution test
soothe -p "search for AI advances"

# Verify:
# - Tool icons (⚙ ✓ ✗) display
# - Duration formatting works
# - Error suggestions appear
# - Subagent namespace icons show

# Plan test
soothe -p "create a plan to build a REST API"

# Verify:
# - Plan icon (📋) shows
# - Step progress indicators work
# - Reasoning displays correctly
```

### Full Integration Test

```bash
# Run verification suite
./scripts/verify_finally.sh

# Must pass:
# - 900+ unit tests
# - Linting (zero errors)
# - Code formatting checks

# CLI compatibility test
soothe --no-tui "test query"

# Verify:
# - stdout/stderr unchanged
# - Tree format intact
# - Timing display works
```

## Success Criteria

1. ✅ Icons display correctly in iTerm2, Terminal.app, Linux terminals
2. ✅ Colors provide clear semantic differentiation
3. ✅ Duration formatting shows appropriate precision
4. ✅ Error suggestions help users resolve issues
5. ✅ Subagent namespace styling distinct per type
6. ✅ Plan step progress clear and informative
7. ✅ CLI output unchanged (all tests pass)
8. ✅ No performance regression (streaming <50ms)

## Dependencies

- Rich library (already used by TUI)
- Unicode support detection (simple implementation)
- No new external dependencies

## Rollback Plan

If issues arise:

1. **Phase 1 Rollback**: Revert to original `DOT_COLORS` and `make_dot_line()`
2. **Phase 2 Rollback**: Restore original renderer methods
3. **Full Rollback**: Restore from git before implementation

Git commits will be made after each phase for safe rollback.

## Timeline

**Week 1:**
- Phase 1 implementation (2 days)
- Phase 2 implementation (3 days)
- Testing and refinement (1 day)

**Week 2:**
- Phase 3 widget enhancements (optional, 3 days)
- User feedback collection (2 days)

**Week 3:**
- Phase 4 streaming polish (optional, 2 days)
- Final testing and documentation (1 day)

## Notes

- **CLI Preservation is Critical**: All changes must respect RendererProtocol contract
- **Performance Matters**: Keep streaming updates lightweight
- **User Experience Focus**: Visual hierarchy should improve comprehension
- **Testing Required**: Run verify_finally.sh after every phase
- **Documentation**: Update user guide with new visual indicators

## References

- **Plan**: `/Users/chenxm/.claude/plans/vectorized-squishing-octopus.md`
- **RFC-0003**: CLI/TUI Architecture
- **RFC-0019**: Unified Event Processing
- **RFC-0020**: Duration Display
- **IG-053**: CLI/TUI Event Progress Implementation
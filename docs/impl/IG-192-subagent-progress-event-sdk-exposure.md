# IG-192: Subagent Progress Event SDK Exposure & CLI/TUI Display

**Created**: 2026-04-18
**Status**: Completed
**Scope**: SDK package UX utilities, CLI/TUI display pipeline
**Related**: RFC-500 (CLI/TUI Architecture), RFC-403 (Event Naming), IG-052 (Event System Optimization)

---

## Summary

Exposed important subagent progress events to CLI/TUI via soothe-sdk and adapted both CLI and TUI to display subagent events at DETAILED verbosity level.

**Phase 1 (SDK)**:
- Added event type constants to `soothe_sdk/events.py` for wire-safe references
- Created `soothe_sdk/ux/subagent_progress.py` with helper functions
- Updated `soothe_sdk/ux/__init__.py` to export new utilities

**Phase 2 (CLI/TUI)**:
- Updated `StreamDisplayPipeline` to handle capability events with unified naming
- Added handlers for browser steps, claude activity, and research judgement
- Modified `TextualUIAdapter` to process capability events at DETAILED level
- Implemented proper classification using SDK helpers

---

## Problem

CLI/TUI needed to identify and display important subagent progress events but:

1. **Missing constants**: SDK had no wire-safe event type strings for browser, claude, and most research events
2. **No progress helpers**: No way to identify which events are "important" (NORMAL tier) vs detailed internals
3. **Import boundary**: CLI cannot import daemon-side event classes (per dependency validation rules)
4. **Pipeline gaps**: StreamDisplayPipeline didn't handle capability.* events properly
5. **TUI filtering**: TextualUIAdapter only showed essential events, excluding subagent progress

**Impact**: CLI/TUI couldn't display subagent lifecycle events (started/completed) or meaningful progress (judgements, browser steps) at any verbosity level.

---

## Solution

### Phase 1: SDK Exposure

#### 1. Add Event Type Constants

Added constants to `soothe_sdk/events.py`:

```python
# Browser subagent events
SUBAGENT_BROWSER_STARTED = "soothe.capability.browser.started"
SUBAGENT_BROWSER_COMPLETED = "soothe.capability.browser.completed"
SUBAGENT_BROWSER_STEP_RUNNING = "soothe.capability.browser.step.running"
SUBAGENT_BROWSER_CDP_CONNECTING = "soothe.capability.browser.cdp.connecting"

# Claude subagent events
SUBAGENT_CLAUDE_TEXT_RUNNING = "soothe.capability.claude.text.running"
SUBAGENT_CLAUDE_TOOL_RUNNING = "soothe.capability.claude.tool.running"
SUBAGENT_CLAUDE_COMPLETED = "soothe.capability.claude.completed"

# Research subagent events
SUBAGENT_RESEARCH_STARTED = "soothe.capability.research.started"
SUBAGENT_RESEARCH_COMPLETED = "soothe.capability.research.completed"
SUBAGENT_RESEARCH_JUDGEMENT_REPORTING = "soothe.capability.research.judgement.reporting"
```

#### 2. Add Progress Helper Functions

Created `soothe_sdk/ux/subagent_progress.py`:

```python
SUBAGENT_PROGRESS_EVENT_TYPES: Final[frozenset[str]] = frozenset({
    # Browser (NORMAL tier)
    "soothe.capability.browser.started",
    "soothe.capability.browser.completed",
    # Claude (NORMAL tier)
    "soothe.capability.claude.completed",
    # Research (NORMAL tier)
    "soothe.capability.research.started",
    "soothe.capability.research.completed",
    "soothe.capability.research.judgement.reporting",
})

def is_subagent_progress_event(event_type: str) -> bool:
    """Check if event is an important progress indicator."""
    return event_type in SUBAGENT_PROGRESS_EVENT_TYPES

def get_subagent_name_from_event(event_type: str) -> str | None:
    """Extract subagent name from capability event."""
    # Returns "browser", "claude", "research" or None
```

#### 3. Export via UX Package

Updated `soothe_sdk/ux/__init__.py` to export new utilities.

### Phase 2: CLI/TUI Display Adaptation

#### 1. StreamDisplayPipeline Classification

Updated `_classify_event()` to use SDK helper:

```python
# IG-192: Use SDK helper to identify important progress events
if event_type.startswith("soothe.capability."):
    if is_subagent_progress_event(event_type):
        return VerbosityTier.NORMAL
    # Other capability events (internal steps) - DETAILED
    return VerbosityTier.DETAILED
```

**Key logic**:
- Important progress events (started/completed/judgement) → NORMAL (visible by default)
- Internal steps (step.running, text.running, tool.running) → DETAILED (hidden at normal)

#### 2. Event Dispatch Handling

Updated `_dispatch_event()` to handle capability.* namespace:

```python
# Capability events (soothe.capability.<subagent>.<action>)
if event_type.startswith("soothe.capability."):
    parts = event_type.split(".")
    if len(parts) >= 4:
        subagent = parts[2]  # browser, claude, research
        action = parts[3]    # started, completed, judgement, step.running, etc.

        # Route to appropriate handler
        if action in ("started", "dispatching"):
            return self._on_subagent_dispatched(event, subagent)
        if "judgement" in action:
            return self._on_subagent_judgement(event)
        if "step" in action and "running" in action:
            return self._on_capability_step(event, subagent)
        if action == "completed":
            return self._on_subagent_completed(event, subagent)
```

#### 3. New Handlers for Capability Events

Added `_on_capability_step()` for browser automation:

```python
def _on_capability_step(self, event: dict, subagent_name: str) -> list[DisplayLine]:
    """Handle capability step event (browser automation steps)."""
    step = event.get("step", "")
    url = event.get("url", "")
    action = event.get("action", "")

    if url:
        brief = f"Step {step}: {action} on {url}"
    elif action:
        brief = f"Step {step}: {action}"
    else:
        brief = f"Step {step}"

    return [format_subagent_milestone(preview_first(brief, 60))]
```

Added `_on_capability_activity()` for claude text/tool:

```python
def _on_capability_activity(self, event: dict, subagent: str, action: str):
    """Handle capability activity (claude text/tool events)."""
    # These are DETAILED level - filtered at NORMAL verbosity
    return []
```

#### 4. TUI Adapter Update

Updated `_format_progress_event_lines_for_tui()`:

```python
# Subagent capability events - show at DETAILED verbosity
if event_type.startswith("soothe.capability."):
    # Only show important progress events (started/completed/judgement)
    # Internal steps filtered at DETAILED tier
    if is_subagent_progress_event(event_type):
        # Process through pipeline
        lines = pipeline.process(event_for_pipeline)
        # Render to text
        ...
```

---

## Important Progress Events

**Browser Subagent** (NORMAL tier at detailed level):
- `started`: Task dispatch with goal description
- `completed`: Duration and success status
- `step.running`: Individual automation steps (DETAILED - shown at detailed level)

**Claude Subagent** (NORMAL tier at detailed level):
- `completed`: Cost/duration metrics
- `text.running`, `tool.running`: Internal activity (DETAILED - shown at detailed level)

**Research Subagent** (NORMAL tier at detailed level):
- `started`: Research topic dispatch
- `completed`: Final synthesis completion
- `judgement.reporting`: LLM decision reasoning (meaningful progress indicator)
- `gathering`, `analyzing`, `summarizing`: Internal phases (DETAILED - shown at detailed level)

**Verbosity Level Display**:
- **Normal**: Only started/completed/judgement events
- **Detailed**: All capability events including internal steps
- **Debug**: All events with source prefix tags

---

## Usage Examples

### CLI Display

At **normal** verbosity:
```
🕵🏻‍♂️ browser_subagent "Login to dashboard"
✓ 🕵🏻‍♂️ Done: completed (3.2s)
```

At **detailed** verbosity:
```
🕵🏻‍♂️ browser_subagent "Login to dashboard"
  ✓ Step 1: navigate on https://example.com
  ✓ Step 2: click on #login-button
  ✓ Step 3: fill_form on #credentials
✓ 🕵🏻‍♂️ Done: completed (3.2s)
```

### TUI Display

TUI follows same verbosity filtering as CLI:
- Normal level: Shows subagent lifecycle and meaningful judgements
- Detailed level: Shows all internal steps and activity

---

## Architecture Alignment

**Maintains separation**:
- Daemon: Event definition, registration, emission (per IG-052)
- SDK: Event consumption, classification, helpers
- CLI: Event rendering, pipeline dispatch

**No import boundary violations**:
- CLI imports SDK (allowed)
- SDK independent (no daemon imports)
- Pipeline uses SDK helpers for classification

**Extends existing systems**:
- Pipeline classification integrates with domain-based defaults
- TUI adapter extends essential events framework
- Formatter functions reused for capability events

---

## Verification

All checks passed:
- ✓ Code formatting (ruff format)
- ✓ Linting (ruff check)
- ✓ Unit tests (1291 passed)
- ✓ Import boundary checks (SDK independent, CLI no daemon imports)
- ✓ Workspace integrity

---

## Files Modified

**SDK Package**:
```
packages/soothe-sdk/src/soothe_sdk/events.py          +21 constants
packages/soothe-sdk/src/soothe_sdk/ux/__init__.py      +3 exports
packages/soothe-sdk/src/soothe_sdk/ux/subagent_progress.py  +87 new file
```

**CLI Package**:
```
packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py   +60 handlers
packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py   +20 capability event logic
```

---

## References

- **RFC-500**: CLI/TUI Architecture (event flow, RendererProtocol)
- **RFC-403**: Unified Event Naming (capability domain semantics)
- **IG-052**: Event System Optimization (register_event API)
- **Daemon-side events**: `packages/soothe/src/soothe/subagents/*/events.py`

---

## Commit

Ready for commit after verification passed.
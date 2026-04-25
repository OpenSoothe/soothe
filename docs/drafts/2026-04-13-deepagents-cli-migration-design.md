# DeepAgents CLI Migration Design Draft

**Date**: 2026-04-13
**Status**: Draft
**Author**: AI Agent (Platonic Coding Phase 1)
**Version**: 2.0 (Complete Design)
**Approach**: Full Copy & Deep Integration (Recommended)

---

## Problem Statement

Soothe currently has a basic custom TUI (~1053 lines) that lacks features available in the mature upstream deepagents-cli package (~5069 lines + 20 widget files). This creates:

1. **Feature gap**: Soothe's TUI lacks sophisticated UI components (thread selector, autocomplete, approval UI, diff viewer)
2. **Maintenance burden**: Custom TUI code requires ongoing development
3. **Duplication**: Both packages implement similar Textual patterns independently
4. **Integration complexity**: Connecting Soothe's protocols to custom TUI requires extensive custom event handling

## Proposed Solution

**Migrate deepagents-cli TUI code into Soothe** using Full Copy & Deep Integration strategy, while preserving Soothe's CLI command structure and unique features (protocols, daemon, autopilot).

### Primary Goal

**Get deepagents' sophisticated UI features immediately**:
- Thread resume UI (thread_selector.py - 65KB with filtering/search)
- Advanced ChatInput (chat_input.py - 69KB with autocomplete, multi-line, history)
- Tool approval UI (approval.py - interactive HITL approval menu)
- Diff viewer (diff.py - inline code change visualization)
- 20+ polished widgets (status, loading, messages, welcome, autocomplete, etc.)

### Secondary Goals

- Reduce maintenance burden by leveraging upstream code
- Stay aligned with deepagents ecosystem for future improvements
- Preserve all Soothe-specific features (protocols, daemon, autopilot)

---

## Scope

### IN Scope

- **Replace**: Soothe's basic TUI (`src/soothe/ux/tui/*.py` - ~1053 lines)
- **Copy**: deepagents CLI TUI code (app.py + widgets + supporting modules)
- **Integrate**: Connect deepagents TUI to Soothe's backend (daemon, protocols, thread persistence)
- **Preserve**: Soothe's Typer CLI structure and subcommands
- **Add**: Protocol event rendering widgets for Soothe-specific events
- **Keep**: Autopilot dashboard (autopilot_screen.py, autopilot_dashboard.py)

### OUT of Scope

- deepagents deploy features (init, dev, deploy) - not relevant to Soothe
- deepagents agent management commands - Soothe has different architecture
- deepagents skills management - Soothe uses plugin system (RFC-600)
- deepagents argparse CLI - Soothe uses Typer (keep structure)

---

## Architecture After Migration

### Overall Stack

```
CLI Layer (Typer - unchanged)
  src/soothe/ux/cli/main.py
    └─ soothe, daemon, thread, config, health, autopilot commands

Execution Layer (unchanged)
  src/soothe/ux/cli/execution/
    ├─ launcher.py → decides TUI/headless/daemon modes
    ├─ daemon.py → daemon client connection
    └─ headless.py → non-TUI execution

TUI Layer (MIGRATED from deepagents)
  src/soothe/ux/tui/
    ├─ app.py (copied from deepagents_cli/app.py, 5069 lines)
    ├─ widgets/ (copied from deepagents_cli/widgets/, 20 files)
    ├─ input.py, sessions.py, theme.py (copied supporting modules)
    ├─ autopilot_screen.py (kept from Soothe)
    ├─ autopilot_dashboard.py (kept from Soothe)
    └─ soothe_adapter.py (NEW - backend bridge)

Integration Layer (NEW)
  src/soothe/ux/tui/
    ├─ soothe_backend_adapter.py (NEW - daemon stream adapter)
    ├─ thread_backend_bridge.py (NEW - thread persistence bridge)
    └─ widgets/protocol_event.py (NEW - protocol visualization)

Backend Layer (unchanged)
  src/soothe/ux/client/session.py → DaemonClient (WebSocket)
  src/soothe/daemon/ → WebSocket server
  src/soothe/core/runner/ → SootheRunner + protocols
  src/soothe/protocols/ → Protocol definitions
  src/soothe/backends/ → Protocol implementations
```

---

## Section 1: File Migration Strategy

### Files to Copy from deepagents-cli (~25-30 files)

**Core TUI Files**:
```
deepagents_cli/app.py (5069 lines) → src/soothe/ux/tui/app.py
deepagents_cli/input.py → src/soothe/ux/tui/input.py
deepagents_cli/theme.py → src/soothe/ux/tui/theme.py
deepagents_cli/sessions.py → src/soothe/ux/tui/sessions.py
deepagents_cli/config.py → src/soothe/ux/tui/config.py (partial - UI config only)
```

**Widget Files (all 20 files)**:
```
deepagents_cli/widgets/*.py → src/soothe/ux/tui/widgets/
  - chat_input.py (69KB - advanced input with autocomplete)
  - thread_selector.py (65KB - sophisticated resume UI)
  - messages.py (60KB - rich message rendering)
  - approval.py (17KB - HITL approval menu)
  - autocomplete.py (23KB - slash command autocomplete)
  - status.py (12KB - status bar)
  - diff.py (7KB - code diff viewer)
  - loading.py (5KB - loading indicators)
  - welcome.py (12KB - welcome banner)
  - tool_widgets.py (9KB - tool call visualization)
  - tool_renderers.py (4KB - tool output formatting)
  - message_store.py (22KB - message state management)
  - ask_user.py (14KB - user question prompts)
  - mcp_viewer.py (11KB - MCP server info)
  - model_selector.py (34KB - model selection UI)
  - history.py (6KB - conversation history navigation)
  - notification_settings.py (4KB)
  - theme_selector.py (4KB)
  - _links.py (2KB)
```

**Supporting Modules**:
```
deepagents_cli/tools.py → src/soothe/ux/tui/tools.py
deepagents_cli/tool_display.py → src/soothe/ux/tui/tool_display.py
deepagents_cli/clipboard.py → src/soothe/ux/tui/clipboard.py
deepagents_cli/editor.py → src/soothe/ux/tui/editor.py
deepagents_cli/file_ops.py → src/soothe/ux/tui/file_ops.py (partial - UI helpers only)
deepagents_cli/media_utils.py → src/soothe/ux/tui/media_utils.py
deepagents_cli/offload.py → src/soothe/ux/tui/offload.py
```

### Files NOT to Copy (deepagents-specific, irrelevant to Soothe)

- `deepagents_cli/main.py` (argparse CLI - Soothe uses Typer)
- `deepagents_cli/agent.py` (deepagents agent management - different architecture)
- `deepagents_cli/server*.py` (remote server architecture - Soothe uses daemon)
- `deepagents_cli/textual_adapter.py` (deepagents runtime adapter - replaced)
- `deepagents_cli/subagents.py` (deepagents subagent management - Soothe has plugins)
- `deepagents_cli/deploy/*` (deploy commands - not relevant)
- `deepagents_cli/skills/*` (skills management - Soothe uses plugins)
- `deepagents_cli/built_in_skills/*` (built-in skills - Soothe has own tools)

### Files to DELETE (old Soothe TUI - replaced)

- `src/soothe/ux/tui/app.py` (current 1053-line TUI)
- `src/soothe/ux/tui/widgets.py` (basic widgets)
- `src/soothe/ux/tui/renderer.py` (custom renderer)
- `src/soothe/ux/tui/state.py` (TUI state)
- `src/soothe/ux/tui/utils.py` (utilities)
- `src/soothe/ux/tui/modals.py` (modal screens)
- `src/soothe/ux/tui/commands.py` (slash command parsing)

### Files to KEEP (Soothe-specific, integrate into new TUI)

- `src/soothe/ux/tui/autopilot_screen.py` (autopilot dashboard)
- `src/soothe/ux/tui/autopilot_dashboard.py` (autopilot widgets)
- `src/soothe/ux/tui/__init__.py` (module init - needs update)

### Total Migration

- **Copy**: ~25-30 files from deepagents
- **Delete**: ~7 old Soothe TUI files
- **Keep**: ~2 autopilot files + integration
- **Net change**: +18-23 files in `src/soothe/ux/tui/`

---

## Section 2: Backend Integration Architecture

### Core Challenge

**deepagents TUI assumes direct `agent.astream()` connection**:
- Runtime: `create_agent()` → `Pregel` graph
- Stream: `agent.astream(stream_mode=["messages", "updates", "custom"])`
- Direct: No daemon layer, no WebSocket

**Soothe has daemon WebSocket layer**:
- Backend: `SootheRunner` → `Daemon` → WebSocket
- Client: `DaemonClient` connects to daemon
- Stream: Events over WebSocket protocol (RFC-400)
- Protocols: Custom `soothe.*` events from protocol orchestration

### Integration Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│  deepagents TUI (app.py + widgets)                      │
│  - Copied from deepagents_cli                           │
│  - Modified to use SootheBackendAdapter                 │
│  - All widgets unchanged (message rendering, input, etc)│
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  SootheBackendAdapter (NEW)                             │
│  - Mimics deepagents runtime interface                  │
│  - Internally connects to DaemonClient                  │
│  - Translates daemon events → deepagents format         │
│  - Injects protocol events → custom widgets             │
│  - Provides agent metadata (model, tools, threads)      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  DaemonClient (unchanged)                               │
│  - WebSocket connection to daemon                       │
│  - Send: input, commands                                │
│  - Receive: event stream                                │
│  - Thread management                                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  SootheDaemon (unchanged)                               │
│  - Receives user input via WebSocket                    │
│  - Runs SootheRunner.astream()                          │
│  - Yields (namespace, mode, data) tuples                │
│  - Includes soothe.* protocol events                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  SootheRunner + Protocols (unchanged)                   │
│  - Protocol orchestration                               │
│  - agent.astream() with custom events                   │
│  - Thread lifecycle management                          │
└─────────────────────────────────────────────────────────┘
```

### SootheBackendAdapter Implementation

```python
"""src/soothe/ux/tui/soothe_backend_adapter.py"""

class SootheBackendAdapter:
    """Adapter that presents deepagents-like interface to TUI
    while internally connecting to Soothe daemon.

    Replaces: deepagents_cli.textual_adapter.TextualUIAdapter
    Connects to: DaemonClient instead of direct agent runtime
    """

    def __init__(
        self,
        daemon_client: DaemonClient,
        config: SootheConfig,
        thread_manager: ThreadContextManager,
    ):
        self.daemon_client = daemon_client
        self.config = config
        self.thread_manager = thread_manager

    async def stream_messages(self, user_input: str):
        """Send input to daemon and stream events back.

        Mimics: agent.astream() interface that deepagents TUI expects
        Internally: uses DaemonClient.send_input() + websocket.recv()
        """
        # Send user input to daemon
        await self.daemon_client.send_input(user_input)

        # Stream events from daemon
        async for event in self.daemon_client.receive_events():
            # Parse WebSocket event format
            namespace, mode, data = self._parse_daemon_event(event)

            # Handle protocol events specially
            if mode == "custom" and data.get("type", "").startswith("soothe."):
                # Filter by verbosity, inject into protocol channel
                adapted = self._adapt_protocol_event(data)
                if adapted:
                    yield (namespace, mode, adapted)
            else:
                # Pass through as deepagents format
                yield (namespace, mode, data)

    def _adapt_protocol_event(self, event: dict):
        """Filter protocol events based on verbosity tier (RFC-501)."""
        verbosity = self.config.verbosity

        # Quiet: suppress all protocol events
        if verbosity == "quiet":
            return None

        # Minimal: show only plan steps
        if verbosity == "minimal":
            if not event["type"].startswith("soothe.plan"):
                return None

        # Normal: show plan + context + memory
        if verbosity == "normal":
            if event["type"].startswith("soothe.policy"):
                return None  # Policy too detailed

        # Detailed: show all protocol events
        return event

    async def get_thread_history(self, thread_id: str):
        """Load thread messages for resume.

        Uses: ThreadContextManager backend (unchanged)
        Returns: deepagents message format
        """
        thread_data = await self.thread_manager.load_thread(thread_id)
        return self._convert_to_deepagents_format(thread_data)

    async def list_threads(self):
        """List available threads for resume UI."""
        threads = await self.thread_manager.list_threads()
        return [
            {
                "id": t.id,
                "created_at": t.created_at,
                "message_count": t.message_count,
                "preview": t.preview,
            }
            for t in threads
        ]

    def get_agent_metadata(self):
        """Provide agent info for UI display."""
        return {
            "model": self.config.resolve_model("chat"),
            "tools": self._list_available_tools(),
            "subagents": self._list_available_subagents(),
        }
```

### Integration Points in app.py Modifications

**1. Replace runtime initialization** (app.py lines ~200-250):
```python
# deepagents original:
# self.agent = create_agent(...)
# self.ui_adapter = TextualUIAdapter(self.agent)

# SOOTHE: Replace with adapter
self.backend_adapter = SootheBackendAdapter(
    daemon_client=self.daemon_client,
    config=self.config,
    thread_manager=self.thread_manager,
)
```

**2. Replace stream invocation** (app.py lines ~800-900):
```python
# deepagents original:
# async for msg in self.agent.astream(...):

# SOOTHE: Use adapter instead
async for namespace, mode, data in self.backend_adapter.stream_messages(user_input):
    await self._handle_stream_event(namespace, mode, data)
```

**3. Add protocol event handling**:
```python
# SOOTHE: Add new handler
async def _handle_protocol_event(self, event: dict):
    """Render Soothe protocol events."""
    event_type = event.get("type", "")

    if event_type.startswith("soothe.plan."):
        self.plan_widget.update(event)
    elif event_type.startswith("soothe.context."):
        self.status_bar.show_protocol_event(event)
    elif event_type.startswith("soothe.memory."):
        self.status_bar.show_protocol_event(event)
```

---

## Section 3: Protocol Event Rendering

### Soothe Protocol Events (RFC-500)

**Events to render**:
- `soothe.thread.started/ended` - Thread lifecycle
- `soothe.context.projected/ingested` - Context operations
- `soothe.memory.recalled/stored` - Memory operations
- `soothe.plan.created/step_started/completed/failed` - Plan execution
- `soothe.goal.batch_started/report` - Goal progress (autopilot)
- `soothe.policy.checked/denied` - Policy enforcement

### Rendering Strategy

**1. ProtocolEventWidget** (new file: `src/soothe/ux/tui/widgets/protocol_event.py`):

```python
"""Widget for rendering Soothe protocol events."""

class ProtocolEventWidget(Widget):
    """Compact one-liner indicator for protocol events.

    Display: Icon + brief message + status
    Similar to: tool call indicators in deepagents
    """

    def render_event(self, event: dict):
        """Render a protocol event as compact indicator."""
        event_type = event.get("type", "")

        # Map event types to icons/colors
        if event_type.startswith("soothe.plan."):
            return self._render_plan_event(event)
        elif event_type.startswith("soothe.context."):
            return self._render_context_event(event)
        elif event_type.startswith("soothe.memory."):
            return self._render_memory_event(event)
        elif event_type.startswith("soothe.policy."):
            return self._render_policy_event(event)

    def _render_plan_event(self, event):
        """Plan events: show step progress."""
        if "step_started" in event["type"]:
            step_desc = event.get("description", "Step")
            return f"📋 [cyan]Starting:[/cyan] {step_desc}"
        elif "step_completed" in event["type"]:
            return f"✅ [green]Completed[/green]"
        elif "created" in event["type"]:
            goal = event.get("goal", "Plan")
            return f"📋 [bold]Plan created[/bold]: {goal}"

    def _render_context_event(self, event):
        """Context events: show projection/ingestion."""
        if "projected" in event["type"]:
            entries = event.get("entries", 0)
            tokens = event.get("tokens", 0)
            return f"🔍 [magenta]Context[/magenta]: {entries} entries ({tokens} tokens)"

    def _render_memory_event(self, event):
        """Memory events: show recall/store."""
        if "recalled" in event["type"]:
            count = event.get("count", 0)
            return f"💭 [yellow]Memory[/yellow]: recalled {count} items"
```

**2. Integration into StatusBar** (modify `widgets/status.py`):

```python
# SOOTHE: Add protocol event display

class StatusBar(Widget):
    """Status bar showing activity.

    deepagents original: shows tool calls, loading, model info
    SOOTHE addition: shows protocol events too
    """

    # Add protocol event queue
    self._protocol_events: deque[dict] = deque(maxlen=5)

    def show_protocol_event(self, event: dict):
        """Queue a protocol event for display."""
        self._protocol_events.append(event)
        self._update_display()

    def _render_activity(self):
        """Render last 5 activity lines.

        Includes: tool calls + protocol events
        """
        lines = []

        # Tool calls (deepagents original)
        for tool_call in self._recent_tool_calls[-3:]:
            lines.append(self._render_tool_call(tool_call))

        # SOOTHE: Protocol events
        for event in self._protocol_events[-2:]:
            widget = ProtocolEventWidget()
            lines.append(widget.render_event(event))

        return "\n".join(lines)
```

**3. Plan Tree Widget** (keep Soothe's existing, integrate into deepagents layout):

```python
# In app.py compose():
def compose(self) -> ComposeResult:
    """Compose the TUI layout.

    deepagents original: messages + input + status
    SOOTHE addition: plan tree panel (collapsible)
    """
    yield ConversationPanel()  # deepagents message display
    yield PlanTree(id="plan-tree")  # SOOTHE: plan visualization
    yield ChatInput()  # deepagents advanced input
    yield StatusBar()  # deepagents status + protocol events
```

**PlanTree integration**:
- Receives `soothe.plan.*` events via app event bus
- Renders hierarchical plan structure
- Toggleable with Ctrl+T (preserves Soothe shortcut)
- Auto-shows when plan created, hides when inactive

**4. Verbosity Filtering** (RFC-501):

```python
# In SootheBackendAdapter._adapt_protocol_event():

def _adapt_protocol_event(self, event: dict):
    """Filter protocol events based on verbosity."""
    verbosity = self.config.verbosity

    # Quiet: suppress all protocol events
    if verbosity == "quiet":
        return None

    # Minimal: show only plan steps
    if verbosity == "minimal":
        if not event["type"].startswith("soothe.plan"):
            return None

    # Normal: show plan + context + memory
    if verbosity == "normal":
        if event["type"].startswith("soothe.policy"):
            return None  # Policy too detailed for normal

    # Detailed: show all protocol events
    return event
```

---

## Section 4: Thread Management Integration

### Thread Backend Bridge

**Create**: `src/soothe/ux/tui/thread_backend_bridge.py`

```python
"""Bridge between deepagents thread_selector UI and Soothe backends."""

class ThreadBackendBridge:
    """Provides thread data to deepagents thread_selector widget.

    Mimics: deepagents session/thread API
    Uses: Soothe ThreadContextManager backend
    """

    def __init__(self, thread_manager: ThreadContextManager):
        self.thread_manager = thread_manager

    async def list_threads_for_ui(self):
        """List threads in format deepagents thread_selector expects."""
        threads = await self.thread_manager.list_threads()

        return [
            {
                "id": t.id,
                "created_at": t.created_at,
                "updated_at": t.last_activity,
                "message_count": len(t.messages),
                "preview": t.messages[0].content[:100] if t.messages else "",
                "tags": t.tags or [],
                # SOOTHE: additional metadata
                "has_plan": t.has_active_plan,
                "status": t.status,  # running, completed, archived
            }
            for t in threads
        ]

    async def load_thread_messages(self, thread_id: str):
        """Load thread messages in deepagents message format."""
        thread_data = await self.thread_manager.load_thread(thread_id)

        messages = []
        for msg in thread_data.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "has_protocol_events": len(msg.protocol_events) > 0,
            })

        return messages

    async def resume_thread(self, thread_id: str):
        """Resume thread - tell daemon to load it."""
        await self.daemon_client.send_command({
            "type": "resume_thread",
            "thread_id": thread_id,
        })

        response = await self.daemon_client.receive_response()

        if response.get("status") == "success":
            return {"thread_id": thread_id, "status": "resumed"}
        else:
            raise ThreadResumeError(response.get("error"))
```

### Integration into thread_selector.py

```python
# SOOTHE: Replace backend connection

# deepagents original:
# threads = await self.session_manager.list_threads()

# SOOTHE: Use bridge instead
self.thread_bridge = ThreadBackendBridge(self.thread_manager)
threads = await self.thread_bridge.list_threads_for_ui()

# Rest of thread_selector UI logic unchanged
```

### Thread Metadata Display

**Soothe additions** to thread_selector rendering:
- Thread status badge (running/completed/archived)
- Plan indicator (show if thread has active plan)
- Tags display
- Protocol event count indicator

```python
# SOOTHE: Add to thread_selector rendering

def _render_thread_row(self, thread: dict) -> Panel:
    """Render single thread row."""
    row_text = f"{thread['id'][:8]} | {thread['preview']}"

    # SOOTHE: Add indicators
    indicators = []

    if thread.get("has_plan"):
        indicators.append("📋")

    if thread.get("status") == "running":
        indicators.append("▶️")

    if thread.get("tags"):
        indicators.append(f"🏷️ {len(thread['tags'])}")

    if indicators:
        row_text += " " + " ".join(indicators)

    return Panel(row_text, subtitle=f"{thread['message_count']} messages")
```

### Thread Commands Integration

**deepagents thread_selector actions**:
- Resume thread (enter)
- Delete thread (d)
- View messages (v)

**Soothe additional actions**:
- Archive thread (a)
- Export thread (e)
- Edit tags (t)

```python
# SOOTHE: Extend thread_selector key bindings

KEY_BINDINGS = {
    "enter": "resume_thread",  # deepagents original
    "d": "delete_thread",      # deepagents original
    "v": "view_messages",      # deepagents original
    # SOOTHE additions:
    "a": "archive_thread",
    "e": "export_thread",
    "t": "edit_tags",
}
```

---

## Section 5: Autopilot Dashboard Integration

### Keep Autopilot Screen, Integrate into deepagents App

```python
# In app.py modifications:

from soothe.ux.tui.autopilot_screen import AutopilotScreen

class SootheApp(App):  # Modified from deepagents App

    # SOOTHE: Add autopilot mode flag
    self._autopilot_mode: bool = False

    def on_mount(self):
        """App initialization.

        deepagents original: load default chat screen
        SOOTHE addition: check for autopilot mode flag
        """
        if self._autopilot_mode:
            # Launch autopilot dashboard instead of chat
            self.push_screen(AutopilotScreen())
        else:
            # Normal chat mode
            self.push_screen(ChatScreen())

    def action_switch_to_autopilot(self):
        """Switch from chat to autopilot."""
        self.push_screen(AutopilotScreen())

    def action_switch_to_chat(self):
        """Switch from autopilot back to chat."""
        self.pop_screen()
```

### Autopilot Dashboard Adaptation

**Modify**: `autopilot_screen.py` to use deepagents widgets where applicable

```python
"""Autopilot dashboard screen - RFC-203.

Uses: deepagents status bar, message display
Adds: Soothe-specific goal progress widgets
"""

from textual.screen import Screen

# SOOTHE: Import deepagents widgets for reuse
from soothe.ux.tui.widgets.status import StatusBar
from soothe.ux.tui.widgets.loading import LoadingWidget

# Keep Soothe-specific autopilot widgets
from soothe.ux.tui.autopilot_dashboard import (
    GoalProgressWidget,
    PlanTreeWidget,
    ExecutionQueueWidget,
)

class AutopilotScreen(Screen):
    """Autopilot dashboard with goal execution visualization."""

    def compose(self):
        yield GoalProgressWidget(id="goal-progress")
        yield PlanTreeWidget(id="plan-tree")
        yield ExecutionQueueWidget(id="execution-queue")
        yield StatusBar(id="status")  # SOOTHE: reuse deepagents
```

### Autopilot-Specific Events

**Autopilot mode receives different events**:
- `soothe.goal.batch_started` - Multiple goals queued
- `soothe.goal.report` - Goal execution report
- `soothe.executor.queue_updated` - Execution queue status

```python
# In SootheBackendAdapter:

async def stream_autopilot_events(self):
    """Stream autopilot-specific events."""
    async for namespace, mode, data in self.daemon_client.receive_events():
        event_type = data.get("type", "")

        if event_type.startswith("soothe.goal"):
            yield ("autopilot", "goal_update", data)
        elif event_type.startswith("soothe.executor"):
            yield ("autopilot", "queue_update", data)
```

### Screen Switching Flow

```
User launches with --autopilot flag
    ↓
app.py on_mount checks self._autopilot_mode = True
    ↓
Push AutopilotScreen (instead of ChatScreen)
    ↓
AutopilotScreen connects via SootheBackendAdapter
    ↓
Stream autopilot events (goal/plan/queue)
    ↓
Dashboard widgets update
    ↓
User presses Escape → pop_screen() → back to chat
```

### CLI Flag Integration

```python
# In src/soothe/ux/cli/main.py:

@app.command()
def autopilot(
    task: str,
    ctx: typer.Context,
):
    """Run autonomous goal execution mode."""
    self._autopilot_mode = True
    run_tui(config=cfg, autopilot_mode=True, initial_prompt=task)
```

```python
# In launcher.py:

def run_tui(
    cfg: SootheConfig,
    *,
    autopilot_mode: bool = False,  # SOOTHE: new flag
    thread_id: str | None = None,
    initial_prompt: str | None = None,
):
    """Launch TUI with mode selection."""
    from soothe.ux.tui import SootheApp

    app = SootheApp(
        config=cfg,
        autopilot_mode=autopilot_mode,
        thread_id=thread_id,
        initial_prompt=initial_prompt,
    )
    app.run()
```

---

## Section 6: CLI Command Structure Preservation

### CLI Entry Point (unchanged)

```python
# src/soothe/ux/cli/main.py - keep Typer structure

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: str | None = None,
    prompt: str | None = None,
    no_tui: bool = False,
    verbosity: str | None = None,
):
    """Soothe - Intelligent AI assistant.

    Default: Launches TUI (deepagents-based)
    With --prompt: Headless single-shot mode
    With --no-tui: Stream to stdout (no TUI)
    """
    cfg = SootheConfig.load(config)

    if no_tui or prompt:
        run_headless(cfg, prompt=prompt)
    else:
        # SOOTHE: Launch deepagents-based TUI
        run_tui(cfg)
```

### Daemon Commands (unchanged)

```python
# src/soothe/ux/cli/commands/daemon_cmd.py - keep entirely

@app.command("daemon")
def daemon_cmd(
    action: str,  # start/stop/status/restart
    foreground: bool = False,
):
    """Manage Soothe daemon lifecycle."""
    # Existing implementation unchanged
```

**Connection flow**:
1. `soothed start` → Daemon listens on WebSocket port 8765
2. `soothe` → TUI connects via DaemonClient
3. TUI receives events, displays using deepagents widgets

### Thread Commands (unchanged CLI, enhanced UI)

```python
# src/soothe/ux/cli/commands/thread_cmd.py

@app.command("thread")
def thread_cmd(
    action: str,  # list/show/continue/archive/delete/export/stats/tag
    thread_id: str | None = None,
):
    """Manage conversation threads.

    CLI: Typer commands unchanged
    UI: 'thread list' can launch interactive thread selector
    """
    if action == "list":
        if sys.stdout.isatty():
            launch_thread_selector_tui()  # deepagents thread_selector
        else:
            print_thread_list()  # Plain text
```

**Enhanced thread list UI**:

```python
def launch_thread_selector_tui():
    """Launch deepagents thread_selector as standalone TUI."""
    from soothe.ux.tui.widgets.thread_selector import ThreadSelectorScreen

    app = ThreadSelectorApp(
        thread_bridge=ThreadBackendBridge(thread_manager),
    )
    app.run()
```

### Configuration/Health/Status Commands (unchanged)

```python
# src/soothe/ux/cli/commands/config_cmd.py - keep entirely
# src/soothe/ux/cli/commands/health_cmd.py - keep entirely
# src/soothe/ux/cli/commands/status_cmd.py - keep entirely
```

### Slash Commands in TUI

**deepagents slash commands**:
- `/help`, `/exit`, `/quit`, `/clear`, `/resume`, `/agents`, `/skills`

**Soothe additions**:

```python
# In app.py modifications:

# SOOTHE: Register additional slash commands
self.command_registry.register("/plan", self.action_show_plan)
self.command_registry.register("/memory", self.action_show_memory)
self.command_registry.register("/context", self.action_show_context)
self.command_registry.register("/policy", self.action_show_policy)
self.command_registry.register("/detach", self.action_detach)
```

**Command actions**:

```python
def action_show_plan(self):
    """Show current plan tree."""
    self.plan_widget.toggle_visibility()

def action_show_memory(self):
    """Show memory stats."""
    stats = await self.backend_adapter.get_memory_stats()
    # Display stats in modal

def action_detach(self):
    """Detach TUI, leave daemon running."""
    if self.confirm_detach():
        self.exit(leave_daemon_running=True)
```

---

## Modification Strategy

### All Modifications Marked

**Comment style**: `# SOOTHE: ...`

**Three modification categories**:

1. **Backend replacement** (~5 locations in app.py):
   - Replace `create_agent()` → `SootheBackendAdapter()`
   - Replace `agent.astream()` → `adapter.stream_messages()`
   - Replace `session_manager` → `ThreadBackendBridge()`

2. **Protocol integration** (~3 additions):
   - Add `ProtocolEventWidget` import and usage
   - Add `_handle_protocol_event()` method
   - Modify `StatusBar` to include protocol queue

3. **Feature additions** (~10 additions):
   - Autopilot screen integration
   - Plan tree toggle (Ctrl+T)
   - Slash commands: `/plan`, `/memory`, `/context`, `/policy`, `/detach`
   - Thread actions: archive, export, tags
   - Autopilot mode flag in launcher

---

## Implementation Phases

### Phase 1: File Copy (Day 1)

**Actions**:
1. Copy 25-30 files from `/Users/xiamingchen/Workspace/mirasurf/deepagents/libs/cli/deepagents_cli/`
2. Delete 7 old Soothe TUI files
3. Keep autopilot files
4. Update `__init__.py` imports

**Verification**:
- All files copied successfully
- Imports resolve correctly
- No syntax errors

### Phase 2: Backend Integration (Day 2-3)

**Actions**:
1. Create `soothe_backend_adapter.py`
2. Create `thread_backend_bridge.py`
3. Modify `app.py` backend connections (5 locations)
4. Test daemon streaming

**Verification**:
- TUI launches without errors
- Daemon connection works
- Event stream received

### Phase 3: Protocol Rendering (Day 3-4)

**Actions**:
1. Create `widgets/protocol_event.py`
2. Modify `widgets/status.py` to add protocol queue
3. Add `_handle_protocol_event()` to app.py
4. Integrate plan tree widget
5. Test protocol event visualization

**Verification**:
- Protocol events render correctly
- Verbosity filtering works
- Plan tree toggles properly

### Phase 4: Feature Integration (Day 4-5)

**Actions**:
1. Integrate autopilot screen
2. Add Soothe slash commands
3. Add thread actions (archive, export, tags)
4. Thread selector bridge complete
5. Test all features

**Verification**:
- Autopilot mode launches
- Thread resume works
- Slash commands functional
- All features operational

### Phase 5: Testing & Polish (Day 5-6)

**Actions**:
1. Run verification suite (`./scripts/verify_finally.sh`)
2. Fix lint errors
3. Add integration tests
4. Create IG documentation
5. Manual testing all workflows

**Verification**:
- All lint checks pass
- 900+ tests pass
- No regressions
- IG written

---

## Success Criteria

1. ✅ TUI launches with all deepagents widgets working
2. ✅ Thread resume UI connects to Soothe persistence
3. ✅ Protocol events render in status bar + plan tree
4. ✅ Autopilot dashboard works as alternate screen
5. ✅ All Soothe CLI commands unchanged
6. ✅ Verbosity filtering applied to protocol events
7. ✅ Daemon connection seamless (WebSocket streaming)
8. ✅ Verification suite passes (lint, 900+ tests)
9. ✅ Feature parity with deepagents TUI (autocomplete, approval, diff)
10. ✅ No regression in Soothe functionality

---

## Risks & Mitigations

### Risk 1: deepagents Assumptions Break

**Risk**: deepagents TUI assumes deepagents SDK runtime, may break with Soothe backend

**Mitigation**: SootheBackendAdapter mimics interface precisely
- Same stream format `(namespace, mode, data)`
- Same method signatures
- Event conversion happens internally

**Test**: Stream format compatibility tests

### Risk 2: Protocol Events Not Rendering

**Risk**: Protocol events may not display properly in deepagents widgets

**Mitigation**: ProtocolEventWidget follows deepagents patterns
- Same one-liner indicator style
- Same status bar integration
- Same event queue approach

**Test**: Visual protocol event display tests

### Risk 3: Thread Selector Incompatible

**Risk**: Thread selector may not work with Soothe persistence

**Mitigation**: ThreadBackendBridge converts metadata cleanly
- Maps thread fields precisely
- Preserves all metadata
- Handles missing fields gracefully

**Test**: Thread resume functionality tests

### Risk 4: Autopilot Screen Integration Issues

**Risk**: Autopilot screen may not integrate smoothly

**Mitigation**: Screen push/pop pattern from deepagents
- Same screen lifecycle
- Same event routing
- Same mode switching

**Test**: Autopilot mode launch and switch tests

### Risk 5: Breaking Existing Workflows

**Risk**: Migration may break existing Soothe user workflows

**Mitigation**: Keep all CLI commands identical
- Same subcommand structure
- Same flags and options
- Same behavior

**Test**: Full regression test suite

### Risk 6: Future deepagents Updates

**Risk**: Divergence from upstream makes future sync hard

**Mitigation**: Mark all modifications clearly
- `# SOOTHE: ...` comments
- Document fork point (version X.Y.Z)
- Keep original logic intact where possible
- Cherry-pick useful improvements selectively

**Plan**: Track deepagents releases, sync improvements manually

---

## Alternatives Considered

### Alternative 1: Keep Soothe's Custom TUI

**Pros**: No migration work, full control
**Cons**: ❌ Maintenance burden continues, ❌ Feature gap persists, ❌ Duplication with upstream

**Rejected**: Goal is to get better features, not avoid work

### Alternative 2: Fork deepagents-cli Entirely

**Pros**: Complete control, no integration work
**Cons**: ❌ Divergence from upstream, ❌ Lose improvements, ❌ Maintenance burden

**Rejected**: Creates larger long-term burden

### Alternative 3: Use deepagents-cli as Dependency

**Pros**: Stays aligned with upstream
**Cons**: ❌ Not designed as library, ❌ Hard to inject protocols, ❌ Tight coupling

**Rejected**: deepagents-cli lacks library-friendly interfaces

### Alternative 4: Extract Shared Widget Package

**Pros**: Reusable library, benefits both projects
**Cons**: ❌ Most upfront work, ❌ Requires upstream coordination, ❌ Delays features

**Rejected**: Overkill for immediate goal, too much investment

### Preferred: Full Copy & Deep Integration

**Why chosen**:
1. ✅ Immediate feature access (get all widgets now)
2. ✅ Full integration control (can tailor to Soothe precisely)
3. ✅ Manageable scope (clear copy/adapt/integrate/test sequence)
4. ✅ Acceptable divergence (deepagents is mature, selective sync possible)
5. ✅ Matches user's strategy choice

---

## References

- **RFC-000**: System Conceptual Design
- **RFC-400**: Daemon Communication Protocol
- **RFC-500**: CLI TUI Architecture (current)
- **RFC-501**: VerbosityTier Unification
- **RFC-203**: Autopilot Mode
- **RFC-600**: Plugin Extension System
- **RFC-402**: Unified Thread Management
- **deepagents-cli source**: `/Users/xiamingchen/Workspace/mirasurf/deepagents/libs/cli/`

---

**Next Step**: User reviews this draft, then proceed to Platonic Coding Phase 1 RFC formalization.
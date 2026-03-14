"""Rich-based terminal UI for Soothe (RFC-0003).

Consumes the deepagents-canonical ``(namespace, mode, data)`` stream from
``SootheRunner.astream()`` and renders real-time progress with Rich Live
display, plan tree, activity lines, and subagent tracking.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from rich.console import Console, Group
from rich.layout import Layout
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.spinner import Spinner
from rich.text import Text
from rich.tree import Tree

if TYPE_CHECKING:
    from soothe.core.runner import SootheRunner
    from soothe.cli.session import InputHistory, SessionLogger
    from soothe.protocols.planner import Plan

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LEN = 3
_MSG_PAIR_LEN = 2
_THINKING_ROTATE_SEC = 1.5
_ACTIVITY_MAX = 300
_ACTIVITY_DISPLAY = 10
_SUBAGENT_DISPLAY = 5
_ANSWER_LINE_WINDOW = 28
_CTRL_C_WINDOW_SEC = 2.0
_CTRL_C_EXIT_COUNT = 2

# ---------------------------------------------------------------------------
# Thinking text
# ---------------------------------------------------------------------------

THINKING_MESSAGES: dict[str, list[str]] = {
    "planning": ["Planning approach...", "Breaking down the task...", "Analyzing requirements..."],
    "executing": ["Working on task...", "Processing...", "Making progress..."],
    "reflecting": ["Reflecting on progress...", "Evaluating results..."],
    "finalizing": ["Preparing answer...", "Synthesizing results..."],
    "tool_use": ["Using tools...", "Calling tool...", "Fetching data..."],
    "default": ["Thinking..."],
}


class DynamicThinkingText:
    """Generates rotating thinking text by phase."""

    def __init__(self) -> None:  # noqa: D107
        self._phase = "default"
        self._index = 0
        self._last_update = time.time()

    def set_phase(self, phase: str) -> None:
        """Switch the thinking phase (resets rotation)."""
        if phase != self._phase:
            self._phase = phase
            self._index = 0
            self._last_update = time.time()

    def get_text(self) -> str:
        """Return the current rotating message."""
        now = time.time()
        if now - self._last_update >= _THINKING_ROTATE_SEC:
            msgs = THINKING_MESSAGES.get(self._phase, THINKING_MESSAGES["default"])
            self._index = (self._index + 1) % len(msgs)
            self._last_update = now
        msgs = THINKING_MESSAGES.get(self._phase, THINKING_MESSAGES["default"])
        return msgs[self._index]


# ---------------------------------------------------------------------------
# Plan rendering
# ---------------------------------------------------------------------------

_STATUS_MARKERS: dict[str, tuple[str, str]] = {
    "pending": ("[ ]", "dim"),
    "in_progress": ("[>]", "bold yellow"),
    "completed": ("[+]", "bold green"),
    "failed": ("[x]", "bold red"),
}


def render_plan_tree(plan: Plan, title: str | None = None) -> Tree:
    """Render a plan as a Rich Tree with status markers.

    Args:
        plan: The plan data model.
        title: Optional custom title.

    Returns:
        A ``rich.tree.Tree`` renderable.
    """
    label = title or f"Plan: {plan.goal}"
    tree = Tree(Text(label, style="bold cyan"))
    for step in plan.steps:
        marker, style = _STATUS_MARKERS.get(step.status, ("[ ]", "dim"))
        step_style = {"in_progress": "yellow", "completed": "green"}.get(step.status, "dim")
        line = Text.assemble(Text(marker, style=style), " ", Text(step.description, style=step_style))
        tree.add(line)
    return tree


# ---------------------------------------------------------------------------
# Subagent tracker
# ---------------------------------------------------------------------------


@dataclass
class _SubagentState:
    subagent_id: str
    status: str = "running"
    last_activity: str = ""


class SubagentTracker:
    """Tracks per-subagent progress for display."""

    def __init__(self) -> None:  # noqa: D107
        self._states: dict[str, _SubagentState] = {}

    def update_from_custom(self, namespace: tuple[str, ...], data: dict[str, Any]) -> None:
        """Update tracker from a subagent custom event."""
        sid = ":".join(namespace) if namespace else "unknown"
        if sid not in self._states:
            self._states[sid] = _SubagentState(subagent_id=sid)
        event_type = data.get("type", "")
        summary = str(data.get("topic", data.get("query", event_type)))[:60]
        self._states[sid].last_activity = summary

    def mark_done(self, sid: str) -> None:
        """Mark a subagent as done."""
        if sid in self._states:
            self._states[sid].status = "done"

    def render(self) -> list[Text]:
        """Return displayable status lines for active subagents."""
        lines: list[Text] = []
        for st in list(self._states.values())[-3:]:
            tag = st.subagent_id.split(":")[-1] if ":" in st.subagent_id else st.subagent_id
            if st.status == "done":
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "green"), ("done", "green")))
            else:
                activity = st.last_activity[:50] or "running..."
                lines.append(Text.assemble(("  ", ""), (f"[{tag}] ", "magenta"), (activity, "yellow")))
        return lines


# ---------------------------------------------------------------------------
# TUI display state
# ---------------------------------------------------------------------------


@dataclass
class TuiState:
    """Mutable state for the live display."""

    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[str | int, dict[str, Any]] = field(default_factory=dict)
    activity_lines: list[Text] = field(default_factory=list)
    current_plan: Plan | None = None
    subagent_tracker: SubagentTracker = field(default_factory=SubagentTracker)
    thinking_gen: DynamicThinkingText = field(default_factory=DynamicThinkingText)
    seen_message_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    thread_id: str = ""
    last_user_input: str = ""


# ---------------------------------------------------------------------------
# Activity line formatting
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _add_activity(state: TuiState, line: Text) -> None:
    state.activity_lines.append(line)
    if len(state.activity_lines) > _ACTIVITY_MAX:
        state.activity_lines = state.activity_lines[-_ACTIVITY_MAX:]


def _set_plan_step_status(
    state: TuiState,
    index: int,
    status: str,
) -> None:
    """Update a plan step status if the current plan exists."""
    if not state.current_plan:
        return
    if 0 <= index < len(state.current_plan.steps):
        state.current_plan.steps[index].status = status


# ---------------------------------------------------------------------------
# Stream handlers
# ---------------------------------------------------------------------------


def _handle_tool_call_block(block: dict[str, Any], state: TuiState) -> None:
    """Process a tool_call or tool_call_chunk content block."""
    chunk_name = block.get("name")
    chunk_id = block.get("id")
    chunk_index = block.get("index")

    buffer_key: str | int
    if chunk_index is not None:
        buffer_key = chunk_index
    elif chunk_id is not None:
        buffer_key = chunk_id
    else:
        buffer_key = f"unknown-{len(state.tool_call_buffers)}"

    if buffer_key not in state.tool_call_buffers:
        state.tool_call_buffers[buffer_key] = {"name": None, "id": None}
    if chunk_name:
        state.tool_call_buffers[buffer_key]["name"] = chunk_name
        _add_activity(state, Text.assemble(("  . ", "dim"), (f"Calling {chunk_name}", "blue")))
        state.thinking_gen.set_phase("tool_use")


def _handle_tool_result(msg: ToolMessage, state: TuiState) -> None:
    """Process a ToolMessage result."""
    tool_name = getattr(msg, "name", "tool")
    content = msg.content
    if isinstance(content, list) or not isinstance(content, str):
        content = str(content)
    brief = _truncate(content.replace("\n", " "), 80)
    _add_activity(
        state,
        Text.assemble(
            ("  > ", "dim green"),
            (tool_name, "green"),
            ("  ", ""),
            (brief, "dim"),
        ),
    )


def _handle_protocol_event(data: dict[str, Any], state: TuiState) -> None:
    """Render a soothe.* protocol custom event as an activity line."""
    etype = data.get("type", "")

    if etype == "soothe.context.projected":
        entries = data.get("entries", 0)
        tokens = data.get("tokens", 0)
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Context: {entries} entries, {tokens} tokens", "cyan"),
            ),
        )

    elif etype == "soothe.memory.recalled":
        count = data.get("count", 0)
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Memory: {count} items recalled", "cyan"),
            ),
        )

    elif etype == "soothe.plan.created":
        from soothe.protocols.planner import Plan, PlanStep

        steps_data = data.get("steps", [])
        try:
            steps = [
                PlanStep(
                    id=s.get("id", str(i)),
                    description=s.get("description", ""),
                    status=s.get("status", "pending"),
                )
                for i, s in enumerate(steps_data)
            ]
            state.current_plan = Plan(
                goal=data.get("goal", ""),
                steps=steps,
            )
        except Exception:
            logger.debug("Plan reconstruction failed", exc_info=True)
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Plan: {len(steps_data)} steps", "cyan"),
            ),
        )
        state.thinking_gen.set_phase("executing")

    elif etype == "soothe.plan.reflected":
        assessment = data.get("assessment", "")[:60]
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Reflected: {assessment}", "dim italic"),
            ),
        )

    elif etype == "soothe.plan.step_started":
        index = int(data.get("index", -1))
        description = data.get("description", "")
        _set_plan_step_status(state, index, "in_progress")
        _add_activity(
            state,
            Text.assemble(("  . ", "dim"), (f"Step {index + 1}: {description}", "yellow")),
        )

    elif etype == "soothe.plan.step_completed":
        index = int(data.get("index", -1))
        success = bool(data.get("success", False))
        _set_plan_step_status(state, index, "completed" if success else "failed")
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Step {index + 1}: {'done' if success else 'failed'}", "green" if success else "red"),
            ),
        )

    elif etype == "soothe.policy.checked":
        verdict = data.get("verdict", "?")
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Policy: {verdict}", "cyan" if verdict == "allow" else "bold red"),
            ),
        )

    elif etype == "soothe.policy.denied":
        reason = data.get("reason", "")
        _add_activity(
            state,
            Text.assemble(
                ("  ! ", "bold red"),
                (f"Denied: {reason}", "red"),
            ),
        )

    elif etype == "soothe.context.ingested":
        source = data.get("source", "")
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Ingested from {source}", "dim cyan"),
            ),
        )

    elif etype == "soothe.thread.created":
        tid = data.get("thread_id", "?")
        state.thread_id = tid
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Thread: {tid}", "dim"),
            ),
        )

    elif etype == "soothe.thread.resumed":
        tid = data.get("thread_id", "?")
        state.thread_id = tid
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Resumed thread: {tid}", "dim"),
            ),
        )

    elif etype == "soothe.thread.saved":
        tid = data.get("thread_id", state.thread_id or "?")
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Saved thread: {tid}", "dim cyan"),
            ),
        )

    elif etype == "soothe.session.started":
        state.thread_id = data.get("thread_id", state.thread_id)
        state.thinking_gen.set_phase("planning")

    elif etype == "soothe.session.ended":
        state.thinking_gen.set_phase("finalizing")

    elif etype == "soothe.memory.stored":
        memory_id = data.get("id", "?")
        _add_activity(
            state,
            Text.assemble(
                ("  . ", "dim"),
                (f"Stored memory: {memory_id}", "cyan"),
            ),
        )

    elif etype == "soothe.error":
        error = data.get("error", "unknown")
        _add_activity(state, Text.assemble(("  ! ", "bold red"), (error, "red")))
        state.errors.append(error)


def _handle_subagent_custom(
    namespace: tuple[str, ...],
    data: dict[str, Any],
    state: TuiState,
) -> None:
    """Render a subagent custom event as an activity line with type-specific detail."""
    state.subagent_tracker.update_from_custom(namespace, data)
    tag = namespace[-1] if namespace else "subagent"
    etype = data.get("type", "")

    if etype == "browser_step":
        step = data.get("step", "?")
        action = _truncate(str(data.get("action", "")), 50)
        url = _truncate(str(data.get("url", "")), 35)
        summary = f"Step {step}"
        if action:
            summary += f": {action}"
        if url:
            summary += f" @ {url}"
    elif etype.startswith("research_"):
        label = etype.replace("research_", "").replace("_", " ")
        query = data.get("query", data.get("topic", ""))
        summary = label
        if query:
            summary += f": {_truncate(str(query), 40)}"
    elif etype in ("claude_tool_use",):
        summary = f"Tool: {data.get('name', etype)}"
    elif etype in ("claude_text",):
        summary = f"Text: {_truncate(str(data.get('text', '')), 50)}"
    elif etype.startswith("soothe.skillify."):
        summary = etype.replace("soothe.skillify.", "").replace("_", " ")
        detail = data.get("skill", data.get("query", ""))
        if detail:
            summary += f": {_truncate(str(detail), 40)}"
    elif etype.startswith("soothe.weaver."):
        summary = etype.replace("soothe.weaver.", "").replace("_", " ")
        detail = data.get("agent_name", data.get("task", ""))
        if detail:
            summary += f": {_truncate(str(detail), 40)}"
    else:
        summary = etype.replace("_", " ")[:50]

    logger.info("Subagent event [%s]: %s  data=%s", tag, etype, data)
    _add_activity(
        state,
        Text.assemble(
            ("  ", ""),
            (f"[{tag}] ", "magenta"),
            (summary, "dim"),
        ),
    )


# ---------------------------------------------------------------------------
# Live display builder
# ---------------------------------------------------------------------------


def _render_answer_panel(state: TuiState) -> Panel:
    """Render the main conversation panel."""
    prompt_text = Text(state.last_user_input or "(awaiting input)", style="bold cyan")
    response_text = "".join(state.full_response)
    response_lines = response_text.splitlines() or ([response_text] if response_text else [])
    if len(response_lines) > _ANSWER_LINE_WINDOW:
        response_lines = ["...", *response_lines[-_ANSWER_LINE_WINDOW:]]
    response_preview = "\n".join(response_lines).strip()

    if response_preview:
        answer_body = Text(response_preview, style="white")
    else:
        answer_body = Text("Streaming response will appear here.", style="dim")

    content = Group(
        Text("User", style="bold cyan"),
        prompt_text,
        Text(""),
        Text("Assistant", style="bold green"),
        answer_body,
    )
    return Panel(content, title="Conversation", border_style="bright_blue")


def _render_activity_panel(state: TuiState) -> Panel:
    """Render the recent action history sidebar panel."""
    lines = state.activity_lines[-_ACTIVITY_DISPLAY:]
    content: Group | Text = Group(*lines) if lines else Text("No activity yet.", style="dim")
    return Panel(content, title="Recent Actions", border_style="cyan")


def _render_plan_panel(state: TuiState) -> Panel:
    """Render the current plan sidebar panel."""
    if not state.current_plan:
        return Panel(Text("No active plan.", style="dim"), title="Plan", border_style="cyan")
    return Panel(render_plan_tree(state.current_plan, title=state.current_plan.goal), title="Plan", border_style="cyan")


def _render_subagent_panel(state: TuiState) -> Panel:
    """Render compact subagent statuses."""
    lines = state.subagent_tracker.render()[-_SUBAGENT_DISPLAY:]
    content: Group | Text = Group(*lines) if lines else Text("No active subagents.", style="dim")
    return Panel(content, title="Subagents", border_style="magenta")


def _render_status_panel(state: TuiState) -> Panel:
    """Render the bottom status/footer panel."""
    activity_count = str(len(state.activity_lines))
    error_count = str(len(state.errors))
    status_line = Text.assemble(
        ("Thread ", "dim"),
        (state.thread_id or "-", "bold cyan"),
        ("   ", ""),
        ("Events ", "dim"),
        (activity_count, "cyan"),
        ("   ", ""),
        ("Errors ", "dim"),
        (error_count, "red" if state.errors else "green"),
    )
    footer = Group(
        status_line,
        Spinner("dots", text=state.thinking_gen.get_text(), style="cyan"),
    )
    return Panel(footer, border_style="bright_black")


def _build_display(state: TuiState) -> Layout:
    """Assemble the live-updating layout."""
    layout = Layout(name="root")
    layout.split_column(Layout(name="body"), Layout(name="footer", size=4))
    layout["body"].split_row(Layout(name="conversation", ratio=3), Layout(name="sidebar", ratio=2))
    layout["sidebar"].split_column(
        Layout(name="plan", ratio=3),
        Layout(name="subagents", ratio=2),
        Layout(name="activity", ratio=4),
    )

    layout["conversation"].update(_render_answer_panel(state))
    layout["plan"].update(_render_plan_panel(state))
    layout["subagents"].update(_render_subagent_panel(state))
    layout["activity"].update(_render_activity_panel(state))
    layout["footer"].update(_render_status_panel(state))
    return layout


# ---------------------------------------------------------------------------
# Query processing
# ---------------------------------------------------------------------------


async def _process_query(
    runner: SootheRunner,
    user_input: str,
    console: Console,
    *,
    thread_id: str | None = None,
    session_logger: SessionLogger | None = None,
) -> Plan | None:
    """Process a single user query with Live display.

    Args:
        runner: The SootheRunner instance.
        user_input: User's query.
        console: Rich console.
        thread_id: Thread ID for persistence.
        session_logger: Optional session logger.

    Returns:
        The plan if one was created, else ``None``.
    """
    from rich.live import Live

    state = TuiState(last_user_input=user_input, thread_id=thread_id or runner.current_thread_id or "")
    user_input_logged = False

    with Live(_build_display(state), console=console, refresh_per_second=8, transient=True) as live:
        async for chunk in runner.astream(user_input, thread_id=thread_id):
            if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LEN:
                continue

            namespace, mode, data = chunk
            is_main = not namespace

            if session_logger and isinstance(data, dict):
                maybe_thread_id = data.get("thread_id")
                if isinstance(maybe_thread_id, str) and maybe_thread_id:
                    session_logger.set_thread_id(maybe_thread_id)
                    state.thread_id = maybe_thread_id
                if not user_input_logged and data.get("type") == "soothe.session.started":
                    session_logger.log_user_input(user_input)
                    user_input_logged = True

            if session_logger:
                session_logger.log(namespace, mode, data)

            if mode == "messages" and is_main:
                if not isinstance(data, tuple) or len(data) != _MSG_PAIR_LEN:
                    continue
                msg, metadata = data
                if metadata and metadata.get("lc_source") == "summarization":
                    continue
                if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
                    msg_id = msg.id or ""
                    # Complete (non-chunk) messages duplicate the streaming chunks
                    if not isinstance(msg, AIMessageChunk):
                        if msg_id in state.seen_message_ids:
                            continue
                        state.seen_message_ids.add(msg_id)
                    elif msg_id:
                        state.seen_message_ids.add(msg_id)
                    for block in msg.content_blocks:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            if text:
                                state.full_response.append(text)
                        elif btype in ("tool_call_chunk", "tool_call"):
                            _handle_tool_call_block(block, state)
                elif isinstance(msg, ToolMessage):
                    _handle_tool_result(msg, state)

            elif mode == "custom":
                if isinstance(data, dict):
                    if data.get("type", "").startswith("soothe."):
                        _handle_protocol_event(data, state)
                    elif not is_main:
                        _handle_subagent_custom(namespace, data, state)

            live.update(_build_display(state))

    # Post-Live: render final answer
    response_text = "".join(state.full_response)
    if session_logger:
        if not user_input_logged:
            session_logger.log_user_input(user_input)
        session_logger.log_assistant_response(response_text)
    if response_text:
        console.print(Rule(style="dim"))
        console.print(Markdown(response_text))
        console.print()

    if state.errors:
        for err in state.errors:
            console.print(Text(f"  ! {err}", style="bold red"))
        console.print()

    return state.current_plan


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


def _read_multiline(first: str, continuation_fn: Any) -> str:
    """Handle backslash-continued multi-line input."""
    if not first.endswith("\\"):
        return first

    lines = [first[:-1]]
    while True:
        try:
            cont = continuation_fn()
        except (EOFError, KeyboardInterrupt):
            break
        if cont.endswith("\\"):
            lines.append(cont[:-1])
        else:
            lines.append(cont)
            break
    return "\n".join(lines)


def read_user_input(
    console: Console,
    *,
    history: InputHistory | None = None,
) -> str | None:
    """Read user input with optional prompt_toolkit history.

    Returns ``None`` on EOF/interrupt.

    Args:
        console: Rich console.
        history: Optional input history for prompt_toolkit.
    """
    prompt_str = "soothe> "
    rich_prompt = "[bold cyan]soothe>[/bold cyan] "
    result: str | None = None

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.styles import Style

        style = Style.from_dict({"prompt": "bold cyan"})
        ptk_history = InMemoryHistory()
        if history:
            for entry in history.history:
                ptk_history.append_string(entry)

        session = PromptSession(history=ptk_history)
        try:
            first = session.prompt([("class:prompt", prompt_str)], style=style)
        except (EOFError, KeyboardInterrupt):
            return None

        result = _read_multiline(first, lambda: session.prompt("...  ", style=style))
        if history and result.strip():
            history.add(result)

    except ImportError:
        try:
            first = Prompt.ask(rich_prompt, console=console, show_default=False)
        except (EOFError, KeyboardInterrupt):
            return None

        result = _read_multiline(
            first,
            lambda: Prompt.ask("[dim]...[/dim]  ", console=console, show_default=False),
        )
        if history and result.strip():
            history.add(result)

    return result


# ---------------------------------------------------------------------------
# Main TUI loop
# ---------------------------------------------------------------------------


def run_agent_tui(runner: SootheRunner) -> None:
    """Launch the interactive Rich TUI for Soothe.

    Args:
        runner: The SootheRunner instance.
    """
    from soothe.cli.commands import handle_slash_command
    from soothe.cli.session import InputHistory, SessionLogger

    console = Console()
    current_plan: Plan | None = None
    ctrl_c_count = 0
    last_ctrl_c_time = 0.0

    session_logger = SessionLogger()
    input_history = InputHistory()

    protocols = runner.protocol_summary()
    proto_line = "  ".join(f"{k}={v}" for k, v in protocols.items() if v != "none")

    console.print(
        Panel(
            (
                "[bold]Soothe[/bold] -- Protocol-Driven Orchestration Agent\n"
                "[bold cyan]/help[/bold cyan]  [bold cyan]/exit[/bold cyan]\n"
                + (f"Protocols: [dim]{proto_line}[/dim]" if proto_line else "")
            ),
            border_style="bright_blue",
        )
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            user_input = read_user_input(console, history=input_history)
            if user_input is None:
                now = time.time()
                if now - last_ctrl_c_time < _CTRL_C_WINDOW_SEC:
                    ctrl_c_count += 1
                else:
                    ctrl_c_count = 1
                last_ctrl_c_time = now
                if ctrl_c_count >= _CTRL_C_EXIT_COUNT:
                    console.print("\n[bold red]Exiting...[/bold red]")
                    break
                console.print("\n[yellow]Press Ctrl+C again to exit.[/yellow]")
                continue

            ctrl_c_count = 0
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                should_exit = handle_slash_command(
                    user_input,
                    runner,
                    console,
                    current_plan=current_plan,
                    session_logger=session_logger,
                    input_history=input_history,
                )
                if should_exit:
                    break
                continue

            console.print()

            thread_id = runner.current_thread_id
            session_logger.set_thread_id(thread_id or "default")

            try:
                task = loop.create_task(
                    _process_query(
                        runner,
                        user_input,
                        console,
                        thread_id=thread_id,
                        session_logger=session_logger,
                    )
                )
                current_plan = loop.run_until_complete(task)
            except KeyboardInterrupt:
                console.print("\n[yellow]Task cancelled.[/yellow]")
                last_ctrl_c_time = time.time()
                ctrl_c_count = 1
            except asyncio.CancelledError:
                console.print("\n[yellow]Task cancelled.[/yellow]")
            except Exception as exc:
                console.print(Text(f"  ! {exc}", style="bold red"))
    finally:
        loop.close()

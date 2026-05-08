"""SootheApp: main Textual application class, composed from mixin modules."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from langgraph.pregel import Pregel
    from textual.app import ComposeResult
    from textual.worker import Worker

    from soothe_cli.tui.skills.load import ExtendedSkillMetadata
    from soothe_cli.tui.textual_adapter import TextualUIAdapter
    from soothe_cli.tui.widgets.approval import ApprovalMenu
    from soothe_cli.tui.widgets.ask_user import AskUserMenu

from textual.app import App
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from soothe_cli.tui import theme
from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.app._commands import _CommandsMixin
from soothe_cli.tui.app._execution import _ExecutionMixin
from soothe_cli.tui.app._history import _HistoryMixin
from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.app._model import _ModelMixin
from soothe_cli.tui.app._module_init import (
    DeferredAction,
    QueuedMessage,
    TextualSessionState,
    _load_theme_preference,
)
from soothe_cli.tui.app._startup import _StartupMixin
from soothe_cli.tui.app._ui import _UIMixin
from soothe_cli.tui.widgets.chat_input import ChatInput
from soothe_cli.tui.widgets.loading import LoadingWidget
from soothe_cli.tui.widgets.message_store import MessageStore
from soothe_cli.tui.widgets.messages import (
    QueuedUserMessage,
)
from soothe_cli.tui.widgets.status import StatusBar
from soothe_cli.tui.widgets.welcome import WelcomeBanner

logger = logging.getLogger(__name__)
_monotonic = time.monotonic

InputMode = (
    "normal"  # Literal type alias — actual value used in _module_init; here for isinstance guards
)


class SootheApp(
    App,
    _StartupMixin,
    _HistoryMixin,
    _CommandsMixin,
    _ModelMixin,
    _ExecutionMixin,
    _UIMixin,
    _MessagesMixin,
):
    """Main Textual application for Soothe.

    SOOTHE: Migrated from Soothe, now connects to Soothe daemon backend.
    """

    TITLE = "Soothe"  # SOOTHE: Changed title
    """Textual application title."""

    CSS_PATH = "app.tcss"
    """Path to the Textual CSS stylesheet for the app layout."""

    ENABLE_COMMAND_PALETTE = False
    """Disable Textual's built-in command palette in favor of the custom slash
    command system."""

    SCROLL_SENSITIVITY_Y = 1.0
    """Vertical scroll speed (reduced from Textual default for finer control)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "interrupt", "Interrupt", show=False, priority=True),
        Binding(
            "ctrl+c",
            "quit_or_interrupt",
            "Quit/Interrupt",
            show=False,
            priority=True,
        ),
        Binding("ctrl+d", "quit_app", "Quit", show=False, priority=True),
        Binding("ctrl+t", "toggle_auto_approve", "Toggle Auto-Approve", show=False),
        Binding(
            "shift+tab",
            "toggle_auto_approve",
            "Toggle Auto-Approve",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+o",
            "toggle_tool_output",
            "Toggle Tool Output",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+x",
            "open_editor",
            "Open Editor",
            show=False,
            priority=True,
        ),
        # Approval menu keys (handled at App level for reliability)
        Binding("up", "approval_up", "Up", show=False),
        Binding("k", "approval_up", "Up", show=False),
        Binding("down", "approval_down", "Down", show=False),
        Binding("j", "approval_down", "Down", show=False),
        Binding("enter", "approval_select", "Select", show=False),
        Binding("y", "approval_yes", "Yes", show=False),
        Binding("1", "approval_yes", "Yes", show=False),
        Binding("2", "approval_auto", "Auto", show=False),
        Binding("a", "approval_auto", "Auto", show=False),
        Binding("3", "approval_no", "No", show=False),
        Binding("n", "approval_no", "No", show=False),
    ]
    """App-level keybindings for interrupt, quit, toggles, and approval menu
    navigation."""

    class ServerReady(Message):
        """Posted by the background server-startup worker on success."""

        def __init__(  # noqa: D107
            self,
            agent: Any,  # noqa: ANN401
            server_proc: Any,  # noqa: ANN401
            mcp_server_info: list[Any] | None,
        ) -> None:
            super().__init__()
            self.agent = agent
            self.server_proc = server_proc
            self.mcp_server_info = mcp_server_info

    class ServerStartFailed(Message):
        """Posted by the background server-startup worker on failure."""

        def __init__(self, error: Exception) -> None:  # noqa: D107
            super().__init__()
            self.error = error

    class DaemonReady(Message):
        """Posted by the background daemon-connect worker on success."""

        def __init__(self, session: Any, status_event: dict[str, Any]) -> None:  # noqa: D107, ANN401
            super().__init__()
            self.session = session
            self.status_event = status_event

    def __init__(
        self,
        *,
        agent: Pregel | None = None,
        assistant_id: str | None = None,
        auto_approve: bool = False,
        cwd: str | Path | None = None,
        thread_id: str | None = None,
        resume_thread: str | None = None,
        initial_prompt: str | None = None,
        initial_skill: str | None = None,
        mcp_server_info: list[dict[str, Any]] | None = None,
        profile_override: dict[str, Any] | None = None,
        server_proc: Any | None = None,
        server_kwargs: dict[str, Any] | None = None,
        mcp_preload_kwargs: dict[str, Any] | None = None,
        model_kwargs: dict[str, Any] | None = None,
        daemon_config: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Deep Agents application.

        Args:
            agent: Pre-configured LangGraph agent, or `None` when server
                startup is deferred via `server_kwargs`.
            assistant_id: Agent identifier for memory storage
            auto_approve: Whether to start with auto-approve enabled
            cwd: Current working directory to display
            thread_id: Thread ID for the session.

                `None` when `resume_thread` is provided (resolved asynchronously).
            resume_thread: Raw resume intent from `-r` flag.

                `'__MOST_RECENT__'` for bare `-r`, a thread ID string for
                `-r <id>`, or `None` for new sessions.

                Resolved via `_resolve_resume_thread`
                during `_start_server_background`.

                Requires `server_kwargs` to be set; ignored otherwise.
            initial_prompt: Optional prompt to auto-submit when session starts
            initial_skill: Optional skill name to invoke when session starts.
            mcp_server_info: MCP server metadata for the `/mcp` viewer.
            profile_override: Extra profile fields from `--profile-override`,
                retained so later profile-aware behavior stays consistent with
                the CLI override, including model selection details and
                on-demand `create_model()` calls.
            server_proc: LangGraph server process for the interactive session.
            server_kwargs: When provided, server startup is deferred.

                The app shows a "Connecting..." state and starts the server in
                the background using these kwargs
                for `start_server_and_get_agent`.
            mcp_preload_kwargs: Kwargs for `_preload_session_mcp_server_info`,
                run concurrently with server startup when `server_kwargs` is set.
            model_kwargs: Kwargs for deferred `create_model()`.

                When provided, model creation runs in a background worker after
                first paint instead of blocking startup.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)

        self._register_custom_themes()

        # Apply saved theme preference (or default)
        self.theme = _load_theme_preference()

        self._agent = agent

        self._assistant_id = assistant_id

        self._auto_approve = auto_approve

        self._cwd = str(cwd) if cwd else str(Path.cwd())

        self._lc_loop_id = thread_id
        """LangChain loop identifier (thread_id in langgraph internals).

        Named `_lc_loop_id` to reflect RFC-503 loop-first UX while avoiding
        collision with Textual's `App._thread_id`.
        """

        self._resume_thread_intent = resume_thread

        self._initial_prompt = initial_prompt

        self._initial_skill = (
            initial_skill.strip().lower() if initial_skill and initial_skill.strip() else None
        )

        self._mcp_server_info = mcp_server_info

        self._profile_override = profile_override

        self._server_proc = server_proc

        self._server_kwargs = server_kwargs

        self._mcp_preload_kwargs = mcp_preload_kwargs

        self._model_kwargs = model_kwargs

        self._daemon_config = daemon_config

        self._daemon_session: Any | None = None

        self._daemon_skills_wire: list[dict[str, Any]] = []
        """Cached ``skills_list_response`` rows when the TUI uses ``TuiDaemonSession``."""

        self._connecting = server_kwargs is not None or daemon_config is not None
        # Extract sandbox type from server kwargs for trace metadata.
        # ServerConfig.__post_init__ normalizes "none" → None, but server_kwargs carries
        # the raw argparse value, so guard against both.

        raw = (server_kwargs or {}).get("sandbox_type")

        self._sandbox_type: str | None = raw if raw and raw != "none" else None

        self._model_override: str | None = None

        self._model_params_override: dict[str, Any] | None = None

        self._mcp_tool_count = sum(len(s.tools) for s in (mcp_server_info or []))

        self._status_bar: StatusBar | None = None

        self._chat_input: ChatInput | None = None

        self._quit_pending = False

        self._session_state: TextualSessionState | None = None

        self._ui_adapter: TextualUIAdapter | None = None

        self._pending_approval_widget: ApprovalMenu | None = None

        self._pending_ask_user_widget: AskUserMenu | None = None
        # Agent task tracking for interruption

        self._agent_worker: Worker[None] | None = None

        self._agent_running = False

        self._server_startup_error: str | None = None
        """Set when the background server fails to start; persists for the
        session lifetime (server failure is terminal).

        Shown in place of the generic 'Agent not configured' message.
        """

        self._shell_process: asyncio.subprocess.Process | None = None
        """Shell command process tracking for interruption (! commands)."""

        self._shell_worker: Worker[None] | None = None

        self._shell_running = False

        self._loading_widget: LoadingWidget | None = None

        self._context_tokens: int = 0
        """Local cache of the last total-context token count.

        Source of truth is `_context_tokens` in graph state; this is a sync
        copy for the status bar.
        """

        self._tokens_approximate: bool = False
        """Whether the cached token count is stale (interrupted generation)."""

        self._last_typed_at: float | None = None
        """Typing-aware approval deferral state."""

        self._approval_placeholder: Static | None = None

        self._update_available: tuple[bool, str | None] = (False, None)
        """Update availability state — set by _check_for_updates, read on exit."""

        self._session_stats: SessionStats = SessionStats()
        """Cumulative usage stats across all turns in this session."""

        self._inflight_turn_stats: SessionStats | None = None
        """Stats for the currently executing turn.

        Held here so `exit()` can merge them synchronously before the event loop
        tears down (e.g. `Ctrl+D` during a pending tool call).
        """

        self._inflight_turn_start: float = 0.0
        """Monotonic timestamp when the current turn started."""

        self._pending_messages: deque[QueuedMessage] = deque()
        """User message queue for sequential processing."""

        self._queued_widgets: deque[QueuedUserMessage] = deque()

        self._processing_pending = False

        self._thread_switching = False

        self._model_switching = False
        self._detaching = False

        self._deferred_actions: list[DeferredAction] = []
        """Deferred actions executed after the current busy state resolves."""

        self._message_store = MessageStore()
        """Message virtualization store."""

        self._startup_task: asyncio.Task[None] | None = None
        """Startup task reference (set in on_mount)."""

        self._discovered_skills: list[ExtendedSkillMetadata] = []
        """Cached skill metadata from daemon RPC (populated by startup
        discovery worker, refreshed on `/reload`).
        """

        # Lazily imported here to avoid pulling image dependencies into
        # argument parsing paths.
        from soothe_cli.tui.input import MediaTracker

        self._image_tracker = MediaTracker()

    def _remote_agent(self) -> Any:  # noqa: ANN401
        """Return the agent if it appears to be a remote agent, or `None`.

        Returns `None` when no agent is configured or the agent is a local graph.
        """
        # RemoteAgent module doesn't exist in this package; always return None.
        # When the SDK provides a RemoteAgent class, this can be re-implemented.
        return None

    def _runtime_backend_ready(self) -> bool:
        """Return whether the app has a usable execution backend."""
        return self._daemon_session is not None or self._agent is not None

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Return custom CSS variable defaults for the current theme.

        Most styling uses Textual's built-in variables (`$primary`,
        `$text-muted`, `$error-muted`, etc.).  This override injects the
        app-specific variables (`$mode-bash`, `$mode-command`, `$skill`,
        `$skill-hover`, `$tool`, `$tool-hover`, `$cognition`, `$cognition-hover`)
        that have no Textual equivalent.

        Returns:
            Dict of CSS variable names to hex color values.
        """
        colors = theme.get_theme_colors(self)
        return theme.get_css_variable_defaults(colors=colors)

    def compose(self) -> ComposeResult:
        """Compose the application layout.

        Yields:
            UI components for the main chat area and status bar.
        """
        # Main chat area with scrollable messages
        # VerticalScroll tracks user scroll intent for better auto-scroll behavior
        with VerticalScroll(id="chat"):
            with Vertical(id="chat-body"):
                yield WelcomeBanner(
                    thread_id=self._lc_loop_id,
                    mcp_tool_count=self._mcp_tool_count,
                    connecting=self._connecting,
                    resuming=self._resume_thread_intent is not None,
                    local_server=self._server_kwargs is not None,
                    id="welcome-banner",
                )
                yield Container(id="messages")
        with Container(id="bottom-app-container"):
            yield Container(id="thinking-status")
            yield ChatInput(
                cwd=self._cwd,
                image_tracker=self._image_tracker,
                id="input-area",
            )

        # Status bar at bottom
        yield StatusBar(cwd=self._cwd, id="status-bar")

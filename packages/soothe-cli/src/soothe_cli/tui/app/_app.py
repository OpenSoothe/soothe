"""SootheApp: main Textual application class, composed from mixin modules."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.worker import Worker

    from soothe_cli.tui.skills.load import ExtendedSkillMetadata
    from soothe_cli.tui.textual_adapter import TextualUIAdapter

from textual.app import App
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui import theme
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
    AssistantMessage,
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
        Binding(
            "shift+tab",
            "shift_tab",
            "Previous filter",
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
        Binding(
            "ctrl+y",
            "copy_selection",
            "Copy Selection",
            show=False,
        ),
    ]
    """App-level keybindings for interrupt, quit, and navigation."""

    class ServerStartFailed(Message):
        """Posted when daemon bootstrap or background connection fails."""

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
        daemon_config: Any,
        assistant_id: str | None = None,
        cwd: str | Path | None = None,
        resume_loop_id: str | None = None,
        initial_prompt: str | None = None,
        initial_skill: str | None = None,
        mcp_server_info: list[dict[str, Any]] | None = None,
        profile_override: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Textual application (daemon-backed execution only).

        Args:
            daemon_config: Loaded Soothe configuration (WebSocket URL, etc.).
            assistant_id: Agent identifier for memory storage.
            cwd: Current working directory to display.
            resume_loop_id: Initial StrangeLoop id when attaching to an existing loop.
            initial_prompt: Optional prompt to auto-submit when session starts.
            initial_skill: Optional skill name to invoke when session starts.
            mcp_server_info: MCP server metadata for the `/mcp` viewer.
            profile_override: Extra profile fields from ``--profile-override``.
            **kwargs: Additional arguments passed to the Textual ``App``.
        """
        super().__init__(**kwargs)

        self._register_custom_themes()

        # Apply saved theme preference (or default)
        self.theme = _load_theme_preference()

        self._assistant_id = assistant_id

        self._cwd = str(cwd) if cwd else str(Path.cwd())

        # Active StrangeLoop id; LangGraph stores it as configurable.thread_id.
        # Named `_lc_loop_id` to avoid colliding with Textual's App._thread_id.
        self._lc_loop_id = resume_loop_id
        self._loop_autopilot_mode: str = "solo"

        self._initial_prompt = initial_prompt

        self._initial_skill = (
            initial_skill.strip().lower() if initial_skill and initial_skill.strip() else None
        )

        self._mcp_server_info = mcp_server_info

        self._profile_override = profile_override

        self._daemon_config = daemon_config

        self._daemon_session: Any | None = None

        self._daemon_skills_wire: list[dict[str, Any]] = []
        """Cached ``skills_list_response`` rows when the TUI uses ``TuiDaemonSession``."""

        self._connecting = True

        self._sandbox_type: str | None = None

        self._model_override: str | None = None

        self._model_params_override: dict[str, Any] | None = None

        # RFC-622: clarification relay mode. Seeded from --mode flag (CLIConfig);
        # default to Auto so loops keep moving when the user hasn't opted in.
        self._clarification_mode: str = getattr(daemon_config, "clarification_mode", None) or "auto"

        self._mcp_tool_count = sum(len(s.tools) for s in (mcp_server_info or []))

        self._status_bar: StatusBar | None = None

        self._chat_input: ChatInput | None = None

        self._quit_pending = False

        self._session_state: TextualSessionState | None = None

        self._ui_adapter: TextualUIAdapter | None = None

        # Agent task tracking for interruption
        self._agent_worker: Worker[None] | None = None

        self._agent_running = False

        self._bg_event_worker: Worker[None] | None = None
        """Background daemon event consumer worker (cancelled on active turn start)."""

        self._server_startup_error: str | None = None
        """Set when daemon bootstrap fails; persists for the session lifetime."""

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

        self._loop_switching = False

        self._model_switching = False
        self._detaching = False

        self._deferred_actions: list[DeferredAction] = []
        """Deferred actions executed after the current busy state resolves."""

        self._message_store = MessageStore()
        """Message virtualization store."""

        self._hydrate_scheduled = False
        """Whether a hydrate task has been queued via `call_later`."""

        self._hydrate_in_progress = False
        """Whether `_hydrate_messages_above` is currently running."""

        self._last_hydration_check_mono: float = 0.0
        """Monotonic timestamp of the last scroll-triggered hydration check."""

        self._deferred_assistant_renders: deque[tuple[AssistantMessage, str]] = deque()
        """Queue of hydrated assistant cards pending markdown render."""

        self._assistant_render_drain_scheduled = False
        """Whether assistant render-drain has been scheduled."""

        self._assistant_render_drain_in_progress = False
        """Whether assistant render-drain is currently active."""

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

    def _runtime_backend_ready(self) -> bool:
        """Return whether the app has a connected daemon session."""
        return self._daemon_session is not None

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
                    loop_id=self._lc_loop_id,
                    mcp_tool_count=self._mcp_tool_count,
                    workspace_path=self._cwd,
                    connecting=self._connecting,
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
            yield StatusBar(cwd=self._cwd, id="status-bar")

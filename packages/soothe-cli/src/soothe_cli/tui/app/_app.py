"""SootheApp: main Textual application class, composed from mixin modules."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer
    from textual.worker import Worker

    from soothe_cli.tui.skills.load import ExtendedSkillMetadata
    from soothe_cli.tui.textual_adapter import TextualUIAdapter

from textual.app import App
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message

from soothe_cli.runtime.state.session_stats import SessionStats
from soothe_cli.tui import theme
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
from soothe_cli.tui.composer_mode import normalize_composer_mode
from soothe_cli.tui.tips import TipRotator
from soothe_cli.tui.widgets.chat_input import ChatInput
from soothe_cli.tui.widgets.loading import LoadingWidget
from soothe_cli.tui.widgets.message_store import MessageStore
from soothe_cli.tui.widgets.messages import (
    AssistantMessage,
    QueuedUserMessage,
)
from soothe_cli.tui.widgets.plan_quick_view_overlay import PlanQuickViewOverlay
from soothe_cli.tui.widgets.status import StatusBar
from soothe_cli.tui.widgets.welcome import WelcomeBanner

logger = logging.getLogger(__name__)
_monotonic = time.monotonic


class SootheApp(
    App,
    _StartupMixin,
    _HistoryMixin,
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
        Binding("escape", "dismiss_ui", "Dismiss", show=False, priority=True),
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
        Binding(
            "ctrl+t",
            "toggle_plan_quick_view",
            "Plan View",
            show=False,
            priority=True,
        ),
    ]
    """App-level keybindings for dismiss, quit, and navigation."""

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

        self._preloaded_model_data: (
            tuple[list[tuple[str, str]], str | None, dict[str, dict[str, Any]]] | None
        ) = None
        """Cached ``/model`` selector data from startup ``models_list`` prewarm."""

        self._wire_credential_map: dict[str, bool | None] | None = None
        """Provider credential flags paired with ``_preloaded_model_data``."""

        self._connecting = True

        self._sandbox_type: str | None = None

        self._model_override: str | None = None

        self._model_params_override: dict[str, Any] | None = None

        self._router_profile_override: str | None = None

        # Composer mode (Auto / Manual / Plan). Seeded from --mode (CLIConfig);
        # default Auto so loops keep moving when the user hasn't opted in.
        self._composer_mode: str = normalize_composer_mode(
            getattr(daemon_config, "clarification_mode", None)
        )

        self._mcp_tool_count = sum(len(s.tools) for s in (mcp_server_info or []))

        self._status_bar: StatusBar | None = None
        self._default_session_tip: str = ""
        self._status_notification_timer: Timer | None = None
        self._status_notification_active = False
        # Rotating tip source + interval timer for the status footer.
        self._tip_rotator: TipRotator = TipRotator()
        self._tip_rotation_timer: Timer | None = None

        self._chat_input: ChatInput | None = None
        self._plan_quick_view_overlay: PlanQuickViewOverlay | None = None

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

        self._connect_spinner_start_mono: float | None = None
        """Monotonic anchor for startup daemon-connect elapsed time in the thinking row."""

        self._loop_token_scope_id: str | None = None
        """Loop id that ``_loop_*_tokens`` counters belong to."""

        self._loop_baseline_tokens: int = 0
        """Persisted loop usage total loaded from checkpoint (resume baseline)."""

        self._loop_input_tokens: int = 0
        """Input tokens for the in-flight goal/turn (stream or backend)."""

        self._loop_output_tokens: int = 0
        """Output tokens for the in-flight goal/turn (stream or backend)."""

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
        self._shutdown_prepared = False

        self._deferred_actions: list[DeferredAction] = []
        """Deferred actions executed after the current busy state resolves."""

        self._message_store = MessageStore()
        """Message virtualization store."""

        self._loop_history_load_lock = asyncio.Lock()
        """Serialize resume history loads to prevent duplicate widget mounts."""

        self._loop_history_loaded_for: str | None = None
        """Loop id whose transcript was last painted by ``_load_loop_history``."""

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

    def exit(
        self,
        result: Any = None,
        return_code: int = 0,
        message: Any = None,
    ) -> None:
        """Exit with Soothe shutdown prep.

        ``App.exit`` appears before ``_MessagesMixin`` in the MRO, so this
        delegate ensures custom teardown (worker cancel, stats merge, iTerm2
        restore) runs for every quit path.
        """
        _MessagesMixin.exit(self, result=result, return_code=return_code, message=message)

    def _runtime_backend_ready(self) -> bool:
        """Return whether the app has a connected daemon session."""
        return self._daemon_session is not None

    def set_default_session_tip(self, tip: str) -> None:
        """Persist and render the fallback tip shown when no notification is active."""
        cleaned = (tip or "").strip()
        self._default_session_tip = cleaned
        if self._status_bar is not None and not self._status_notification_active:
            self._status_bar.set_session_tip(cleaned)

    def start_tip_rotation(self, interval: float = 12.0) -> None:
        """Cycle through rotating tips in the status footer at a fixed interval.

        Args:
            interval: Seconds between tip rotations.
        """
        self.stop_tip_rotation()
        self._tip_rotation_timer = self.set_interval(interval, self._rotate_session_tip)

    def stop_tip_rotation(self) -> None:
        """Cancel the rotating-tip interval timer if one is running."""
        if self._tip_rotation_timer is not None:
            with suppress(Exception):
                self._tip_rotation_timer.stop()
            self._tip_rotation_timer = None

    def _rotate_session_tip(self) -> None:
        """Advance to the next tip and push it to the status footer.

        Transient notifications take precedence: rotation is skipped while a
        notification is active so it can run its timeout uninterrupted.
        """
        if self._status_notification_active:
            return
        self.set_default_session_tip(self._tip_rotator.next_tip())

    def _set_status_notification(self, message: str, *, timeout: float | None = None) -> None:
        """Render a transient notification in the status-tip area."""
        text = (message or "").strip()
        if not text:
            return
        if self._status_notification_timer is not None:
            with suppress(Exception):
                self._status_notification_timer.stop()
            self._status_notification_timer = None
        self._status_notification_active = True
        if self._status_bar is not None:
            self._status_bar.set_notification_message(text)

        duration = timeout if timeout and timeout > 0 else 3.0
        self._status_notification_timer = self.set_timer(duration, self._clear_status_notification)

    def _clear_status_notification(self) -> None:
        """Restore the default tip after transient notification timeout."""
        self._status_notification_timer = None
        self._status_notification_active = False
        if self._status_bar is not None:
            self._status_bar.set_session_tip(self._default_session_tip)

    def notify(  # type: ignore[override]
        self,
        message: Any,
        *,
        title: str = "",
        severity: str = "information",
        timeout: float | None = None,
        markup: bool = True,  # noqa: ARG002
    ) -> None:
        """Display notifications in the status-tip area instead of toast bubbles."""
        text = str(message or "").strip()
        if not text:
            return
        if title:
            text = f"{title}: {text}"
        if severity and severity.lower() in {"warning", "error"}:
            text = f"{severity.title()}: {text}"
        self._set_status_notification(text, timeout=timeout)

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Return custom CSS variable defaults for the current theme.

        Most styling uses Textual's built-in variables (`$primary`,
        `$text-muted`, `$error-muted`, etc.).  This override injects the
        app-specific variables (`$mode-bash`, `$mode-command`, `$cognition`)
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
                    id="welcome-banner",
                )
                yield Container(id="messages")
        # In-flow plan panel: sits above the sticky bottom chrome so Ctrl+t
        # never covers the thinking row or chat input. Auto-shows when a plan
        # is active if CLIConfig.plan_panel_default_visible is True.
        plan_visible = getattr(self._daemon_config, "plan_panel_default_visible", False)
        yield PlanQuickViewOverlay(
            id="plan-quick-view-overlay",
            default_visible=plan_visible,
        )
        with Container(id="bottom-app-container"):
            yield Container(id="thinking-status")
            yield ChatInput(
                cwd=self._cwd,
                image_tracker=self._image_tracker,
                id="input-area",
            )
            yield StatusBar(cwd=self._cwd, id="status-bar")

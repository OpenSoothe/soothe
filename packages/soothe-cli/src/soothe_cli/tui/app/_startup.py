"""Startup, server/daemon workers, skills, prewarm, and update check mixin."""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import platform
import sys
from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_cli.tui.app._app import DaemonReady, ServerStartFailed
    from soothe_cli.tui.skills.load import ExtendedSkillMetadata

from textual.containers import VerticalScroll
from textual.css.query import NoMatches

from soothe_cli.tui._version import CHANGELOG_URL
from soothe_cli.tui.app._module_init import (
    TextualSessionState,
)
from soothe_cli.tui.widgets.chat_input import ChatInput
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    ErrorMessage,
    SkillMessage,
    UserMessage,
)
from soothe_cli.tui.widgets.status import StatusBar
from soothe_cli.tui.widgets.welcome import WelcomeBanner

logger = logging.getLogger(__name__)

# Cold-start: daemon may bind WebSocket ~30s after PID file (CoreAgent pool warmup).
_DAEMON_READY_TIMEOUT_S = 60.0
_DAEMON_CONNECT_MAX_ATTEMPTS = 3
_DAEMON_CONNECT_RETRY_DELAY_S = 2.0


class _StartupMixin:
    """Startup, server/daemon workers, skills discovery, prewarm and update methods."""

    @staticmethod
    def _env_flag(name: str) -> bool:
        """Return True when an env var contains a truthy value."""
        raw = os.environ.get(name, "")
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _should_dump_tui_debug_snapshot(self) -> bool:
        """Return True when CLI/TUI debug logging is enabled."""
        if self._env_flag("SOOTHE_TUI_DEBUG"):
            return True
        root_logger = logging.getLogger()
        return root_logger.isEnabledFor(logging.DEBUG) or logger.isEnabledFor(logging.DEBUG)

    def _dump_tui_debug_snapshot(self) -> None:
        """Emit one startup diagnostic snapshot for TUI/Textual troubleshooting."""
        if not self._should_dump_tui_debug_snapshot():
            return
        textual_version = "unknown"
        rich_version = "unknown"
        try:
            textual_version = version("textual")
        except PackageNotFoundError:
            pass
        try:
            rich_version = version("rich")
        except PackageNotFoundError:
            pass
        logger.info(
            "[TUI Debug] runtime python=%s platform=%s textual=%s rich=%s",
            platform.python_version(),
            platform.platform(),
            textual_version,
            rich_version,
        )
        logger.info(
            "[TUI Debug] terminal term=%r colorterm=%r term_program=%r shell=%r",
            os.environ.get("TERM", ""),
            os.environ.get("COLORTERM", ""),
            os.environ.get("TERM_PROGRAM", ""),
            os.environ.get("SHELL", ""),
        )
        logger.info(
            "[TUI Debug] gc enabled=%s count=%s threshold=%s frozen=%s",
            gc.isenabled(),
            gc.get_count(),
            gc.get_threshold(),
            hasattr(gc, "get_freeze_count") and gc.get_freeze_count() > 0,
        )
        logger.info(
            "[TUI Debug] tui window_size=%d hydrate_buffer=%d render_queue_len=%d",
            self._message_store.WINDOW_SIZE,
            self._message_store.HYDRATE_BUFFER,
            len(self._deferred_assistant_renders),
        )
        logger.info(
            "[TUI Debug] env SOOTHE_TUI_DEBUG=%r SOOTHE_LOG_LEVEL=%r argv0=%r",
            os.environ.get("SOOTHE_TUI_DEBUG", ""),
            os.environ.get("SOOTHE_LOG_LEVEL", ""),
            sys.argv[0] if sys.argv else "",
        )

    async def on_mount(self) -> None:
        """Initialize components after mount.

        Only widget queries and lightweight config go here — anything that
        would delay the first rendered frame (subprocess calls, heavy
        imports) is deferred to `_post_paint_init` via `call_after_refresh`.
        """
        # Move all objects allocated during import/compose into the permanent
        # generation so the cyclic GC skips them during first-paint rendering.
        import gc

        gc.freeze()

        chat = self.query_one("#chat", VerticalScroll)
        # Transcript scrolling is mouse-driven; keeping the region unfocusable
        # prevents clicks in the message area from stealing the chat prompt caret.
        chat.can_focus = False
        chat.anchor()

        self._status_bar = self.query_one("#status-bar", StatusBar)
        self._chat_input = self.query_one("#input-area", ChatInput)
        with suppress(NoMatches):
            from soothe_cli.tui.widgets.plan_quick_view_overlay import PlanQuickViewOverlay

            self._plan_quick_view_overlay = self.query_one(
                "#plan-quick-view-overlay",
                PlanQuickViewOverlay,
            )

        # Seed the badge from the app-level clarification mode (CLI flag, default Auto).
        self._status_bar.set_clarification_mode(self._clarification_mode)

        with suppress(NoMatches):
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            self._status_bar.set_session_tip(banner.session_tip)

        # Focus the input immediately so the cursor is visible on first paint
        self._chat_input.focus_input()

        # Start daemon connection immediately in background — this waits for the
        # daemon to become ready and should run concurrently with import prewarm
        # to avoid sequential delays when the daemon is freshly started.
        self.run_worker(
            self._connect_daemon_background,
            exclusive=True,
            group="daemon-connect",
        )

        # Run import prewarm off the UI thread. Post-paint init runs after prewarm
        # completes to ensure adapter construction doesn't cold-load heavy modules.
        self._startup_task = asyncio.create_task(self._run_deferred_startup())

    async def _run_deferred_startup(self) -> None:
        """Prewarm imports in a worker thread, then schedule post-paint workers.

        Daemon connection runs independently (started in on_mount) so it can
        proceed while prewarm loads heavy modules. Post-paint init is scheduled
        only after prewarm completes so its inline imports are cheap
        ``sys.modules`` lookups instead of cold loads on the UI thread.
        """
        try:
            await asyncio.to_thread(self._prewarm_deferred_imports)
        except Exception:
            logger.warning("Import prewarm failed", exc_info=True)

        # Always schedule post-paint init — even when prewarm fails, the app
        # must still start session state and related workers. Use a minimal
        # non-zero delay (0.001s) to avoid Textual's ZeroDivisionError with
        # set_timer(0), and wrap in asyncio.create_task since set_timer
        # expects a synchronous callable.
        self.set_timer(0.001, lambda: asyncio.create_task(self._post_paint_init()))

    async def _post_paint_init(self) -> None:
        """Fire background workers for remaining startup work.

        Everything here is non-blocking: workers and thread-offloaded calls
        so the UI stays responsive. Import prewarm must finish before this
        runs (see ``_run_deferred_startup``) so adapter construction does not
        cold-load langchain/runtime stacks on the Textual message loop.
        """
        # Create UI adapter unconditionally — it only holds UI callbacks.
        from soothe_cli.tui.textual_adapter import TextualUIAdapter

        self._ui_adapter = TextualUIAdapter(
            mount_message=self._mount_message,
            update_status=self._update_status,
            set_spinner=self._set_spinner,
            pause_spinner=self._pause_spinner,
            resume_spinner=self._resume_spinner,
            set_active_message=self._set_active_message,
            sync_message_content=self._sync_message_content,
        )

        # Wire token display callbacks
        self._ui_adapter._seed_loop_token_from_checkpoint = self._seed_loop_token_from_checkpoint
        self._ui_adapter._on_turn_tokens = self._record_loop_turn_tokens
        self._ui_adapter._get_loop_token_total = self._loop_token_total
        self._ui_adapter._on_refresh_token_displays = self._push_token_displays
        self._ui_adapter._apply_authoritative_loop_tokens = self._apply_authoritative_loop_tokens
        self._ui_adapter._on_tokens_hide = self._hide_tokens
        self._dump_tui_debug_snapshot()

        # Seed static slash commands now that the first frame has rendered.
        # Skill commands are appended later when _discover_skills() completes.
        self._apply_slash_command_autocomplete()

        # Fire-and-forget workers — none of these block the event loop.

        self.run_worker(self._init_session_state, exclusive=True, group="session-init")

        # Daemon connection is started directly in on_mount to run concurrently
        # with import prewarm — no need to start it again here.

        # Background update check and what's-new banner (on by default; opt-out via
        # SOOTHE_CLI_NO_UPDATE_CHECK or [update].check: false; SOOTHE_CLI_UPDATE_CHECK
        # forces on if config disables)
        from soothe_cli.tui.update_check import is_update_check_enabled

        if is_update_check_enabled():
            self.run_worker(
                self._check_for_updates,
                exclusive=True,
                group="startup-update-check",
            )
            self.run_worker(
                self._show_whats_new,
                exclusive=True,
                group="startup-whats-new",
            )

        # Model cache prewarm runs from ``on_soothe_app_daemon_ready`` once the
        # session exists — post-paint is too early (``_daemon_session`` is still None).

        # Auto-submit initial prompt or skill if provided via -m / --skill.
        # When connecting, defer until the ready message handler fires.
        if not self._connecting:
            self._schedule_initial_submission()

    async def _init_session_state(self) -> None:
        """Create session state in a thread (imports soothe.sessions)."""

        def _create() -> TextualSessionState:
            return TextualSessionState(loop_id=self._lc_loop_id)

        try:
            self._session_state = await asyncio.to_thread(_create)
        except Exception:
            logger.exception("Failed to create session state")
            self.notify(
                "Session initialization failed. Some features may be unavailable.",
                severity="error",
                timeout=10,
            )

    def _apply_slash_command_autocomplete(self) -> None:
        """Merge static slash commands with skill entries (daemon catalog or local)."""
        from soothe_cli.tui.command_registry import (
            SLASH_COMMANDS,
            build_skill_commands,
            build_skill_commands_from_wire,
        )

        merged: list[tuple[str, str, str]] = list(SLASH_COMMANDS)
        if self._daemon_session is not None and self._daemon_skills_wire:
            merged.extend(build_skill_commands_from_wire(self._daemon_skills_wire))
        elif self._discovered_skills:
            merged.extend(build_skill_commands(self._discovered_skills))
        if self._chat_input:
            self._chat_input.update_slash_commands(merged)

    async def _refresh_daemon_skills_catalog(self) -> None:
        """Fetch skills from the daemon and refresh slash autocomplete."""
        session = self._daemon_session
        if session is None:
            return
        try:
            rows = await session.list_skills()
        except Exception:
            logger.exception("Failed to fetch skills list from daemon")
            self.notify(
                "Could not load skill list from daemon. /skill: autocomplete may be incomplete.",
                severity="warning",
                timeout=8,
                markup=False,
            )
            return
        self._daemon_skills_wire = rows
        self._apply_slash_command_autocomplete()

    @staticmethod
    def _format_local_skills_catalog_text(skills: list[Any]) -> str:
        """Human-readable listing for bare ``/skill:`` in local (non-daemon) mode."""
        lines: list[str] = ["Available skills:\n"]
        for s in sorted(skills, key=lambda m: str(m.get("name", "")).lower()):
            name = str(s.get("name", ""))
            desc = str(s.get("description", "")).strip()
            lines.append(f"  • {name}: {desc}" if desc else f"  • {name}")
        lines.append("")
        lines.append("Usage: `/skill:<name> [args]`")
        return "\n".join(lines)

    @staticmethod
    def _format_daemon_skills_catalog_text(rows: list[dict[str, Any]]) -> str:
        """Human-readable listing for bare ``/skill:`` when backed by the daemon."""
        lines = ["Available skills (from daemon):\n"]
        for row in sorted(rows, key=lambda r: str(r.get("name", "")).lower()):
            name = str(row.get("name", ""))
            desc = str(row.get("description", "")).strip()
            lines.append(f"  • {name}: {desc}" if desc else f"  • {name}")
        lines.append("")
        lines.append("Usage: `/skill:<name> [args]`")
        return "\n".join(lines)

    async def _mount_bare_skill_list(self, command: str) -> None:
        """Show every known skill when the user submits ``/skill:`` with no name."""
        await self._mount_message(UserMessage(command))
        if self._daemon_session is not None:
            rows = self._daemon_skills_wire
            if not rows:
                try:
                    rows = await self._daemon_session.list_skills()
                    self._daemon_skills_wire = rows
                    self._apply_slash_command_autocomplete()
                except Exception as exc:
                    await self._mount_message(
                        AppMessage(f"Could not load skills from daemon: {exc}"),
                    )
                    return
            await self._mount_message(AppMessage(self._format_daemon_skills_catalog_text(rows)))
            return

        if not self._discovered_skills:
            try:
                skills = await self._discover_skills()
                self._discovered_skills = skills
                self._apply_slash_command_autocomplete()
            except Exception:
                logger.exception("Error fetching skills from daemon")
                await self._mount_message(
                    AppMessage("Could not list skills. Check logs for details.")
                )
                return

        if not self._discovered_skills:
            await self._mount_message(AppMessage("No skills found in configured skill paths."))
            return

        await self._mount_message(
            AppMessage(self._format_local_skills_catalog_text(self._discovered_skills))
        )

    async def _invoke_skill_daemon(self, command: str, skill_name: str, args: str) -> None:
        """Daemon path: RPC loads ``SKILL.md`` on the server; TUI only streams the turn."""
        if self._daemon_session is None:
            return
        if self._agent_running or self._shell_running:
            self.notify(
                "Wait for the current turn to finish before invoking a skill.",
                severity="warning",
                timeout=4,
            )
            return
        try:
            resp = await self._daemon_session.invoke_skill(
                skill_name,
                args,
                clarification_mode=getattr(self, "_clarification_mode", None),
            )
        except RuntimeError as exc:
            await self._mount_message(UserMessage(command))
            await self._mount_message(AppMessage(str(exc)))
            return
        except Exception as exc:
            logger.exception("invoke_skill RPC failed")
            await self._mount_message(UserMessage(command))
            await self._mount_message(AppMessage(f"Skill invocation failed: {exc}"))
            return

        echo = resp.get("echo")
        if not isinstance(echo, dict):
            await self._mount_message(UserMessage(command))
            await self._mount_message(
                AppMessage("Invalid invoke_skill_response from daemon (missing echo).")
            )
            return

        await self._mount_message(UserMessage(command))
        await self._mount_message(
            SkillMessage(
                skill_name=str(echo.get("skill_name", skill_name)),
                description=str(echo.get("description", "")),
                source=str(echo.get("source", "")),
                body=str(echo.get("body", "")),
                args=str(echo.get("args", args)),
            ),
        )
        await self._send_to_agent("", skip_daemon_send_turn=True)

    async def _discover_skills(self) -> list[ExtendedSkillMetadata]:
        """Discover skills from daemon via WebSocket RPC (IG-174 Phase 2).

        Fetches wire-safe skill metadata from daemon. No local filesystem
        access — all skill discovery and invocation handled by daemon.

        Returns:
            List of skill metadata dicts from daemon RPC.
        """
        from soothe_cli.tui.skills.invocation import discover_skills_async

        return await discover_skills_async(daemon_config=self._daemon_config)

    @staticmethod
    def _daemon_connect_hint_extra(*, attempt: int, max_attempts: int) -> str | None:
        """Hint suffix for daemon connect retries (label stays a single word)."""
        from soothe_cli.tui.spinner_labels import daemon_connect_hint_extra

        return daemon_connect_hint_extra(attempt=attempt, max_attempts=max_attempts)

    async def _connect_daemon_background(self) -> None:
        """Background worker: connect the TUI directly to the daemon."""
        from soothe_cli.tui.spinner_labels import SPINNER_LABEL_WAITING

        for attempt in range(1, _DAEMON_CONNECT_MAX_ATTEMPTS + 1):
            await self._set_spinner(
                SPINNER_LABEL_WAITING,
                show_interrupt_hint=False,
                hint_extra=self._daemon_connect_hint_extra(
                    attempt=attempt,
                    max_attempts=_DAEMON_CONNECT_MAX_ATTEMPTS,
                ),
            )
            try:
                session, status_event = await self._connect_daemon_once(attempt=attempt)
            except Exception as exc:
                if attempt < _DAEMON_CONNECT_MAX_ATTEMPTS:
                    logger.warning(
                        "Daemon connect attempt %d/%d failed: %s",
                        attempt,
                        _DAEMON_CONNECT_MAX_ATTEMPTS,
                        exc,
                    )
                    await asyncio.sleep(_DAEMON_CONNECT_RETRY_DELAY_S)
                    continue
                self.post_message(self.ServerStartFailed(error=exc))
                return

            self.post_message(self.DaemonReady(session=session, status_event=status_event))
            return

    async def _connect_daemon_once(
        self,
        *,
        attempt: int,
    ) -> tuple[Any, dict[str, Any]]:
        """Wait for daemon readiness and bootstrap one TUI session.

        Args:
            attempt: Current connect attempt (1-based).

        Returns:
            Tuple of ``(TuiDaemonSession, status_event)``.

        Raises:
            ConnectionError: If the daemon is not reachable or ready in time.
            Exception: If loop bootstrap fails.
        """
        from soothe_sdk.client import (
            is_daemon_live,
            websocket_url_from_config,
        )

        from soothe_cli.runtime.transport.session import TuiDaemonSession
        from soothe_cli.tui._env_vars import resolve_cli_loop_workspace
        from soothe_cli.tui.spinner_labels import SPINNER_LABEL_CONNECTING

        ws_url = websocket_url_from_config(self._daemon_config)

        # Check daemon status via WebSocket RPC (IG-174 Phase 1)
        # Wait for daemon to be fully ready, not just port-live (IG-489)
        daemon_live = await is_daemon_live(
            ws_url,
            timeout=5.0,
            wait_for_ready=True,
            ready_timeout=_DAEMON_READY_TIMEOUT_S,
        )

        if not daemon_live:
            # CLI does NOT control daemon start/stop per architectural separation (IG-174/IG-175)
            raise ConnectionError(
                f"Soothe daemon not running at {ws_url}. "
                f"Please start the daemon with: soothed start"
            )

        await self._set_spinner(
            SPINNER_LABEL_CONNECTING,
            show_interrupt_hint=False,
            hint_extra=self._daemon_connect_hint_extra(
                attempt=attempt,
                max_attempts=_DAEMON_CONNECT_MAX_ATTEMPTS,
            ),
        )

        session = TuiDaemonSession(
            self._daemon_config,
            workspace=resolve_cli_loop_workspace(),
            post_idle_drain_deadline=0.3,
        )
        status_event = await session.connect(resume_loop_id=self._lc_loop_id)
        return session, status_event

    def on_soothe_app_daemon_ready(self, event: DaemonReady) -> None:
        """Handle successful daemon bootstrap for the TUI."""
        self._connecting = False
        self.call_after_refresh(lambda: asyncio.create_task(self._set_spinner(None)))
        self._daemon_session = event.session

        status_loop_id = event.status_event.get("loop_id")
        if isinstance(status_loop_id, str) and status_loop_id:
            self._lc_loop_id = status_loop_id
            if self._session_state is not None:
                self._session_state.loop_id = status_loop_id

        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.set_connected(self._mcp_tool_count)
            if self._lc_loop_id:
                banner.update_loop_id(self._lc_loop_id)
            if self._status_bar is not None:
                self._status_bar.set_session_tip(banner.session_tip)
        except NoMatches:
            logger.warning("Welcome banner not found during daemon ready transition")

        # IG-228: Start background event reader if the loop is already running
        loop_state = event.status_event.get("state", "")
        if loop_state == "running" and self._daemon_session is not None:
            logger.info(
                "Loop %s is running, starting background event reader",
                status_loop_id[:8] if status_loop_id else "?",
            )
            self._bg_event_worker = self.run_worker(
                self._consume_daemon_events_background(),
                exclusive=False,
                group="daemon-event-reader",
            )

        # Resume sessions must load prior conversation regardless of whether a
        # startup prompt is also queued — see _post_mount for the rationale.
        if self._lc_loop_id:
            self.call_after_refresh(lambda: asyncio.create_task(self._load_loop_history()))
        self._schedule_initial_submission()

        if self._deferred_actions and not self._agent_running:

            async def _safe_drain() -> None:
                try:
                    await self._maybe_drain_deferred()
                except Exception:
                    logger.exception("Unhandled error while draining deferred actions")
                    with suppress(Exception):
                        await self._mount_message(
                            ErrorMessage(
                                "A deferred action failed during startup. You may need to retry the operation."
                            )
                        )

            self.call_after_refresh(lambda: asyncio.create_task(_safe_drain()))

        if self._pending_messages and not self._has_initial_submission():
            self.call_after_refresh(lambda: asyncio.create_task(self._process_next_from_queue()))

        self.run_worker(
            self._refresh_daemon_skills_catalog(),
            exclusive=True,
            group="daemon-skills-catalog",
        )

        self.run_worker(
            self._prewarm_model_caches,
            exclusive=True,
            group="startup-model-prewarm",
        )

    def on_soothe_app_server_start_failed(self, event: ServerStartFailed) -> None:
        """Handle daemon bootstrap / connection failure."""
        self._connecting = False
        self.call_after_refresh(lambda: asyncio.create_task(self._set_spinner(None)))
        self._server_startup_error = f"{type(event.error).__name__}: {event.error}"
        logger.error("Daemon connection failed: %s", event.error, exc_info=event.error)
        # Update banner to show persistent failure state
        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.set_failed(self._server_startup_error)
        except NoMatches:
            logger.warning("Welcome banner not found during server failure transition")

        # Discard any messages queued while connecting
        if self._pending_messages:
            self._pending_messages.clear()
            for w in self._queued_widgets:
                w.remove()
            self._queued_widgets.clear()
        self._deferred_actions.clear()

    @staticmethod
    def _prewarm_deferred_imports() -> None:
        """Background-load modules deferred from the startup path.

        Populates `sys.modules` so the first user-triggered inline import
        is a cheap dict lookup instead of a cold module load.
        """
        # Internal modules moved from top-level to local imports — a failure
        # here indicates a packaging or code bug, not a missing optional dep, so
        # we let the exception propagate (the worker catches it and logs
        # at WARNING). textual_adapter and update_check are included so
        # _post_paint_init's inline imports are dict lookups.
        from soothe_cli.tui.command_registry import ALWAYS_IMMEDIATE  # noqa: F401
        from soothe_cli.tui.config import settings  # noqa: F401
        from soothe_cli.tui.model_config import ModelSpec  # noqa: F401
        from soothe_cli.tui.textual_adapter import TextualUIAdapter  # noqa: F401
        from soothe_cli.tui.update_check import is_update_check_enabled  # noqa: F401
        from soothe_cli.tui.widgets.clipboard import (
            copy_selection_to_clipboard,  # noqa: F401
        )

        # First user message: ``execute_task_textual`` + CLI stream pipeline.
        # Warm on this thread so the asyncio loop does not stall on cold import.
        try:
            import importlib

            importlib.import_module("soothe_cli.tui.textual_adapter")
            importlib.import_module("soothe_cli.runtime.turn.prepare")
        except Exception:
            logger.warning("Could not prewarm first-turn execute path", exc_info=True)

        try:
            # Heavy third-party deps deferred from textual_adapter /
            # tool_display — hit on first message send and first tool
            # approval. Best-effort: missing optional deps should not block the
            # TUI from rendering.
            from langchain_core.messages import AIMessage  # noqa: F401
            from langgraph.types import Command  # noqa: F401
            from soothe_sdk.client.config import DEFAULT_EXECUTE_TIMEOUT  # noqa: F401
        except Exception:
            logger.warning("Could not prewarm third-party imports", exc_info=True)

        # Markdown rendering stack — ~170 ms cold (markdown_it, pygments,
        # linkify_it).  Hit on first AssistantMessage flush and first
        # SkillMessage expand.  Warming here makes the first render instant.
        import markdown_it  # noqa: F401
        from pygments.lexers import get_lexer_by_name as _get_lexer
        from rich.markdown import Markdown as _RichMarkdown  # noqa: F401

        # Instantiate the Python lexer to populate Pygments' internal
        # lexer cache (~12 ms cold).  Python is the most common fence
        # language in skill bodies.
        _get_lexer("python")

        # Widgets deferred from app.py module level — a failure here indicates
        # a packaging or code bug (same as the block above), so we let
        # exceptions propagate.
        from soothe_cli.tui.widgets.loop_selector import LoopSelectorScreen  # noqa: F401
        from soothe_cli.tui.widgets.model_selector import (
            ModelSelectorScreen,  # noqa: F401
        )

    async def _prewarm_model_caches(self) -> None:
        """Prewarm ``/model`` selector data via the connected daemon session."""
        session = self._daemon_session
        if session is None:
            logger.debug("Skipping model cache prewarm - daemon session not ready")
            return
        try:
            from soothe_cli.tui.model_config import parse_models_list_response

            resp = await session.list_models()
            all_models, default_spec, profiles, wire_creds = parse_models_list_response(resp)
            self._preloaded_model_data = (all_models, default_spec, profiles)
            self._wire_credential_map = wire_creds
        except Exception:
            logger.warning("Could not prewarm model caches", exc_info=True)

    async def _check_for_updates(self) -> None:
        """Check PyPI for a newer version and optionally auto-update."""
        # Phase 1: version check (benign failure)
        try:
            from soothe_cli.tui.update_check import (
                is_auto_update_enabled,
                is_update_available,
                upgrade_command,
            )

            available, latest = await asyncio.to_thread(is_update_available)
            if not available:
                return

            self._update_available = (True, latest)
            self.call_after_refresh(lambda v=latest: self._apply_welcome_update_notice(v))
        except Exception:
            logger.debug("Background update check failed", exc_info=True)
            return

        # Phase 2: optional auto-update (version notice lives on the welcome banner only)
        try:
            if is_auto_update_enabled():
                from soothe_cli.tui.update_check import perform_upgrade

                self.notify(
                    f"Updating to v{latest}...",
                    severity="information",
                    timeout=5,
                )
                success, _output = await perform_upgrade()
                if success:
                    self.notify(
                        f"Updated to v{latest}. Restart to use the new version.",
                        severity="information",
                        timeout=10,
                    )
                    self.call_after_refresh(lambda: self._apply_welcome_update_notice(None))
                else:
                    cmd = upgrade_command()
                    self.notify(
                        f"Auto-update failed. Run manually: {cmd}",
                        severity="warning",
                        timeout=15,
                        markup=False,
                    )
        except Exception:
            logger.warning("Auto-update failed unexpectedly", exc_info=True)
            self.notify(
                "Update failed unexpectedly.",
                severity="warning",
                timeout=10,
            )

    def _apply_welcome_update_notice(self, latest: str | None) -> None:
        """Show or hide the welcome-banner update line (must run on the UI thread)."""
        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.set_update_notice(latest)
        except NoMatches:
            logger.debug("Welcome banner not found while applying update notice")

    async def _show_whats_new(self) -> None:
        """Show a 'what's new' banner on the first launch after an upgrade."""
        try:
            from soothe_cli.tui.update_check import should_show_whats_new

            if not await asyncio.to_thread(should_show_whats_new):
                return
        except Exception:
            logger.debug("What's new check failed", exc_info=True)
            return

        try:
            from soothe_cli.tui._version import __version__ as cli_version
            from soothe_cli.tui.config import _is_editable_install

            if await asyncio.to_thread(_is_editable_install):
                heading = f"Now running v{cli_version}"
            else:
                heading = f"Updated to v{cli_version}"

            await self._mount_message(AppMessage(f"{heading}\nSee what's new: {CHANGELOG_URL}"))
        except Exception:
            logger.debug("What's new banner display failed", exc_info=True)
            return

        try:
            from soothe_cli.tui._version import __version__ as cli_version
            from soothe_cli.tui.update_check import mark_version_seen

            await asyncio.to_thread(mark_version_seen, cli_version)
        except Exception:
            logger.warning("Failed to persist seen-version marker", exc_info=True)

    async def _handle_update_command(self) -> None:
        """Handle the `/update` slash command — check for and install updates."""
        await self._mount_message(UserMessage("/update"))
        try:
            from soothe_cli.tui.update_check import (
                is_update_available,
                perform_upgrade,
                upgrade_command,
            )

            await self._mount_message(AppMessage("Checking for updates..."))
            available, latest = await asyncio.to_thread(is_update_available, bypass_cache=True)
            if not available:
                self._update_available = (False, None)
                self._apply_welcome_update_notice(None)
                await self._mount_message(AppMessage("Already on the latest version."))
                return

            from soothe_cli.tui._version import __version__ as cli_version

            self._update_available = (True, latest)
            self._apply_welcome_update_notice(latest)
            await self._mount_message(
                AppMessage(f"Update available: v{latest} (current: v{cli_version}). Upgrading...")
            )
            success, output = await perform_upgrade()
            if success:
                self._update_available = (False, None)
                self._apply_welcome_update_notice(None)
                await self._mount_message(
                    AppMessage(f"Updated to v{latest}. Restart to use the new version.")
                )
            else:
                cmd = upgrade_command()
                detail = f": {output[:200]}" if output else ""
                await self._mount_message(
                    AppMessage(f"Auto-update failed{detail}\nRun manually: {cmd}")
                )
        except Exception as exc:
            logger.warning("/update command failed", exc_info=True)
            await self._mount_message(ErrorMessage(f"Update failed: {type(exc).__name__}: {exc}"))

    async def _handle_auto_update_toggle(self) -> None:
        """Handle the `/auto-update` slash command — persist toggle immediately."""
        try:
            from soothe_cli.tui.config import _is_editable_install
            from soothe_cli.tui.update_check import (
                is_auto_update_enabled,
                set_auto_update,
            )

            if await asyncio.to_thread(_is_editable_install):
                self.notify(
                    "Auto-updates are not available for editable installs.",
                    severity="warning",
                    timeout=5,
                )
                return

            currently_enabled = await asyncio.to_thread(is_auto_update_enabled)
            new_state = not currently_enabled
            await asyncio.to_thread(set_auto_update, new_state)
            label = "enabled" if new_state else "disabled"
            self.notify(
                f"Auto-updates {label}.",
                severity="information",
                timeout=5,
                markup=False,
            )
        except Exception as exc:
            logger.warning("/auto-update command failed", exc_info=True)
            self.notify(
                f"Auto-update toggle failed: {type(exc).__name__}: {exc}",
                severity="warning",
                timeout=5,
                markup=False,
            )

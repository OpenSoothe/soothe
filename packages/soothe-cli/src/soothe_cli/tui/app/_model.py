"""Model switching, loop switching, and modal screen managers mixin."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from textual.app import ScreenStackError
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.theme import Theme

from soothe_cli.tui import theme
from soothe_cli.tui.app._module_init import (
    DeferredAction,
    save_theme_preference,
)
from soothe_cli.tui.widgets.messages import AppMessage, ErrorMessage
from soothe_cli.tui.widgets.welcome import WelcomeBanner

logger = logging.getLogger(__name__)


class _ModelMixin:
    """Model switching, loop switching, and modal screen managers."""

    async def _show_model_selector(
        self,
        *,
        extra_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Show interactive model selector as a modal screen.

        Args:
            extra_kwargs: Extra constructor kwargs from `--model-params`.
        """
        from functools import partial

        from soothe_cli.tui.config import settings
        from soothe_cli.tui.model_config import ModelSpec
        from soothe_cli.tui.widgets.model_selector import ModelSelectorScreen

        def handle_result(result: tuple[str, str] | None) -> None:
            """Handle the model selector result."""
            if result is not None:
                model_spec, _ = result
                if self._agent_running or self._shell_running or self._connecting:
                    self._defer_action(
                        DeferredAction(
                            kind="model_switch",
                            execute=partial(
                                self._switch_model,
                                model_spec,
                                extra_kwargs=extra_kwargs,
                            ),
                        )
                    )
                    self.notify("Model will switch after current task completes.", timeout=3)
                else:
                    self.call_later(
                        partial(
                            self._switch_model,
                            model_spec,
                            extra_kwargs=extra_kwargs,
                        )
                    )
            # Refocus input after modal closes
            if self._chat_input:
                self._chat_input.focus_input()

        cur_model = settings.model_name
        cur_provider = settings.model_provider
        if self._model_override:
            parsed_cur = ModelSpec.try_parse(self._model_override.strip())
            if parsed_cur:
                cur_provider, cur_model = parsed_cur.provider, parsed_cur.model
            else:
                cur_model = self._model_override.strip()
                cur_provider = cur_provider or ""

        preloaded: tuple[list[tuple[str, str]], str | None, dict[str, dict[str, Any]]] | None = None
        wire_creds: dict[str, bool | None] | None = None
        if self._daemon_session is not None:
            try:
                resp = await self._daemon_session.list_models()
            except Exception as exc:
                logger.exception("daemon list_models failed")
                await self._mount_message(ErrorMessage(f"Could not load models from daemon: {exc}"))
                return
            rows = resp.get("models") or []
            all_models: list[tuple[str, str]] = []
            wire_creds = {}
            for row in rows:
                if not isinstance(row, dict) or row.get("placeholder"):
                    continue
                spec = str(row.get("spec", "")).strip()
                prov = str(row.get("provider", "")).strip()
                if not spec or not prov:
                    continue
                all_models.append((spec, prov))
                if prov not in wire_creds and "has_credentials" in row:
                    wire_creds[prov] = row.get("has_credentials")
            dm = resp.get("default_model")
            default_spec = dm if isinstance(dm, str) and dm.strip() else None
            profiles = {spec: {"profile": {}, "overridden_keys": set()} for spec, _ in all_models}
            preloaded = (all_models, default_spec, profiles)
            if not all_models:
                await self._mount_message(
                    ErrorMessage(
                        "Daemon returned no models. Check providers and `models:` lists in the daemon host config.yml."
                    ),
                )
                return

        screen = ModelSelectorScreen(
            current_model=cur_model,
            current_provider=cur_provider,
            cli_profile_override=self._profile_override,
            preloaded=preloaded,
            wire_credential_map=wire_creds,
        )
        self.push_screen(screen, handle_result)

    def _register_custom_themes(self) -> None:
        """Register all custom themes (built-in LC + user-defined) with Textual."""
        for name, entry in theme.ThemeEntry.REGISTRY.items():
            if entry.custom:
                c = entry.colors
                try:
                    self.register_theme(
                        Theme(
                            name=name,
                            primary=c.primary,
                            secondary=c.secondary,
                            accent=c.accent,
                            foreground=c.foreground,
                            background=c.background,
                            surface=c.surface,
                            panel=c.panel,
                            warning=c.warning,
                            error=c.error,
                            success=c.success,
                            dark=entry.dark,
                            variables={
                                "footer-key-foreground": c.primary,
                            },
                        )
                    )
                except Exception:
                    logger.warning(
                        "Failed to register theme '%s'; skipping",
                        name,
                        exc_info=True,
                    )

    async def _show_theme_selector(self) -> None:
        """Show interactive theme selector as a modal screen."""
        from soothe_cli.tui.widgets.theme_selector import ThemeSelectorScreen

        # Capture scroll state.  The submit handler may have already caused
        # a reflow that re-anchored to the bottom, so we save the *current*
        # offset and release the anchor to prevent further drift while the
        # modal is open.
        chat = self.query_one("#chat", VerticalScroll)
        saved_y = chat.scroll_y
        was_anchored = chat.is_anchored
        chat.release_anchor()

        def handle_result(result: str | None) -> None:
            """Handle the theme selector result."""
            if result is not None:
                self.theme = result
                self.refresh_css(animate=False)

                async def _persist() -> None:
                    try:
                        ok = await asyncio.to_thread(save_theme_preference, result)
                        if not ok:
                            self.notify(
                                "Theme applied for this session but could not be saved. Check logs for details.",
                                severity="warning",
                                timeout=6,
                                markup=False,
                            )
                    except Exception:
                        logger.warning(
                            "Failed to persist theme preference",
                            exc_info=True,
                        )
                        self.notify(
                            "Theme applied for this session but could not be saved. Check logs for details.",
                            severity="warning",
                            timeout=6,
                            markup=False,
                        )

                self.call_later(_persist)
            # Restore scroll position, then re-anchor if it was anchored.
            chat.scroll_to(y=saved_y, animate=False)
            if was_anchored:
                chat.anchor()
            if self._chat_input:
                self._chat_input.focus_input()

        screen = ThemeSelectorScreen(current_theme=self.theme)
        self.push_screen(screen, handle_result)

    async def _show_notification_settings(self) -> None:
        """Show notification settings modal."""
        from soothe_cli.tui.model_config import is_warning_suppressed
        from soothe_cli.tui.widgets.notification_settings import (
            WARNING_TOGGLES,
            NotificationSettingsScreen,
        )

        suppressed: set[str] = set()
        try:
            for key, _ in WARNING_TOGGLES:
                if await asyncio.to_thread(is_warning_suppressed, key):
                    suppressed.add(key)
        except Exception:
            logger.warning("Failed to read notification settings", exc_info=True)
            suppressed = set()
            self.notify(
                "Could not read notification preferences. Showing defaults.",
                severity="warning",
                timeout=6,
                markup=False,
            )

        def handle_result(_result: None) -> None:
            if self._chat_input:
                self._chat_input.focus_input()

        screen = NotificationSettingsScreen(suppressed=suppressed)
        self.push_screen(screen, handle_result)

    async def _show_mcp_viewer(self) -> None:
        """Show read-only MCP server/tool viewer as a modal screen."""
        from soothe_cli.tui.widgets.mcp_viewer import MCPViewerScreen

        server_info = self._mcp_server_info
        if server_info is None:
            server_info = await self._fetch_mcp_status()
        screen = MCPViewerScreen(server_info=server_info or [])

        def handle_result(result: None) -> None:  # noqa: ARG001
            if self._chat_input:
                self._chat_input.focus_input()

        self.push_screen(screen, handle_result)

    async def _fetch_mcp_status(self) -> list[dict[str, Any]] | None:
        """Fetch MCP server status from daemon for the viewer."""
        if self._daemon_session is None:
            return None
        try:
            resp = await self._daemon_session.get_mcp_status()
        except Exception:  # noqa: BLE001
            return None
        return resp.get("servers")

    def _apply_loop_autopilot_mode(self, mode: str | None) -> None:
        """Sync local Solo/Autopilot mode from daemon bootstrap or toggle events."""
        if mode not in ("solo", "autopilot"):
            return
        self._loop_autopilot_mode = mode
        if self._status_bar is not None:
            label = "Autopilot" if mode == "autopilot" else "Solo"
            self._status_bar.set_session_tip(f"Mode: {label}")

    async def _show_context_viewer(self) -> None:
        """Show context engine goal DAG and status as a modal screen."""
        from soothe_cli.tui.widgets.context_viewer import ContextViewerScreen

        def handle_result(result: None) -> None:  # noqa: ARG001
            if self._chat_input:
                self._chat_input.focus_input()

        loop_id = self._lc_loop_id
        screen = ContextViewerScreen(loop_id=loop_id)
        self.push_screen(screen, handle_result)

    async def _submit_autopilot_job(self, task: str) -> None:
        """Submit an autopilot job via WebSocket (like CLI `soothe autopilot run`).

        Args:
            task: Task description for autonomous execution.
        """
        from soothe_sdk.client import (
            async_ws_command_client_from_config,
            is_daemon_live,
            websocket_url_from_config,
        )

        from soothe_cli.runtime import load_config
        from soothe_cli.tui.widgets.messages import ErrorMessage, UserMessage

        await self._mount_message(UserMessage(f"/autopilot {task}"))

        cfg = load_config()
        ws_url = websocket_url_from_config(cfg)

        # Check daemon is running
        if not await is_daemon_live(ws_url, timeout=5.0):
            await self._mount_message(
                ErrorMessage("Daemon not running. Start with 'soothed start'.")
            )
            return

        workspace = self._cwd if hasattr(self, "_cwd") else os.getcwd()

        try:
            client = async_ws_command_client_from_config(cfg)
            result = await client.autopilot_submit(task, workspace=workspace)
        except RuntimeError as exc:
            await self._mount_message(ErrorMessage(str(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Autopilot submit failed")
            await self._mount_message(ErrorMessage(f"Failed to submit autopilot job: {exc}"))
            return

        goal_id = result.get("goal_id", "")
        if goal_id:
            self.notify(f"Autopilot job submitted: {goal_id[:8]}", timeout=5)
            logger.info("Submitted autopilot job %s: %s", goal_id, task[:50])
        else:
            await self._mount_message(ErrorMessage("No goal_id returned from daemon"))

    async def _submit_cron_job(self, text: str, *, slash_input: str | None = None) -> None:
        """Submit a cron job via WebSocket (like CLI ``soothe cron add``).

        Args:
            text: Natural language schedule and task description.
            slash_input: Original slash command for chat display.
        """
        from soothe_sdk.client import (
            async_ws_command_client_from_config,
            is_daemon_live,
            websocket_url_from_config,
        )

        from soothe_cli.runtime import load_config
        from soothe_cli.tui.widgets.messages import AppMessage, ErrorMessage, UserMessage

        display = slash_input or f"/cron {text}"
        await self._mount_message(UserMessage(display))

        cfg = load_config()
        ws_url = websocket_url_from_config(cfg)
        if not await is_daemon_live(ws_url, timeout=5.0):
            await self._mount_message(
                ErrorMessage("Daemon not running. Start with 'soothed start'.")
            )
            return

        try:
            client = async_ws_command_client_from_config(cfg)
            result = await client.cron_add(text)
        except RuntimeError as exc:
            await self._mount_message(ErrorMessage(str(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cron submit failed")
            await self._mount_message(ErrorMessage(f"Failed to submit cron job: {exc}"))
            return

        job = result.get("job") or {}
        job_id = job.get("id", "")
        if not job_id:
            await self._mount_message(ErrorMessage("No job id returned from daemon"))
            return

        next_run = str(job.get("next_run", ""))[:19]
        self.notify(f"Cron job scheduled: {job_id[:8]}", timeout=5)
        await self._mount_message(
            AppMessage(
                f"Scheduled job {job_id[:12]}: {job.get('description', text)}\n"
                f"Next run: {next_run or 'unknown'}"
            )
        )
        logger.info("Submitted cron job %s: %s", job_id, text[:50])

    async def _show_loop_selector(self) -> None:
        """Show interactive loop selector as a modal screen."""
        from functools import partial

        from soothe_cli.tui.sessions import get_loop_limit
        from soothe_cli.tui.widgets.loop_selector import LoopSelectorScreen

        current = self._session_state.loop_id if self._session_state else None
        loop_limit = get_loop_limit()

        def handle_result(result: str | None) -> None:
            """Handle the loop selector result."""
            if result is not None:
                if self._agent_running or self._shell_running or self._connecting:
                    self._defer_action(
                        DeferredAction(
                            kind="loop_switch",
                            execute=partial(self._resume_loop_via_daemon, result),
                        )
                    )
                    self.notify("Loop will switch after current task completes.", timeout=3)
                else:
                    self.call_later(self._resume_loop_via_daemon, result)
            if self._chat_input:
                self._chat_input.focus_input()

        screen = LoopSelectorScreen(
            current_loop=current,
            loop_limit=loop_limit,
            daemon_session=self._daemon_session,
        )
        self.push_screen(screen, handle_result)

    async def _resume_loop_via_daemon(self, loop_id: str) -> None:
        """Resume a loop by subscribing to daemon events (RFC-503).

        Similar to continuing a loop in the CLI, but uses ``loop_subscribe`` RPC to attach
        to the loop's event stream.

        Args:
            loop_id: The loop ID to resume/attach.
        """
        if not self._daemon_session:
            await self._mount_message(AppMessage("Cannot switch loops: no daemon connection"))
            return

        if not self._session_state:
            await self._mount_message(AppMessage("Cannot switch loops: no active session"))
            return

        # Skip if already on this loop
        if self._session_state.loop_id == loop_id:
            await self._mount_message(AppMessage(f"Already on loop: {loop_id}"))
            return

        if self._loop_switching:
            await self._mount_message(AppMessage("Loop switch already in progress."))
            return

        # Save previous state for rollback on failure
        prev_loop_id = self._lc_loop_id
        prev_session_loop = self._session_state.loop_id
        self._loop_switching = True
        if self._chat_input:
            self._chat_input.set_cursor_active(active=False)

        try:
            self._update_status(f"Attaching to loop: {loop_id}")

            # Clear conversation (similar to /clear, without creating a new loop)
            self._pending_messages.clear()
            self._queued_widgets.clear()
            await self._clear_messages()
            self._context_tokens = 0
            self._tokens_approximate = False
            self._update_tokens(0)
            self._update_status("")

            status = await self._daemon_session.switch_loop(loop_id)
            if status.get("type") == "error":
                raise RuntimeError(str(status.get("message", "loop switch failed")))
            self._session_state.loop_id = loop_id
            self._lc_loop_id = loop_id
            self._clear_loop_model_override()

            self._update_welcome_banner(
                loop_id,
                missing_message="Welcome banner not found during loop switch to %s",
                warn_if_missing=False,
            )

            # Render historical transcript before live events start arriving on the
            # new subscription (RFC-413). Awaiting (rather than scheduling) guarantees
            # painting order: prior history first, then live frames.
            await self._load_loop_history(loop_id=loop_id)

            # Start consuming daemon events for this loop
            self._bg_event_worker = self.run_worker(
                self._consume_daemon_events_background(),
                exclusive=False,
                group="daemon-event-reader",
            )

        except Exception as exc:
            logger.exception("Failed to attach to loop %s", loop_id)
            # Restore previous loop ID so the user can retry
            self._session_state.loop_id = prev_session_loop
            self._lc_loop_id = prev_loop_id
            self._update_welcome_banner(
                prev_session_loop,
                missing_message=(
                    "Welcome banner not found during rollback to loop %s; banner may display stale id"
                ),
                warn_if_missing=True,
            )
            await self._mount_message(
                AppMessage(f"Failed to attach to loop {loop_id}: {exc}. Use /resume to try again.")
            )
        finally:
            self._loop_switching = False
            if self._chat_input:
                self._chat_input.set_cursor_active(active=True)
                self._chat_input.focus_input()

    def _update_welcome_banner(
        self,
        loop_id: str,
        *,
        missing_message: str,
        warn_if_missing: bool,
    ) -> None:
        """Update the welcome banner when the banner is mounted.

        Args:
            loop_id: Active loop id to display on the banner.
            missing_message: Log message template when banner is missing.
            warn_if_missing: Whether to log missing-banner cases at warning level.
        """
        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.update_loop_id(loop_id)
        except NoMatches:
            if warn_if_missing:
                logger.warning(missing_message, loop_id)
            else:
                logger.debug(missing_message, loop_id)

    def _clear_loop_model_override(self) -> None:
        """Drop per-loop model override; next turns use config/CLI defaults."""
        from soothe_cli.tui.config import settings

        self._model_override = None
        self._model_params_override = None
        if self._status_bar:
            self._status_bar.set_model(
                provider=settings.model_provider or "",
                model=settings.model_name or "",
            )

    async def _switch_model(
        self,
        model_spec: str,
        *,
        extra_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Switch model for the current loop without changing `config.yml`.

        The override is sent on each websocket ``input`` (resolved on the daemon
        host). Global ``settings`` and on-disk defaults are not updated; use
        ``/model --default`` to persist a new default.

        Args:
            model_spec: The model specification to switch to.

                Can be in `provider:model` format
                (e.g., `'anthropic:claude-sonnet-4-5'`) or just the model name
                for auto-detection.
            extra_kwargs: Extra constructor kwargs from `--model-params`.
        """
        from soothe_cli.tui.config import detect_provider, settings
        from soothe_cli.tui.model_config import ModelSpec

        logger.info("Switching model to %s", model_spec)

        if self._model_switching:
            await self._mount_message(AppMessage("Model switch already in progress."))
            return

        self._model_switching = True
        try:
            # Defensively strip leading colon in case of empty provider,
            # treat ":claude-opus-4-6" as "claude-opus-4-6"
            model_spec = model_spec.removeprefix(":")

            if not self._runtime_backend_ready():
                await self._mount_message(
                    ErrorMessage("No execution backend is configured for this session.")
                )
                return

            parsed = ModelSpec.try_parse(model_spec)
            if parsed:
                provider: str | None = parsed.provider
                model_name = parsed.model
            else:
                model_name = model_spec
                provider = detect_provider(model_spec)

            # Build the provider:model spec for the configurable middleware.
            display = model_spec
            if provider and not parsed:
                display = f"{provider}:{model_name}"

            # Effective model for this loop (session override wins over CLI defaults).
            prior_effective = (
                self._model_override or f"{settings.model_provider}:{settings.model_name}"
            ).strip()
            if display.strip() == prior_effective:
                await self._mount_message(AppMessage(f"Already using {display} for this loop"))
                return

            if self._daemon_session is None:
                await self._mount_message(
                    ErrorMessage("Not connected to the daemon; cannot switch models.")
                )
                return

            self._model_override = display
            self._model_params_override = extra_kwargs
            bar_provider = (parsed.provider if parsed else (provider or "")) or ""
            bar_model = (parsed.model if parsed else model_name) or ""
            if self._status_bar:
                self._status_bar.set_model(provider=bar_provider, model=bar_model)
            await self._mount_message(
                AppMessage(
                    f"Switched this loop to {display} for daemon turns "
                    f"(session only; daemon host default in config.yml unchanged).",
                ),
            )
            logger.info("Model override set to %s for daemon-backed TUI session", display)

            # Anchor to bottom so the confirmation message is visible
            with suppress(NoMatches, ScreenStackError):
                self.query_one("#chat", VerticalScroll).anchor()
        finally:
            self._model_switching = False

    async def _set_default_model(self, model_spec: str) -> None:
        """Set the default model in config without switching the current session.

        Updates `[models].default` in `~/SOOTHE_HOME/config.yml` so that
        future CLI launches use this model. Does not affect the running session.

        Args:
            model_spec: The model specification (e.g., `'anthropic:claude-opus-4-6'`).
        """
        from soothe_cli.tui.config import detect_provider
        from soothe_cli.tui.model_config import ModelSpec, save_default_model

        model_spec = model_spec.removeprefix(":")

        parsed = ModelSpec.try_parse(model_spec)
        if not parsed:
            provider = detect_provider(model_spec)
            if provider:
                model_spec = f"{provider}:{model_spec}"

        if await asyncio.to_thread(save_default_model, model_spec):
            await self._mount_message(AppMessage(f"Default model set to {model_spec}"))
        else:
            await self._mount_message(
                ErrorMessage("Could not save default model. Check permissions for ~/SOOTHE_HOME/")
            )

    async def _clear_default_model(self) -> None:
        """Remove the default model from config.

        After clearing, future launches fall back to `[models].recent` or
        environment auto-detection.
        """
        from soothe_cli.tui.model_config import clear_default_model

        if await asyncio.to_thread(clear_default_model):
            await self._mount_message(
                AppMessage(
                    "Default model cleared. Future launches will use recent model or auto-detect."
                )
            )
        else:
            await self._mount_message(
                ErrorMessage("Could not clear default model. Check permissions for ~/SOOTHE_HOME/")
            )

    # SOOTHE: Slash command actions

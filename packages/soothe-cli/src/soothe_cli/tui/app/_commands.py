"""Slash command routing and handling mixin."""

from __future__ import annotations

import logging
import webbrowser
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from textual.content import Content

from textual.app import ScreenStackError
from textual.containers import VerticalScroll
from textual.content import Content
from textual.css.query import NoMatches
from textual.style import Style as TStyle

from soothe_cli.tui import theme
from soothe_cli.tui._session_stats import format_token_count
from soothe_cli.tui._version import DOCS_URL
from soothe_cli.tui.app._module_init import (
    _COMMAND_URLS,
    DeferredAction,
    _extract_model_params_flag,
)
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    ErrorMessage,
    QueuedUserMessage,
    UserMessage,
)
from soothe_cli.tui.widgets.welcome import WelcomeBanner

logger = logging.getLogger(__name__)


class _CommandsMixin:
    """Slash command routing, URL commands, skill commands, and token display."""

    async def _open_url_command(self, command: str, cmd: str) -> None:
        """Open a URL in the browser and display a clickable link.

        The browser opens immediately regardless of busy state. When the app is
        busy, a queued indicator is shown and the real chat output (user echo
        + clickable link) replaces it after the current task finishes.

        Args:
            command: The raw command text (displayed as user message).
            cmd: The normalized slash command used to look up the URL.
        """
        url = _COMMAND_URLS[cmd]
        webbrowser.open(url)

        if self._agent_running or self._shell_running:
            queued_widget = QueuedUserMessage(command)
            self._queued_widgets.append(queued_widget)
            await self._mount_message(queued_widget)

            async def _mount_output() -> None:
                # Remove the ephemeral queued widget, then mount real output.
                if queued_widget in self._queued_widgets:
                    self._queued_widgets.remove(queued_widget)
                with suppress(Exception):
                    await queued_widget.remove()
                await self._mount_message(UserMessage(command))
                link = Content.styled(url, TStyle(dim=True, italic=True, link=url))
                await self._mount_message(AppMessage(link))

            # Append directly — no dedup; each URL command gets its own output.
            self._deferred_actions.append(DeferredAction(kind="chat_output", execute=_mount_output))
            return

        await self._mount_message(UserMessage(command))
        link = Content.styled(url, TStyle(dim=True, italic=True, link=url))
        await self._mount_message(AppMessage(link))

    @staticmethod
    async def _build_thread_message(prefix: str, thread_id: str) -> str | Content:
        """Build a thread status message with the thread id.

        Args:
            prefix: Label before the thread ID (e.g. `'Resumed thread'`).
            thread_id: The thread identifier.

        Returns:
            Plain status line.
        """
        return f"{prefix}: {thread_id}"

    async def _handle_command(self, command: str) -> None:
        """Handle a slash command.

        Args:
            command: The slash command (including /)
        """
        from soothe_cli.shared.commands.command_router import (
            parse_slash_command,
            validate_command,
        )
        from soothe_cli.shared.commands.slash_commands import COMMANDS as _RFC404_COMMANDS

        # RFC-404 daemon *routing* commands (/browser, /claude, /research, /plan):
        # send the full line as a normal user turn so ``parse_subagent_from_input``
        # runs in the daemon adapter (same as headless CLI). Without this branch,
        # ``cmd == "/claude …"`` never matches the bare ``/claude`` handlers below.
        full_stripped = command.strip()
        first_word, query = parse_slash_command(full_stripped)
        if first_word:
            entry = _RFC404_COMMANDS.get(first_word)
            if entry and entry.get("location") == "daemon" and entry.get("type") == "routing":
                thread_id = self._session_state.loop_id if self._session_state else None
                ok, err = validate_command(entry, first_word, query, thread_id)
                if not ok:
                    await self._mount_message(UserMessage(command))
                    await self._mount_message(AppMessage(f"Error: {err}"))
                    with suppress(NoMatches, ScreenStackError):
                        self.query_one("#chat", VerticalScroll).anchor()
                    return
                await self._mount_message(UserMessage(command))
                await self._send_to_agent(full_stripped)
                with suppress(NoMatches, ScreenStackError):
                    self.query_one("#chat", VerticalScroll).anchor()
                return

        from soothe_cli.tui.config import newline_shortcut, settings

        cmd = command.lower().strip()

        if cmd in {"/quit", "/q"}:
            self.exit()
        elif cmd == "/help":
            await self._mount_message(UserMessage(command))
            help_body = (
                "Commands: /quit, /clear, /editor, /autopilot, /mcp, "
                "/model [--model-params JSON] [--default], /notifications, "
                "/reload, /skill:<name>, /remember, /theme, "
                "/tokens, /loops, "
                "/browser, /claude, /research, /explore, /plan (subagent routing), "
                "/update, /auto-update, /changelog, /docs, /feedback, /help\n\n"
                "Interactive Features:\n"
                "  Enter           Submit your message\n"
                f"  {newline_shortcut():<15} Insert newline\n"
                "  Ctrl+X          Open prompt in external editor\n"
                "  Shift+Tab       Toggle auto-approve mode\n"
                "  @filename       Auto-complete files and inject content\n"
                "  /command        Slash commands (/help, /clear, /quit)\n"
                "  !command        Run shell commands directly\n\n"
                "Docs: "
            )
            help_text = Content.assemble(
                (help_body, "dim italic"),
                (DOCS_URL, TStyle(dim=True, italic=True, link=DOCS_URL)),
            )
            await self._mount_message(AppMessage(help_text))

        elif cmd in {"/changelog", "/docs", "/feedback"}:
            await self._open_url_command(command, cmd)
        elif cmd == "/version":
            await self._mount_message(UserMessage(command))
            # Show CLI and SDK package versions
            try:
                from soothe_cli.tui._version import (
                    __version__ as cli_version,
                )

                cli_line = f"Soothe version: {cli_version}"
            except ImportError:
                logger.debug("soothe._version module not found")
                cli_line = "Soothe version: unknown"
            except Exception:
                logger.warning("Unexpected error looking up CLI version", exc_info=True)
                cli_line = "Soothe version: unknown"
            try:
                from importlib.metadata import (
                    PackageNotFoundError,
                )
                from importlib.metadata import (
                    version as _pkg_version,
                )

                sdk_version = _pkg_version("Soothe")
                sdk_line = f"Soothe (SDK) version: {sdk_version}"
            except PackageNotFoundError:
                logger.debug("Soothe SDK package not found in environment")
                sdk_line = "Soothe (SDK) version: unknown"
            except Exception:
                logger.warning("Unexpected error looking up SDK version", exc_info=True)
                sdk_line = "Soothe (SDK) version: unknown"
            await self._mount_message(AppMessage(f"{cli_line}\n{sdk_line}"))
        elif cmd == "/clear":
            self._pending_messages.clear()
            self._queued_widgets.clear()
            await self._clear_messages()
            self._context_tokens = 0
            self._tokens_approximate = False
            self._update_tokens(0)
            # Clear status message (e.g., "Interrupted" from previous session)
            self._update_status("")
            # Reset thread to start fresh conversation
            if self._session_state:
                if self._daemon_session is not None:
                    status_event = await self._daemon_session.new_thread()
                    new_thread_id = (
                        str(status_event.get("thread_id", "")) or self._session_state.reset_thread()
                    )
                    self._session_state.loop_id = new_thread_id
                    self._lc_loop_id = new_thread_id
                else:
                    new_thread_id = self._session_state.reset_thread()
                try:
                    banner = self.query_one("#welcome-banner", WelcomeBanner)
                    banner.update_loop_id(new_thread_id)
                except NoMatches:
                    pass
                self._clear_thread_model_override()
                await self._mount_message(AppMessage(f"Started new thread: {new_thread_id}"))
        elif cmd == "/editor":
            await self.action_open_editor()
        elif cmd == "/loops":
            await self._show_loop_selector()
        elif cmd == "/update":
            await self._handle_update_command()
        elif cmd == "/auto-update":
            await self._handle_auto_update_toggle()
        elif cmd == "/tokens":
            await self._mount_message(UserMessage(command))
            if self._context_tokens > 0:
                count = self._context_tokens
                formatted = format_token_count(count)

                model_name = settings.model_name
                context_limit = settings.model_context_limit

                if context_limit is not None:
                    limit_str = format_token_count(context_limit)
                    pct = count / context_limit * 100
                    usage = f"{formatted} / {limit_str} tokens ({pct:.0f}%)"
                else:
                    usage = f"{formatted} tokens used"

                msg = f"{usage} \u00b7 {model_name}" if model_name else usage

                conv_tokens = await self._get_conversation_token_count()
                if conv_tokens is not None:
                    overhead = max(0, count - conv_tokens)
                    overhead_str = format_token_count(overhead)
                    conv_str = format_token_count(conv_tokens)

                    overhead_unit = " tokens" if overhead < 1000 else ""  # noqa: PLR2004  # not bothersome, cosmetic
                    conv_unit = " tokens" if conv_tokens < 1000 else ""  # noqa: PLR2004  # not bothersome, cosmetic

                    msg += (
                        f"\n\u251c System prompt + tools: ~{overhead_str}{overhead_unit} (fixed)"  # noqa: E501
                        f"\n\u2514 Conversation: ~{conv_str}{conv_unit}"
                    )

                await self._mount_message(AppMessage(msg))
            else:
                model_name = settings.model_name
                context_limit = settings.model_context_limit

                parts: list[str] = ["No token usage yet"]
                if context_limit is not None:
                    limit_str = format_token_count(context_limit)
                    parts.append(f"{limit_str} token context window")
                if model_name:
                    parts.append(model_name)

                await self._mount_message(AppMessage(" · ".join(parts)))
        elif cmd == "/remember" or cmd.startswith("/remember "):
            # Convenience alias for /skill:remember — shorter and discoverable
            # before skill loading completes.
            args = command.strip()[len("/remember") :].strip()
            rewritten = f"/skill:remember {args}" if args else "/skill:remember"
            await self._handle_skill_command(rewritten)
        elif cmd == "/skill-creator" or cmd.startswith("/skill-creator "):
            # Convenience alias for /skill:skill-creator — shorter and
            # discoverable before skill loading completes.
            args = command.strip()[len("/skill-creator") :].strip()
            rewritten = f"/skill:skill-creator {args}" if args else "/skill:skill-creator"
            await self._handle_skill_command(rewritten)
        elif cmd == "/autopilot":
            await self._show_autopilot_dashboard()
        elif cmd == "/mcp":
            await self._show_mcp_viewer()
        elif cmd == "/theme":
            await self._show_theme_selector()
        elif cmd == "/notifications":
            await self._show_notification_settings()
        elif cmd == "/model" or cmd.startswith("/model "):
            model_arg = None
            set_default = False
            extra_kwargs: dict[str, Any] | None = None
            if cmd.startswith("/model "):
                raw_arg = command.strip()[len("/model ") :].strip()
                try:
                    raw_arg, extra_kwargs = _extract_model_params_flag(raw_arg)
                except (ValueError, TypeError) as exc:
                    await self._mount_message(UserMessage(command))
                    await self._mount_message(ErrorMessage(str(exc)))
                    return
                if raw_arg.startswith("--default"):
                    set_default = True
                    model_arg = raw_arg[len("--default") :].strip() or None
                else:
                    model_arg = raw_arg or None

            if set_default:
                await self._mount_message(UserMessage(command))
                if extra_kwargs:
                    await self._mount_message(
                        ErrorMessage(
                            "--model-params cannot be used with --default. "
                            "Model params are applied per-session, not "
                            "persisted."
                        )
                    )
                elif model_arg == "--clear":
                    await self._clear_default_model()
                elif model_arg:
                    await self._set_default_model(model_arg)
                else:
                    await self._mount_message(
                        AppMessage(
                            "Usage: /model --default provider:model\n       /model --default --clear"
                        )
                    )
            elif model_arg:
                # Direct switch: /model claude-sonnet-4-5
                await self._mount_message(UserMessage(command))
                await self._switch_model(model_arg, extra_kwargs=extra_kwargs)
            else:
                await self._show_model_selector(extra_kwargs=extra_kwargs)
        elif cmd == "/reload":
            await self._mount_message(UserMessage(command))
            try:
                changes = settings.reload_from_environment()

                from soothe_cli.tui.model_config import clear_caches

                clear_caches()
            except (OSError, ValueError):
                logger.exception("Failed to reload configuration")
                await self._mount_message(
                    AppMessage(
                        "Failed to reload configuration. Check your .env "
                        "file and environment variables for syntax errors, "
                        "then try again."
                    )
                )
                return

            # Reload user themes from config.yml and re-register with Textual
            theme_reload_ok = True
            try:
                theme.reload_registry()
                self._register_custom_themes()
            except Exception:
                theme_reload_ok = False
                logger.warning("Failed to reload user themes", exc_info=True)

            if changes:
                report = "Configuration reloaded. Changes:\n" + "\n".join(
                    f"  - {change}" for change in changes
                )
            else:
                report = "Configuration reloaded. No changes detected."
            report += "\nModel config caches cleared."
            if theme_reload_ok:
                report += "\nTheme registry reloaded."
            else:
                report += "\nTheme registry reload failed. Check config.yml for errors."
            await self._mount_message(AppMessage(report))

            # Re-discover skills so autocomplete reflects any new/removed skills
            if self._daemon_config is None:
                self.run_worker(
                    self._discover_skills(),
                    exclusive=True,
                    group="startup-skill-discovery",
                )
            if self._daemon_session is not None:
                self.run_worker(
                    self._refresh_daemon_skills_catalog(),
                    exclusive=True,
                    group="daemon-skills-catalog",
                )
        elif cmd.startswith("/skill:"):
            await self._handle_skill_command(command)
        # -- Hidden debug commands (not in COMMANDS / autocomplete) -----------
        elif cmd == "/debug-error":
            await self._mount_message(
                ErrorMessage(
                    "Server failed to start: RuntimeError: Server process exited with code 3"
                )
            )
        else:
            await self._mount_message(UserMessage(command))
            await self._mount_message(AppMessage(f"Unknown command: {cmd}"))

        # Anchor to bottom so command output stays visible
        with suppress(NoMatches, ScreenStackError):
            self.query_one("#chat", VerticalScroll).anchor()

    async def _handle_skill_command(self, command: str) -> None:
        """Handle a `/skill:<name>` command via daemon RPC.

        Args:
            command: The full command string (e.g., `/skill:web-research find X`).
        """
        from soothe_cli.tui.command_registry import parse_skill_command

        skill_name, args = parse_skill_command(command)
        if not skill_name:
            await self._mount_bare_skill_list(command.strip())
            return
        if self._daemon_session is not None:
            await self._invoke_skill_daemon(command.strip(), skill_name, args)
            return
        # No daemon session available — skills require daemon connection
        await self._mount_message(UserMessage(command.strip()))
        await self._mount_message(
            AppMessage("Skills require a daemon connection. Connect to a daemon first.")
        )

    async def _get_conversation_token_count(self) -> int | None:
        """Return the approximate conversation-only token count.

        Returns:
            Token count as an integer, or `None` if state is unavailable.
        """
        if not self._agent:
            return None
        try:
            from langchain_core.messages.utils import (
                count_tokens_approximately,
            )

            config: RunnableConfig = {
                "configurable": {"thread_id": self._lc_loop_id},
            }
            state = await self._agent.aget_state(config)
            if not state or not state.values:
                return None
            messages = state.values.get("messages", [])
            if not messages:
                return None
            return count_tokens_approximately(messages)
        except Exception:  # best-effort for /tokens display
            logger.debug("Failed to retrieve conversation token count", exc_info=True)
            return None

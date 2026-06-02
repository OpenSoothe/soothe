"""Agent execution, message routing, queue processing, shell commands, and daemon events mixin."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
import webbrowser
from contextlib import suppress
from typing import Any, Literal

from textual.app import ScreenStackError
from textual.containers import VerticalScroll
from textual.content import Content
from textual.css.query import NoMatches
from textual.style import Style as TStyle

from soothe_cli.cli.execution.daemon_errors import (
    friendly_daemon_connection_error,
    is_daemon_connection_error,
)
from soothe_cli.cli.execution.daemon_errors import (
    friendly_daemon_execution_error as _friendly_agent_execution_error,
)
from soothe_cli.runtime.state.session_stats import SessionStats, format_token_count
from soothe_cli.tui import theme
from soothe_cli.tui._cli_context import CLIContext
from soothe_cli.tui._version import DOCS_URL
from soothe_cli.tui.app._module_init import (
    _COMMAND_URLS,
    DeferredAction,
    QueuedMessage,
    _extract_model_params_flag,
)
from soothe_cli.tui.hooks import dispatch_hook
from soothe_cli.tui.widgets.chat_input import ChatInput
from soothe_cli.tui.widgets.messages import (
    AppMessage,
    AssistantMessage,
    ErrorMessage,
    QueuedUserMessage,
    UserMessage,
)
from soothe_cli.tui.widgets.welcome import WelcomeBanner

_monotonic = time.monotonic

InputMode = Literal["normal", "shell", "command"]

logger = logging.getLogger(__name__)


class _ExecutionMixin:
    """Agent execution, message routing, queue, shell commands, and daemon events."""

    async def _process_message(self, value: str, mode: InputMode) -> None:
        """Route a message to the appropriate handler based on mode.

        Args:
            value: The message text to process.
            mode: The input mode that determines message routing.
        """
        if mode == "shell":
            await self._handle_shell_command(value.removeprefix("!"))
        elif mode == "command":
            await self._handle_command(value)
        elif mode == "normal":
            await self._handle_user_message(value)
        else:
            logger.warning("Unrecognized input mode %r, treating as normal", mode)
            await self._handle_user_message(value)

    def _has_initial_submission(self) -> bool:
        """Return whether startup should auto-submit a prompt or skill."""
        return self._initial_skill is not None or bool(
            self._initial_prompt and self._initial_prompt.strip()
        )

    def _schedule_initial_submission(self) -> bool:
        """Schedule the startup prompt or skill after the next refresh.

        Returns:
            `True` when a startup submission was queued, `False` otherwise.
        """
        if not self._has_initial_submission():
            return False
        self.call_after_refresh(lambda: asyncio.create_task(self._submit_initial_submission()))
        return True

    async def _submit_initial_submission(self) -> None:
        """Submit the startup prompt or skill after the UI is ready."""
        try:
            if self._initial_skill is not None:
                if self._daemon_session is not None:
                    cmd = f"/skill:{self._initial_skill}"
                    rest = (self._initial_prompt or "").strip()
                    if rest:
                        cmd = f"{cmd} {rest}"
                    await self._invoke_skill_daemon(
                        cmd, self._initial_skill, self._initial_prompt or ""
                    )
                else:
                    await self._mount_message(
                        AppMessage("Skills require a daemon connection. Connect to a daemon first.")
                    )
                return
            if self._initial_prompt and self._initial_prompt.strip():
                await self._handle_user_message(self._initial_prompt)
        except Exception:
            logger.exception("Unhandled error during initial submission")
            with suppress(Exception):
                await self._mount_message(
                    ErrorMessage(
                        "Failed to submit startup prompt. Try running the command manually in the session."
                    )
                )

    def _can_bypass_queue(self, value: str) -> bool:
        """Check if a slash command can skip the message queue.

        Args:
            value: The lowered, stripped command string (e.g. `/model`).

        Returns:
            `True` if the command should bypass the busy-state queue.
        """
        from soothe_cli.tui.command_registry import (
            BYPASS_WHEN_CONNECTING,
            IMMEDIATE_UI,
            SIDE_EFFECT_FREE,
        )

        cmd = value.split(maxsplit=1)[0] if value else ""
        if cmd in BYPASS_WHEN_CONNECTING:
            return self._connecting and not (self._agent_running or self._shell_running)
        if cmd in IMMEDIATE_UI:
            # Only bare form (no args) bypasses — /model opens selector,
            # /model <name> does a direct switch that shouldn't race with agent.
            return value == cmd
        return cmd in SIDE_EFFECT_FREE

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle submitted input from ChatInput widget."""
        value = event.value
        mode: InputMode = event.mode  # type: ignore[assignment]  # Textual event mode is str at type level but InputMode at runtime

        # Reset quit pending state on any input
        self._quit_pending = False

        await dispatch_hook("user.prompt", {})

        # /quit and /q always execute immediately, even mid-loop-switch.
        from soothe_cli.tui.command_registry import ALWAYS_IMMEDIATE

        if mode == "command" and value.lower().strip() in ALWAYS_IMMEDIATE:
            self.exit()
            return

        # Prevent message handling while a loop switch is in-flight.
        if self._loop_switching:
            self.notify(
                "Loop switch in progress. Please wait.",
                severity="warning",
                timeout=3,
            )
            return

        # If agent/shell is running or server is still starting up, enqueue
        # instead of processing. Messages queued during connection are drained
        # once the server is ready.
        if self._agent_running or self._shell_running or self._connecting:
            if mode == "command" and self._can_bypass_queue(value.lower().strip()):
                await self._process_message(value, mode)
                return
            self._pending_messages.append(QueuedMessage(text=value, mode=mode))
            queued_widget = QueuedUserMessage(value)
            self._queued_widgets.append(queued_widget)
            await self._mount_message(queued_widget)
            return

        await self._process_message(value, mode)

    def on_chat_input_mode_changed(self, event: ChatInput.ModeChanged) -> None:
        """Update status bar when input mode changes."""
        if self._status_bar:
            self._status_bar.set_mode(event.mode)

    async def _handle_shell_command(self, command: str) -> None:
        """Handle a shell command (! prefix).

        Thin dispatcher that mounts the user message and spawns a worker
        so the event loop stays free for key events (Esc/Ctrl+C).

        Args:
            command: The shell command to execute.
        """
        await self._mount_message(UserMessage(f"!{command}"))
        self._shell_running = True

        if self._chat_input:
            self._chat_input.set_cursor_active(active=False)

        self._shell_worker = self.run_worker(
            self._run_shell_task(command),
            exclusive=False,
        )

    async def _run_shell_task(self, command: str) -> None:
        """Run a shell command in a background worker.

        This mirrors `_run_agent_task`: running in a worker keeps the event
        loop free so Esc/Ctrl+C can cancel the worker -> raise
        `CancelledError` -> kill the process.

        Args:
            command: The shell command to execute.

        Raises:
            CancelledError: If the command is interrupted by the user.
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                start_new_session=(sys.platform != "win32"),
            )
            self._shell_process = proc

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=60)
            except TimeoutError:
                await self._kill_shell_process()
                await self._mount_message(ErrorMessage("Command timed out (60s limit)"))
                return
            except asyncio.CancelledError:
                await self._kill_shell_process()
                raise

            output = (stdout_bytes or b"").decode(errors="replace").strip()
            stderr_text = (stderr_bytes or b"").decode(errors="replace").strip()
            if stderr_text:
                output += f"\n[stderr]\n{stderr_text}"

            if output:
                msg = AssistantMessage(f"```\n{output}\n```")
                await self._mount_message(msg)
                await msg.write_initial_content()
            else:
                await self._mount_message(AppMessage("Command completed (no output)"))

            if proc.returncode and proc.returncode != 0:
                await self._mount_message(ErrorMessage(f"Exit code: {proc.returncode}"))

            # Anchor to bottom so shell output stays visible
            with suppress(NoMatches, ScreenStackError):
                self.query_one("#chat", VerticalScroll).anchor()

        except OSError as e:
            logger.exception("Failed to execute shell command: %s", command)
            err_msg = f"Failed to run command: {e}"
            await self._mount_message(ErrorMessage(err_msg))
        finally:
            await self._cleanup_shell_task()

    async def _cleanup_shell_task(self) -> None:
        """Clean up after shell command task completes or is cancelled."""
        was_interrupted = self._shell_process is not None and (
            self._shell_worker is not None and self._shell_worker.is_cancelled
        )
        self._shell_process = None
        self._shell_running = False
        self._shell_worker = None
        if was_interrupted:
            await self._mount_message(AppMessage("Command interrupted"))
        if self._chat_input:
            self._chat_input.set_cursor_active(active=True)
        try:
            await self._maybe_drain_deferred()
        except Exception:
            logger.exception("Failed to drain deferred actions during shell cleanup")
            with suppress(Exception):
                await self._mount_message(
                    ErrorMessage(
                        "A deferred action failed after task completion. You may need to retry the operation."
                    )
                )
        await self._process_next_from_queue()

    async def _kill_shell_process(self) -> None:
        """Terminate the running shell command process.

        On POSIX, sends SIGTERM to the entire process group (killing children).
        On Windows, terminates only the root process. No-op if the process has
        already exited. Waits up to 5s for clean shutdown, then escalates
        to SIGKILL.
        """
        proc = self._shell_process
        if proc is None or proc.returncode is not None:
            return

        try:
            if sys.platform != "win32":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except ProcessLookupError:
            return
        except OSError:
            logger.warning("Failed to terminate shell process (pid=%s)", proc.pid, exc_info=True)
            return

        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            logger.warning(
                "Shell process (pid=%s) did not exit after SIGTERM; sending SIGKILL",
                proc.pid,
            )
            with suppress(ProcessLookupError, OSError):
                if sys.platform != "win32":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            with suppress(ProcessLookupError, OSError):
                await proc.wait()
        except (ProcessLookupError, OSError):
            pass

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
        await asyncio.to_thread(webbrowser.open, url)

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
    async def _build_loop_status_line(prefix: str, loop_id: str) -> str | Content:
        """Build a status line with the loop id.

        Args:
            prefix: Label before the id (e.g. ``'Resumed loop'``).
            loop_id: Loop id.

        Returns:
            Plain status line.
        """
        return f"{prefix}: {loop_id}"

    async def _handle_command(self, command: str) -> None:
        """Handle a slash command.

        Args:
            command: The slash command (including /)
        """
        from soothe_cli.tui.commands.command_router import (
            parse_slash_command,
            validate_command,
        )
        from soothe_cli.tui.commands.slash_commands import COMMANDS as _RFC404_COMMANDS

        # RFC-404 daemon *routing* commands (/research, /explore, /plan, optional /«id»):
        # send the full line as a normal user turn so ``parse_subagent_from_input``
        # runs in the daemon adapter (same as headless CLI). Without this branch,
        # ``cmd == "/research …"`` never matches the bare single-token handlers below.
        full_stripped = command.strip()
        first_word, query = parse_slash_command(full_stripped)
        if first_word:
            entry = _RFC404_COMMANDS.get(first_word)
            if entry and entry.get("location") == "daemon" and entry.get("type") == "routing":
                loop_id = self._session_state.loop_id if self._session_state else None
                ok, err = validate_command(entry, first_word, query, loop_id)
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
                "/reload, /skill:<name>, /theme, "
                "/tokens, /loops, "
                "/research, /explore, /plan, /«subagent» (when configured), "
                "/update, /auto-update, /changelog, /docs, /feedback, /help\n\n"
                "Interactive Features:\n"
                "  Enter           Submit your message\n"
                f"  {newline_shortcut():<15} Insert newline\n"
                "  Ctrl+X          Open prompt in external editor\n"
                "  Shift+Tab       Cycle loop selector\n"
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
            if self._session_state:
                if self._daemon_session is None:
                    await self._mount_message(
                        AppMessage("Not connected to the daemon; cannot start a new loop.")
                    )
                else:
                    status_event = await self._daemon_session.new_loop()
                    new_loop_id = (
                        str(status_event.get("loop_id", "")) or self._session_state.reset_loop()
                    )
                    self._session_state.loop_id = new_loop_id
                    self._lc_loop_id = new_loop_id
                    try:
                        banner = self.query_one("#welcome-banner", WelcomeBanner)
                        banner.update_loop_id(new_loop_id)
                    except NoMatches:
                        pass
                    self._clear_loop_model_override()
                    await self._mount_message(AppMessage(f"Started new loop: {new_loop_id}"))
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

            if self._daemon_session is not None:
                self.run_worker(
                    self._refresh_daemon_skills_catalog(),
                    exclusive=True,
                    group="daemon-skills-catalog",
                )
        elif cmd.startswith(("/skill:", "/skills:")):
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

    async def _handle_user_message(self, message: str) -> None:
        """Handle a user message to send to the agent.

        Args:
            message: The user's message
        """
        # Mount the user message
        await self._mount_message(UserMessage(message))
        await self._send_to_agent(message)

    async def _send_to_agent(
        self,
        message: str,
        *,
        message_kwargs: dict[str, Any] | None = None,
        skip_daemon_send_turn: bool = False,
    ) -> None:
        """Send a message to the agent and start execution.

        This is the low-level send path. It does NOT mount any widget — the
        caller is responsible for mounting the appropriate visual representation
        (e.g., `UserMessage`, `SkillMessage`) before calling this method.

        Args:
            message: The prompt to send to the agent.
            message_kwargs: Extra fields merged into the stream input message
                dict (e.g., `additional_kwargs` for skill metadata).
            skip_daemon_send_turn: When using a daemon session, only attach to
                the in-flight stream (prompt already queued on the daemon).
        """
        # Anchor to bottom so streaming response stays visible
        with suppress(NoMatches, ScreenStackError):
            self.query_one("#chat", VerticalScroll).anchor()

        # Check if agent is available
        if self._runtime_backend_ready() and self._ui_adapter and self._session_state:
            if self._daemon_session is not None:
                try:
                    await self._daemon_session.ensure_connected()
                except (ConnectionError, OSError, TimeoutError) as exc:
                    await self._mount_message(
                        ErrorMessage(
                            f"Daemon connection error. {friendly_daemon_connection_error(exc)}"
                        )
                    )
                    return
            self._agent_running = True

            if self._chat_input:
                self._chat_input.set_cursor_active(active=False)

            # Use run_worker to avoid blocking the main event loop
            # This allows the UI to remain responsive during agent execution
            self._agent_worker = self.run_worker(
                self._run_agent_task(
                    message,
                    message_kwargs=message_kwargs,
                    skip_daemon_send_turn=skip_daemon_send_turn,
                ),
                exclusive=False,
            )
        elif self._server_startup_error:
            await self._mount_message(
                ErrorMessage(f"Server failed to start: {self._server_startup_error}")
            )
        else:
            await self._mount_message(AppMessage("Agent not configured for this session."))

    async def _run_agent_task(
        self,
        message: str,
        *,
        message_kwargs: dict[str, Any] | None = None,
        skip_daemon_send_turn: bool = False,
    ) -> None:
        """Run the agent task in a background worker.

        This runs in a Textual worker so the main event loop stays responsive.

        Args:
            message: The prompt to send to the agent.
            message_kwargs: Extra fields merged into the stream input message
                dict (e.g., `additional_kwargs` for skill metadata).
            skip_daemon_send_turn: When ``True`` with a daemon session, only
                consume the daemon stream (prompt already queued server-side).
        """
        # Caller ensures _ui_adapter is set (checked in _handle_user_message)
        if self._ui_adapter is None:
            return
        # Import from submodule so package ``__init__`` does not eagerly load
        # unrelated symbols; ``execute_task_textual`` graph is prewarmed on startup.
        from soothe_cli.tui.textual_adapter import execute_task_textual

        # Create the stats object up-front and store on the app so
        # exit() can merge it synchronously if the worker is cancelled
        # before this method can return (e.g. Ctrl+D during a pending tool call).
        turn_stats = SessionStats()
        self._inflight_turn_stats = turn_stats
        self._inflight_turn_start = time.monotonic()
        try:
            await execute_task_textual(
                user_input=message,
                daemon_session=self._daemon_session,
                assistant_id=self._assistant_id,
                session_state=self._session_state,
                adapter=self._ui_adapter,
                image_tracker=self._image_tracker,
                sandbox_type=self._sandbox_type,
                workspace=self._cwd,
                message_kwargs=message_kwargs,
                context=CLIContext(
                    model=self._model_override,
                    model_params=self._model_params_override or {},
                ),
                turn_stats=turn_stats,
                skip_daemon_send_turn=skip_daemon_send_turn,
                clarification_mode=getattr(self, "_clarification_mode", None),
            )
        except Exception as e:  # Resilient tool rendering
            logger.exception("Agent execution failed")
            if is_daemon_connection_error(e):
                display_err = friendly_daemon_connection_error(e)
                error_title = "Daemon connection error"
            else:
                display_err = _friendly_agent_execution_error(e)
                error_title = "Agent error"
            # Ensure any in-flight tool calls don't remain stuck in "Running..."
            # when streaming aborts before tool results arrive.
            if self._ui_adapter:
                self._ui_adapter.finalize_pending_tools_with_error(f"{error_title}: {display_err}")
                self._ui_adapter.finalize_pending_steps_with_error(f"{error_title}: {display_err}")
            try:
                await self._mount_message(ErrorMessage(f"{error_title}. {display_err}"))
            except Exception:
                logger.debug("Could not mount error message (app closing?)", exc_info=True)
        finally:
            # Merge turn stats before cleanup — _cleanup_agent_task may raise
            # during teardown (widget removal on a torn-down DOM), and stats
            # should ideally be captured regardless.
            # exit() clears _inflight_turn_stats when it merges, so
            # checking for None prevents double-counting.
            if self._inflight_turn_stats is not None:
                self._session_stats.merge(turn_stats)
                self._inflight_turn_stats = None
            await self._cleanup_agent_task()

    async def _process_next_from_queue(self) -> None:
        """Process the next message from the queue if any exist.

        Dequeues and processes the next pending message in FIFO order.
        Uses the `_processing_pending` flag to prevent reentrant execution.
        """
        if self._processing_pending or not self._pending_messages or self._exit:
            return

        self._processing_pending = True
        try:
            msg = self._pending_messages.popleft()

            # Remove the ephemeral queued-message widget
            if self._queued_widgets:
                widget = self._queued_widgets.popleft()
                await widget.remove()

            await self._process_message(msg.text, msg.mode)
        except Exception:
            logger.exception("Failed to process queued message")
            await self._mount_message(
                ErrorMessage(f"Failed to process queued message: {msg.text[:60]}")
            )
        finally:
            self._processing_pending = False

        # Command mode messages complete synchronously without spawning
        # a worker, so cleanup won't fire again. Continue draining the
        # queue if no worker was started.
        busy = self._agent_running or self._shell_running
        if not busy and self._pending_messages:
            await self._process_next_from_queue()

    async def _cleanup_agent_task(self) -> None:
        """Clean up after agent task completes or is cancelled."""
        self._agent_running = False
        self._agent_worker = None

        # Remove spinner if present
        await self._set_spinner(None)

        if self._chat_input:
            self._chat_input.set_cursor_active(active=True)

        # Ensure token display is restored (in case of early cancellation).
        # Pass the cached approximate flag so an interrupted "+" isn't clobbered.
        self._show_tokens(approximate=self._tokens_approximate)

        try:
            await self._maybe_drain_deferred()
        except Exception:
            logger.exception("Failed to drain deferred actions during agent cleanup")
            with suppress(Exception):
                await self._mount_message(
                    ErrorMessage(
                        "A deferred action failed after task completion. You may need to retry the operation."
                    )
                )

        # Process next message from queue if any
        await self._process_next_from_queue()

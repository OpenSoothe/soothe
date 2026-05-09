"""Startup, server/daemon workers, skills, prewarm, and update check mixin."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_cli.tui.app._app import DaemonReady, ServerReady, ServerStartFailed
    from soothe_cli.tui.skills.load import ExtendedSkillMetadata

from textual.containers import VerticalScroll
from textual.css.query import NoMatches

from soothe_cli.tui._version import CHANGELOG_URL
from soothe_cli.tui.app._module_init import (
    TextualSessionState,
)
from soothe_cli.tui.config import is_ascii_mode
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


class _StartupMixin:
    """Startup, server/daemon workers, skills discovery, prewarm and update methods."""

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
        chat.anchor()
        if is_ascii_mode():
            chat.styles.scrollbar_size_vertical = 0

        self._status_bar = self.query_one("#status-bar", StatusBar)
        self._chat_input = self.query_one("#input-area", ChatInput)

        # Set initial auto-approve state
        if self._auto_approve:
            self._status_bar.set_auto_approve(enabled=True)

        # Focus the input immediately so the cursor is visible on first paint
        self._chat_input.focus_input()

        # Prewarm heavy imports in a thread while the first frame renders.
        # The user can't type yet, so GIL contention is harmless.  By the
        # time _post_paint_init fires its inline imports are dict lookups.
        self.run_worker(
            asyncio.to_thread(self._prewarm_deferred_imports),
            exclusive=True,
            group="startup-import-prewarm",
        )

        # Start branch resolution immediately — the thread launches now
        # (during on_mount) so by the time the first frame finishes painting
        # the subprocess is already done. _post_paint_init fires the heavier
        # workers (server, model creation) afterward.
        self._startup_task = asyncio.create_task(self._resolve_git_branch_and_continue())

    async def _resolve_git_branch_and_continue(self) -> None:
        """Resolve git branch, then schedule remaining init workers.

        Launched via `asyncio.create_task()` during `on_mount` so the subprocess
        runs concurrently with first-paint rendering. `_post_paint_init` is
        scheduled via `call_after_refresh` regardless of whether branch
        resolution succeeds.
        """
        try:
            import subprocess  # noqa: S404  # stdlib, already loaded

            def _get_branch() -> str:
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
                        capture_output=True,
                        text=True,
                        timeout=2,
                        check=False,
                    )
                    if result.returncode == 0:
                        return result.stdout.strip()
                except FileNotFoundError:
                    pass  # git not installed
                except subprocess.TimeoutExpired:
                    logger.debug("Git branch detection timed out")
                except OSError:
                    logger.debug("Git branch detection failed", exc_info=True)
                return ""

            branch = await asyncio.to_thread(_get_branch)
            if self._status_bar:
                self._status_bar.branch = branch
        except Exception:
            logger.warning("Git branch resolution failed", exc_info=True)
        finally:
            # Always schedule post-paint init — even if branch resolution
            # fails, the app must still start the server, session, etc.
            self.call_after_refresh(self._post_paint_init)

    async def _post_paint_init(self) -> None:
        """Fire background workers for remaining startup work.

        Everything here is non-blocking: workers and thread-offloaded calls
        so the UI stays responsive.
        """
        # Create UI adapter unconditionally — it only holds UI callbacks and
        # doesn't depend on the agent. The agent is injected later at
        # execute_task_textual() call time.
        from soothe_cli.tui.textual_adapter import TextualUIAdapter

        self._ui_adapter = TextualUIAdapter(
            mount_message=self._mount_message,
            update_status=self._update_status,
            request_approval=self._request_approval,
            on_auto_approve_enabled=self._on_auto_approve_enabled,
            set_spinner=self._set_spinner,
            set_active_message=self._set_active_message,
            sync_message_content=self._sync_message_content,
            request_ask_user=self._request_ask_user,
        )
        # Wire token display callbacks
        self._ui_adapter._on_tokens_update = self._on_tokens_update
        self._ui_adapter._on_tokens_hide = self._hide_tokens
        self._ui_adapter._on_tokens_show = self._show_tokens

        # Seed static slash commands now that the first frame has rendered.
        # Skill commands are appended later when _discover_skills() completes.
        self._apply_slash_command_autocomplete()

        # Fire-and-forget workers — none of these block the event loop.

        # Discover skills on the local machine when not using a daemon backend.
        # Daemon-backed sessions load skill metadata from the daemon instead.
        if self._daemon_config is None:
            self.run_worker(
                self._discover_skills(),
                exclusive=True,
                group="startup-skill-discovery",
            )

        self.run_worker(self._init_session_state, exclusive=True, group="session-init")

        # Daemon-backed TUI startup
        if self._daemon_config is not None:
            self.run_worker(
                self._connect_daemon_background,
                exclusive=True,
                group="daemon-connect",
            )

        # Server startup (model creation + server process)
        if self._server_kwargs is not None:
            self.run_worker(
                self._start_server_background,
                exclusive=True,
                group="server-startup",
            )

        # Background update check and what's-new banner
        # (opt-out via env var or config.yml [update].check)
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

        # Prewarm model discovery and profile caches unconditionally so
        # /model opens instantly even before the agent/server is ready.
        self.run_worker(
            self._prewarm_model_caches,
            exclusive=True,
            group="startup-model-prewarm",
        )

        # Prewarm thread message counts so /threads opens instantly.
        self.run_worker(
            self._prewarm_threads_cache,
            exclusive=True,
            group="startup-thread-prewarm",
        )

        # Auto-submit initial prompt or skill if provided via -m / --skill.
        # This check must come first because _lc_loop_id and _agent are
        # always set (even for brand-new sessions), so an elif after the
        # thread-history branch would never execute.
        # When connecting, defer until the ready message handler fires.
        # NOTE: _schedule_initial_submission() has a side effect (queues a
        # task via call_after_refresh); short-circuit ensures it only runs
        # when not connecting — the deferred path handles the connecting case.
        if (
            not self._connecting
            and not self._schedule_initial_submission()
            and self._lc_loop_id
            and self._runtime_backend_ready()
        ):
            self.call_after_refresh(lambda: asyncio.create_task(self._load_thread_history()))

    async def _init_session_state(self) -> None:
        """Create session state in a thread (imports soothe.sessions)."""

        def _create() -> TextualSessionState:
            return TextualSessionState(
                auto_approve=self._auto_approve,
                loop_id=self._lc_loop_id,
            )

        try:
            self._session_state = await asyncio.to_thread(_create)
        except Exception:
            logger.exception("Failed to create session state")
            self.notify(
                "Session initialization failed. Some features may be unavailable.",
                severity="error",
                timeout=10,
            )

    async def _discover_skills(self) -> None:
        """Discover skills from daemon RPC, cache metadata, and update autocomplete.

        Fetches wire-safe skill metadata via daemon WebSocket RPC and caches
        it for autocomplete and skill list display.
        """
        try:
            from soothe_cli.tui.skills.invocation import discover_skills_async

            skills = await discover_skills_async(daemon_config=self._daemon_config)
            self._discovered_skills = skills
            self._apply_slash_command_autocomplete()
            if skills and not self._chat_input:
                logger.debug(
                    "Skill discovery completed (%d skills) but chat input not yet mounted; autocomplete deferred",
                    len(skills),
                )
        except Exception:
            self._discovered_skills = []
            logger.exception("Unexpected error during skill discovery")
            self.notify(
                "Skill discovery failed. /skill: commands may not work. Check logs for details.",
                severity="warning",
                timeout=8,
                markup=False,
            )
            self._apply_slash_command_autocomplete()

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
        lines.append("Top-level alias: `/remember` (same as `/skill:remember`).")
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
        lines.append("Top-level alias: `/remember` (same as `/skill:remember`).")
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
            resp = await self._daemon_session.invoke_skill(skill_name, args)
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

    async def _resolve_resume_thread(self) -> None:
        """Resolve a `-r` resume intent into a concrete thread ID.

        Consumes `self._resume_thread_intent` and resolves it into a concrete
        thread ID. Mutates `self._lc_loop_id` and optionally
        `self._assistant_id` / `self._server_kwargs`. Falls back to a fresh
        thread on any DB error.
        """
        from soothe_cli.tui.sessions import (
            find_similar_threads,
            generate_loop_id,
            get_most_recent,
            get_thread_agent,
            thread_exists,
        )

        resume = self._resume_thread_intent
        self._resume_thread_intent = None  # consumed

        if not resume:
            return

        # Matches _DEFAULT_AGENT_NAME in main.py. Do NOT import it — main.py is
        # the CLI entry point and pulls in argparse, rich, etc. at module level.
        # Even a deferred import drags in the full dep tree for a single
        # string constant.
        default_agent = "agent"

        try:
            if resume == "__MOST_RECENT__":
                agent_filter = self._assistant_id if self._assistant_id != default_agent else None
                thread_id = await get_most_recent(agent_filter)
                if thread_id:
                    agent_name = await get_thread_agent(thread_id)
                    if agent_name:
                        self._assistant_id = agent_name
                        if self._server_kwargs:
                            self._server_kwargs["assistant_id"] = agent_name
                    self._lc_loop_id = thread_id
                else:
                    self._lc_loop_id = generate_loop_id()
                    if agent_filter:
                        msg = f"No previous threads for '{agent_filter}', starting new."
                    else:
                        msg = "No previous threads, starting new."
                    self.notify(msg, severity="warning", markup=False)
            elif await thread_exists(resume):
                self._lc_loop_id = resume
                if self._assistant_id == default_agent:
                    agent_name = await get_thread_agent(resume)
                    if agent_name:
                        self._assistant_id = agent_name
                        if self._server_kwargs:
                            self._server_kwargs["assistant_id"] = agent_name
            else:
                # Thread not found — notify + fall back to new thread
                self._lc_loop_id = generate_loop_id()
                similar = await find_similar_threads(resume)
                hint = f"Thread '{resume}' not found."
                if similar:
                    hint += f" Did you mean: {', '.join(str(t) for t in similar)}?"
                self.notify(hint, severity="warning", timeout=6, markup=False)
        except Exception:
            logger.exception("Failed to resolve resume thread %r", resume)
            self._lc_loop_id = generate_loop_id()
            self.notify(
                "Could not look up thread history. Starting new session.",
                severity="warning",
            )

        # Update session state if ready (may still be initializing in a
        # concurrent worker)
        if self._session_state:
            self._session_state.loop_id = self._lc_loop_id

    async def _start_server_background(self) -> None:
        """Background worker: resolve resume-thread intent, start server + MCP preload.

        Also runs deferred model creation if `model_kwargs` was provided,
        so the langchain import + init doesn't block first paint.
        """
        # Phase 1: Resolve resume thread (if any) before server startup
        if self._resume_thread_intent:
            await self._resolve_resume_thread()

        # Run deferred model creation. settings.model_name / model_provider
        # are already set eagerly for the status bar display; this call
        # does the heavy langchain import + SDK init and may refine them
        # (e.g., context_limit from the model profile).
        if self._model_kwargs is not None:
            from soothe_cli.tui.config import create_model
            from soothe_cli.tui.model_config import ModelConfigError, save_recent_model

            try:
                result = create_model(**self._model_kwargs)
            except ModelConfigError as exc:
                self.post_message(self.ServerStartFailed(error=exc))
                return
            result.apply_to_settings()
            save_recent_model(f"{result.provider}:{result.model_name}")
            self._model_kwargs = None  # consumed

        from soothe_cli.tui.server_manager import start_server_and_get_agent

        coros: list[Any] = [start_server_and_get_agent(**self._server_kwargs)]  # type: ignore[arg-type]

        try:
            results = await asyncio.gather(*coros, return_exceptions=True)
        except Exception as exc:  # noqa: BLE001  # defensive catch around gather
            self.post_message(self.ServerStartFailed(error=exc))
            return

        server_result = results[0]
        if isinstance(server_result, BaseException):
            self.post_message(
                self.ServerStartFailed(
                    error=server_result
                    if isinstance(server_result, Exception)
                    else RuntimeError(str(server_result)),
                )
            )
            return

        agent, server_proc, _ = server_result

        # Assign immediately so the finally block in run_textual_app can
        # clean up the server even if the ServerReady message is never
        # processed (e.g. user quits during startup).
        self._server_proc = server_proc

        self.post_message(
            self.ServerReady(
                agent=agent,
                server_proc=server_proc,
                mcp_server_info=None,
            )
        )

    async def _connect_daemon_background(self) -> None:
        """Background worker: connect the TUI directly to the daemon."""
        if self._daemon_config is None:
            return

        try:
            from soothe_sdk.client import (
                is_daemon_live,
                websocket_url_from_config,
            )

            from soothe_cli.tui.daemon_session import TuiDaemonSession

            ws_url = websocket_url_from_config(self._daemon_config)

            # Check daemon status via WebSocket RPC (IG-174 Phase 1)
            daemon_live = await is_daemon_live(ws_url, timeout=5.0)

            if not daemon_live:
                # CLI does NOT control daemon start/stop per architectural separation (IG-174/IG-175)
                # Show helpful error message instead
                raise ConnectionError(
                    f"Soothe daemon not running at {ws_url}. "
                    f"Please start the daemon with: soothed start"
                )

            session = TuiDaemonSession(self._daemon_config, workspace=self._cwd)
            status_event = await session.connect(resume_loop_id=self._lc_loop_id)
        except Exception as exc:
            self.post_message(self.ServerStartFailed(error=exc))
            return

        self.post_message(self.DaemonReady(session=session, status_event=status_event))

    def on_soothe_app_server_ready(self, event: ServerReady) -> None:
        """Handle successful background server startup."""
        self._connecting = False
        self._agent = event.agent
        self._server_proc = event.server_proc
        self._mcp_server_info = event.mcp_server_info
        self._mcp_tool_count = sum(len(s.tools) for s in (event.mcp_server_info or []))

        # Update welcome banner to show ready state
        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.set_connected(self._mcp_tool_count)
        except NoMatches:
            logger.warning("Welcome banner not found during server ready transition")

        # Handle deferred initial prompt, skill, or thread history
        if not self._schedule_initial_submission() and (
            self._lc_loop_id and self._runtime_backend_ready()
        ):
            self.call_after_refresh(lambda: asyncio.create_task(self._load_thread_history()))

        # Drain deferred actions (e.g. model/thread switch queued during connection)
        # if the agent is not actively running. Wrapped in a helper so that
        # exceptions are logged rather than becoming unhandled task errors.
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

        # Drain any messages the user typed while the server was starting.
        # (If an initial submission exists, its cleanup path will drain the queue.)
        if self._pending_messages and not self._has_initial_submission():
            self.call_after_refresh(lambda: asyncio.create_task(self._process_next_from_queue()))

    def on_soothe_app_daemon_ready(self, event: DaemonReady) -> None:
        """Handle successful daemon bootstrap for the TUI."""
        self._connecting = False
        self._daemon_session = event.session
        self._agent = event.session

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
        except NoMatches:
            logger.warning("Welcome banner not found during daemon ready transition")

        # IG-228: Start background event reader if thread is already running
        thread_state = event.status_event.get("state", "")
        if thread_state == "running" and self._daemon_session is not None:
            logger.info(
                "Loop %s is running, starting background event reader",
                status_loop_id[:8] if status_loop_id else "?",
            )
            self.run_worker(
                self._consume_daemon_events_background(),
                exclusive=False,
                group="daemon-event-reader",
            )

        if not self._schedule_initial_submission() and self._lc_loop_id:
            self.call_after_refresh(lambda: asyncio.create_task(self._load_thread_history()))

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

    def on_soothe_app_server_start_failed(self, event: ServerStartFailed) -> None:
        """Handle background server startup failure."""
        self._connecting = False
        self._server_startup_error = f"{type(event.error).__name__}: {event.error}"
        logger.error("Server startup failed: %s", event.error, exc_info=event.error)
        # Update banner to show persistent failure state
        try:
            banner = self.query_one("#welcome-banner", WelcomeBanner)
            banner.set_failed(self._server_startup_error)
        except NoMatches:
            logger.warning("Welcome banner not found during server failure transition")

        # Discard any messages queued while the server was starting
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

        try:
            # Heavy third-party deps deferred from textual_adapter /
            # tool_display — hit on first message send and first tool
            # approval. Best-effort: missing optional deps should not block the
            # TUI from rendering.
            from langchain.agents.middleware.human_in_the_loop import (  # noqa: F401
                ApproveDecision,
            )
            from langchain_core.messages import AIMessage  # noqa: F401
            from langgraph.types import Command  # noqa: F401
            from soothe_sdk.client.config import DEFAULT_EXECUTE_TIMEOUT  # noqa: F401
        except Exception:
            logger.warning("Could not prewarm third-party imports", exc_info=True)

        # Markdown rendering stack — ~170 ms cold (textual._markdown pulls in
        # markdown_it, pygments, linkify_it — 438 modules).  Hit on first
        # SkillMessage compose() and first code-fence highlight.  Warming
        # here makes the first expand/Ctrl+O instant.
        import markdown_it  # noqa: F401
        from pygments.lexers import get_lexer_by_name as _get_lexer
        from textual.widgets import Markdown  # noqa: F401

        # Instantiate the Python lexer to populate Pygments' internal
        # lexer cache (~12 ms cold).  Python is the most common fence
        # language in skill bodies.
        _get_lexer("python")

        # Widgets deferred from app.py module level — a failure here indicates
        # a packaging or code bug (same as the block above), so we let
        # exceptions propagate.
        from soothe_cli.tui.widgets.approval import ApprovalMenu  # noqa: F401
        from soothe_cli.tui.widgets.ask_user import AskUserMenu  # noqa: F401
        from soothe_cli.tui.widgets.model_selector import (
            ModelSelectorScreen,  # noqa: F401
        )
        from soothe_cli.tui.widgets.thread_selector import (  # noqa: F401
            DeleteThreadConfirmScreen,
            ThreadSelectorScreen,
        )

    async def _prewarm_threads_cache(self) -> None:  # noqa: PLR6301  # Worker hook kept as instance method
        """Prewarm thread selector cache without blocking app startup."""
        from soothe_cli.tui.sessions import (
            get_thread_limit,
            prewarm_thread_message_counts_via_daemon_rpc,
        )

        if self._daemon_session is not None:
            await prewarm_thread_message_counts_via_daemon_rpc(
                daemon_session=self._daemon_session,
                limit=get_thread_limit(),
            )
        else:
            logger.debug("Skipping thread cache prewarm - no daemon session available")

    async def _prewarm_model_caches(self) -> None:
        """Prewarm model discovery and profile caches without blocking startup."""
        if self._daemon_config is not None and self._daemon_session is None:
            logger.debug("Skipping model cache prewarm - daemon session not ready")
            return
        try:
            from soothe_cli.tui.model_config import (
                get_available_models,
                get_model_profiles,
            )

            await asyncio.to_thread(get_available_models)
            await asyncio.to_thread(get_model_profiles, cli_override=self._profile_override)
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
        except Exception:
            logger.debug("Background update check failed", exc_info=True)
            return

        # Phase 2: auto-update or notify (failures surfaced to user)
        try:
            from soothe_cli.tui._version import __version__ as cli_version

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
                else:
                    cmd = upgrade_command()
                    self.notify(
                        f"Auto-update failed. Run manually: {cmd}",
                        severity="warning",
                        timeout=15,
                        markup=False,
                    )
            else:
                cmd = upgrade_command()
                self.notify(
                    f"Update available: v{latest} (current: v{cli_version}). "
                    f"Run: {cmd}\n\n"
                    f"Enable auto-updates: /auto-update",
                    severity="information",
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
                await self._mount_message(AppMessage("Already on the latest version."))
                return

            from soothe_cli.tui._version import __version__ as cli_version

            await self._mount_message(
                AppMessage(f"Update available: v{latest} (current: v{cli_version}). Upgrading...")
            )
            success, output = await perform_upgrade()
            if success:
                self._update_available = (False, None)
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

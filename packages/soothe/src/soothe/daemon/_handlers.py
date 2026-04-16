"""Client connection handling for the daemon (IG-110).

Heavy logic lives in ``message_router`` and ``query_engine``; this mixin wires
transport entrypoints and the input queue loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from soothe_sdk.protocol import decode, encode

from soothe.core.event_catalog import ERROR
from soothe.daemon._command_parser import _parse_autonomous_command_local

logger = logging.getLogger(__name__)

# Local command constants (no CLI dependency - IG-176)
_SLASH_COMMANDS_HELP = {
    "/exit": "Stop running thread (confirm) and exit TUI; daemon keeps running",
    "/quit": "Stop running thread (confirm) and exit TUI; daemon keeps running",
    "/detach": "Leave thread running (confirm) and exit TUI; daemon keeps running",
    "/autopilot <prompt>": "Run prompt in autonomous mode",
    "/cancel": "Cancel the current running job",
    "/plan": "Show current task plan",
    "/memory": "Show memory stats",
    "/policy": "Show active policy profile",
    "/history": "Show recent prompt history",
    "/config": "Show active configuration summary",
    "/help": "Show available commands",
    "/keymaps": "Show keyboard shortcuts",
    "/clear": "Clear the screen",
}

_KEYBOARD_SHORTCUTS_HELP = {
    "Ctrl+Q": "Quit TUI: Stop thread (confirm) and exit client",
    "Ctrl+D": "Detach TUI: Leave thread running (confirm) and exit client",
    "Ctrl+C": "Cancel running job, press twice within 1s to quit",
    "Ctrl+E": "Focus chat input",
    "Ctrl+Y": "Copy last message to clipboard",
}


class DaemonHandlersMixin:
    """Client connection handling and query execution mixin.

    Mixed into ``SootheDaemon`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Send a direct response to a specific client when possible."""
        try:
            session = (
                await self._session_manager.get_session(client_id)
                if isinstance(client_id, str)
                else None
            )
            if session is not None:
                await session.transport.send(session.transport_client, msg)
                return
            if hasattr(client_id, "writer"):
                await self._send(client_id, msg)
        except Exception:
            logger.debug("Failed to send direct response to client %r", client_id, exc_info=True)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        from soothe.daemon.server import _ClientConn

        client = _ClientConn(reader=reader, writer=writer)
        self._clients.append(client)
        logger.info("Client connected (total=%d)", len(self._clients))

        try:
            initial_state = (
                "running" if self._query_running else ("idle" if self._running else "stopped")
            )
            initial_msg = {
                "type": "status",
                "state": initial_state,
                "thread_id": "",
                "input_history": [],
            }

            client.writer.write(encode(initial_msg))
            client.writer.write(encode(self.daemon_ready_message()))
            await client.writer.drain()
        except Exception:
            logger.exception("Failed to send initial status to client")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = decode(line)
                if msg is None:
                    continue
                await self._message_router.dispatch(f"legacy:{id(client)}", msg)
        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            self._clients = [c for c in self._clients if c is not client]
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
            logger.info("Client disconnected (total=%d)", len(self._clients))

    async def _handle_client_message(self, client_id: str, msg: dict[str, Any]) -> None:
        """Handle a message from a client (WebSocket / HTTP transports)."""
        await self._message_router.dispatch(client_id, msg)

    async def _cancel_thread(self, thread_id: str) -> None:
        """Cancel a running thread (used by session disconnect)."""
        qe = getattr(self, "_query_engine", None)
        if qe is not None:
            await qe.cancel_thread(thread_id)

    async def _input_loop(self) -> None:
        """Process user input from clients in an infinite loop."""
        while self._running:
            try:
                msg = await self._current_input_queue.get()
            except asyncio.CancelledError:
                break

            msg_type = msg.get("type", "")
            try:
                if msg_type == "command":
                    cmd = msg.get("cmd", "")
                    if cmd in ("/exit", "/quit"):
                        logger.info(
                            "Received %s command - treating as client detach (daemon keeps running)",
                            cmd,
                        )
                        await self._broadcast({"type": "status", "state": "detached"})
                        continue
                    if cmd.strip().lower() == "/cancel":
                        if self._query_engine is not None:
                            await self._query_engine.cancel_current_query()
                        continue
                    await self._handle_command(cmd)
                elif msg_type == "input":
                    text = msg["text"]
                    if self._query_engine is not None:
                        mp = msg.get("model_params")
                        model_params = mp if isinstance(mp, dict) else None
                        raw_m = msg.get("model")
                        model_kw = (
                            raw_m.strip() if isinstance(raw_m, str) and raw_m.strip() else None
                        )
                        await self._query_engine.run_query(
                            text,
                            autonomous=bool(msg.get("autonomous", False)),
                            max_iterations=msg.get("max_iterations"),
                            subagent=msg.get("subagent"),
                            client_id=msg.get("client_id"),
                            interactive=bool(msg.get("interactive", False)),
                            model=model_kw,
                            model_params=model_params,
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Daemon input loop handler error")
                self._query_running = False
                await self._broadcast(
                    {
                        "type": "event",
                        "thread_id": self._runner.current_thread_id or "",
                        "namespace": [],
                        "mode": "custom",
                        "data": {"type": ERROR, "error": "Daemon failed to process input"},
                    }
                )
                await self._broadcast(
                    {
                        "type": "status",
                        "state": "idle",
                        "thread_id": self._runner.current_thread_id or "",
                    }
                )

    async def _handle_command(self, cmd: str) -> None:
        """Execute a slash command and broadcast structured data response."""
        import logging

        logger = logging.getLogger(__name__)

        cmd_lower = cmd.strip().lower()

        # Handle /clear locally
        if cmd_lower == "/clear":
            await self._broadcast({"type": "clear"})
            return

        # Handle /help and /keymaps - return command lists
        # These are defined locally in daemon to avoid CLI dependency
        if cmd_lower == "/help":
            await self._broadcast(
                {
                    "type": "command_response",
                    "command": "/help",
                    "data": {"commands": _SLASH_COMMANDS_HELP},
                }
            )
            return

        if cmd_lower == "/keymaps":
            await self._broadcast(
                {
                    "type": "command_response",
                    "command": "/keymaps",
                    "data": {"keymaps": _KEYBOARD_SHORTCUTS_HELP},
                }
            )
            return

        # Handle /autopilot - parse and send as special query
        if cmd_lower.startswith("/autopilot"):
            # Parse locally to avoid CLI dependency
            parsed = _parse_autonomous_command_local(cmd)
            if parsed:
                max_iter, prompt = parsed
                await self._run_query(
                    prompt,
                    autonomous=True,
                    max_iterations=max_iter,
                )
            else:
                await self._broadcast(
                    {
                        "type": "command_response",
                        "command": "/autopilot",
                        "error": "Invalid autopilot syntax. Usage: /autopilot [N] <prompt>",
                    }
                )
            return

        # Handle data-fetching commands
        try:
            if cmd_lower == "/plan":
                # Get current plan from runner
                plan = None
                if hasattr(self._runner, "_current_plan"):
                    plan = self._runner._current_plan
                plan_data = None
                if plan:
                    plan_data = {
                        "goal": plan.goal,
                        "reasoning": plan.reasoning,
                        "general_activity": plan.general_activity,
                        "steps": [
                            {
                                "description": step.description,
                                "status": step.status,
                                "depends_on": list(step.depends_on or []),
                                "current_activity": step.current_activity,
                            }
                            for step in plan.steps
                        ],
                    }
                await self._broadcast(
                    {
                        "type": "command_response",
                        "command": "/plan",
                        "data": {"plan": plan_data},
                    }
                )
                return

            if cmd_lower == "/memory":
                stats = await self._runner.memory_stats()
                await self._broadcast(
                    {
                        "type": "command_response",
                        "command": "/memory",
                        "data": {"memory_stats": stats},
                    }
                )
                return

            if cmd_lower == "/policy":
                policy_data = {
                    "profile": self._runner.config.protocols.policy.profile,
                    "planner_routing": self._runner.config.protocols.planner.routing,
                    "memory_backend": self._runner.config.protocols.memory.backend,
                }
                await self._broadcast(
                    {
                        "type": "command_response",
                        "command": "/policy",
                        "data": {"policy": policy_data},
                    }
                )
                return

            if cmd_lower == "/history":
                # Use per-thread input history
                history_data = []
                current_tid = self._runner.current_thread_id
                if current_tid and hasattr(self, "_thread_registry"):
                    st = self._thread_registry.get(current_tid)
                    if st and hasattr(st, "input_history"):
                        # Get recent history items
                        history_data = st.input_history.get_recent(10)
                await self._broadcast(
                    {
                        "type": "command_response",
                        "command": "/history",
                        "data": {"history": history_data},
                    }
                )
                return

            if cmd_lower == "/config":
                # Return config summary
                config_data = {
                    "providers": [
                        {"name": p.name, "models": list(p.models.keys()) if p.models else []}
                        for p in (self._runner.config.providers or [])
                    ],
                    "workspace_dir": str(self._runner.config.workspace_dir or ""),
                    "verbosity": str(self._runner.config.logging.verbosity),
                }
                await self._broadcast(
                    {
                        "type": "command_response",
                        "command": "/config",
                        "data": {"config": config_data},
                    }
                )
                return

            # Unknown command
            await self._broadcast(
                {
                    "type": "command_response",
                    "error": f"Unknown command: {cmd}",
                }
            )

        except Exception as exc:
            logger.exception(f"Command error: {cmd}")
            await self._broadcast(
                {
                    "type": "command_response",
                    "error": str(exc),
                }
            )

    async def _run_query(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        client_id: str | None = None,
        interactive: bool = False,
        model: str | None = None,
        model_params: dict | None = None,
    ) -> None:
        """Delegate to ``QueryEngine`` (keeps unit tests and legacy callers working)."""
        await self._query_engine.run_query(
            text,
            autonomous=autonomous,
            max_iterations=max_iterations,
            subagent=subagent,
            client_id=client_id,
            interactive=interactive,
            model=model,
            model_params=model_params,
        )

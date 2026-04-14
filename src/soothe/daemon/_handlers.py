"""Client connection handling for the daemon (IG-110).

Heavy logic lives in ``message_router`` and ``query_engine``; this mixin wires
transport entrypoints and the input queue loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from soothe.core.event_catalog import ERROR
from soothe.daemon.protocol import decode, encode

logger = logging.getLogger(__name__)


class DaemonHandlersMixin:
    """Client connection handling and query execution mixin.

    Mixed into ``SootheDaemon`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Send a direct response to a specific client when possible."""
        try:
            session = await self._session_manager.get_session(client_id) if isinstance(client_id, str) else None
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
            initial_state = "running" if self._query_running else ("idle" if self._running else "stopped")
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
                        logger.info("Received %s command - treating as client detach (daemon keeps running)", cmd)
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
                        await self._query_engine.run_query(
                            text,
                            autonomous=bool(msg.get("autonomous", False)),
                            max_iterations=msg.get("max_iterations"),
                            subagent=msg.get("subagent"),
                            client_id=msg.get("client_id"),
                            interactive=bool(msg.get("interactive", False)),
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
                    {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
                )

    async def _handle_command(self, cmd: str) -> None:
        """Execute a slash command and broadcast the response."""
        from io import StringIO

        from rich.console import Console

        from soothe.foundation.slash_commands import handle_slash_command

        if cmd.strip().lower() == "/clear":
            await self._broadcast({"type": "clear"})
            return

        output = StringIO()
        console = Console(file=output, force_terminal=False, width=120)

        # Use per-thread input history
        current_tid = self._runner.current_thread_id
        input_hist = None
        if current_tid and hasattr(self, "_thread_registry"):
            st = self._thread_registry.get(current_tid)
            if st:
                input_hist = st.input_history

        await handle_slash_command(
            cmd,
            self._runner,
            console,
            current_plan=None,
            thread_logger=self._thread_logger,
            input_history=input_hist,
        )

        response_text = output.getvalue()
        if response_text.strip():
            await self._broadcast(
                {
                    "type": "command_response",
                    "content": response_text,
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
    ) -> None:
        """Delegate to ``QueryEngine`` (keeps unit tests and legacy callers working)."""
        await self._query_engine.run_query(
            text,
            autonomous=autonomous,
            max_iterations=max_iterations,
            subagent=subagent,
            client_id=client_id,
            interactive=interactive,
        )

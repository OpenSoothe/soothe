"""Client connection handling for the daemon (IG-110).

Heavy logic lives in ``message_router`` and ``query_engine``; this mixin wires
transport entrypoints and the input queue loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import websockets.exceptions
from soothe.core.events import ERROR
from soothe_sdk.client.protocol import decode, encode

from soothe_daemon.protocol.router import (
    _coerce_loop_input_text,
    _queue_options_from_daemon_message,
)

# Import RPC command handlers (RFC-404)
from soothe_daemon.rpc import (
    _cmd_autopilot_dashboard,
    _cmd_cancel,
    _cmd_clear,
    _cmd_config,
    _cmd_detach,
    _cmd_exit,
    _cmd_history,
    _cmd_memory,
    _cmd_plan,
    _cmd_policy,
    _cmd_quit,
    _cmd_resume,
    _cmd_review,
    _cmd_thread,
    _handle_command_request,
    _send_command_response,
)

logger = logging.getLogger(__name__)


class DaemonHandlersMixin:
    """Client connection handling and query execution mixin.

    Mixed into ``SootheDaemon`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    # Attach RPC handlers to mixin (RFC-404)
    _handle_command_request = _handle_command_request
    _send_command_response = _send_command_response
    _cmd_clear = _cmd_clear
    _cmd_exit = _cmd_exit
    _cmd_quit = _cmd_quit
    _cmd_detach = _cmd_detach
    _cmd_cancel = _cmd_cancel
    _cmd_memory = _cmd_memory
    _cmd_policy = _cmd_policy
    _cmd_history = _cmd_history
    _cmd_config = _cmd_config
    _cmd_review = _cmd_review
    _cmd_plan = _cmd_plan
    _cmd_thread = _cmd_thread
    _cmd_resume = _cmd_resume
    _cmd_autopilot_dashboard = _cmd_autopilot_dashboard

    async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Send a direct response to a specific client when possible.

        Handles normal client disconnects gracefully without logging errors.
        """
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
        except websockets.exceptions.ConnectionClosedOK:
            # Normal disconnect (code 1000) - expected, no error logging
            logger.debug("Client %r disconnected normally", client_id)
        except (websockets.exceptions.ConnectionClosedError, ConnectionError):
            # Abnormal disconnect - log as warning without full traceback
            logger.debug("Client %r disconnected unexpectedly", client_id)
        except Exception:
            # Unexpected error - log with full traceback
            logger.debug("Failed to send direct response to client %r", client_id, exc_info=True)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        from soothe_daemon.server import _ClientConn

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

    async def _process_loop_input_message(self, loop_id: str, msg: dict[str, Any]) -> None:
        """Process one loop-scoped message from ``LoopInputDispatcher`` (IG-408).

        Supported ``msg["type"]`` values for user turns: ``input`` (normalized queue
        payload from ``loop_input`` RPC) or ``loop_input`` (wire-shaped dict with
        ``content``). Other types are ignored with a warning except ``command`` and
        ``command_request``, which are handled above.
        """
        from soothe_daemon.loop_isolation import bind_execution_thread_for_loop

        msg_type = msg.get("type", "")
        try:
            checkpoint_thread_id = await bind_execution_thread_for_loop(self, loop_id)
        except Exception as exc:
            logger.warning(
                "Failed to bind LangGraph checkpoint for loop %s: %s",
                loop_id,
                exc,
            )
            client_id = msg.get("client_id")
            if client_id:
                await self._send_client_message(
                    client_id,
                    {"type": "error", "code": "LOOP_CONTEXT", "message": str(exc)},
                )
            return

        try:
            if msg_type == "command":
                cmd = msg.get("cmd", "")
                if cmd in ("/exit", "/quit"):
                    logger.warning(
                        "Received %s in loop worker — should be handled in MessageRouter",
                        cmd,
                    )
                    return
                if cmd.strip().lower() == "/cancel":
                    if self._query_engine is not None:
                        await self._query_engine.cancel_loop(loop_id)
                    return
                logger.warning("Received legacy 'command' message in loop worker — ignoring")
                return
            if msg_type == "command_request":
                req = dict(msg)
                req.setdefault("loop_id", loop_id)
                await self._handle_command_request(req)
                return
            if msg_type not in ("input", "loop_input"):
                logger.warning(
                    "Loop worker ignoring unsupported queue message type=%r loop_id=%s",
                    msg_type,
                    loop_id[:16] if loop_id else "?",
                )
                return

            if msg_type == "loop_input":
                prompt_text = _coerce_loop_input_text(msg.get("content"))
                if prompt_text is None:
                    logger.warning(
                        "Loop worker loop_input missing usable content loop_id=%s",
                        loop_id[:16] if loop_id else "?",
                    )
                    return
            else:
                raw_text = msg.get("text")
                if not isinstance(raw_text, str):
                    logger.warning(
                        "Loop worker input missing str text loop_id=%s",
                        loop_id[:16] if loop_id else "?",
                    )
                    return
                prompt_text = raw_text

            if self._query_engine is not None:
                qo = _queue_options_from_daemon_message(msg)
                model_params = qo["model_params"]
                model_kw = qo["model"]
                intent_hint = qo["intent_hint"]
                raw_att = msg.get("attachments")
                attachments = raw_att if isinstance(raw_att, list) and raw_att else None
                await self._query_engine.run_query(
                    prompt_text,
                    loop_id=loop_id,
                    autonomous=qo["autonomous"],
                    max_iterations=qo["max_iterations"],
                    preferred_subagent=qo["preferred_subagent"],
                    client_id=msg.get("client_id"),
                    interactive=qo["interactive"],
                    model=model_kw,
                    model_params=model_params,
                    attachments=attachments,
                    checkpoint_thread_id=checkpoint_thread_id,
                    intent_hint=intent_hint,
                )
        except Exception:
            logger.exception("Daemon loop input handler error")
            self._query_running = False
            lid = str(loop_id or "").strip()
            if lid and self._query_engine is not None:
                qe = self._query_engine
                await self._broadcast(
                    qe._loop_scoped_client_message(
                        lid,
                        {
                            "type": "event",
                            "namespace": [],
                            "mode": "custom",
                            "data": {"type": ERROR, "error": "Daemon failed to process input"},
                        },
                    )
                )
                await self._broadcast(
                    qe._loop_scoped_client_message(lid, {"type": "status", "state": "idle"})
                )

    async def _run_query(
        self,
        text: str,
        *,
        loop_id: str | None = None,
        autonomous: bool = False,
        max_iterations: int | None = None,
        preferred_subagent: str | None = None,
        client_id: str | None = None,
        interactive: bool = False,
        model: str | None = None,
        model_params: dict | None = None,
        attachments: list[dict[str, str]] | None = None,
        checkpoint_thread_id: str | None = None,
    ) -> None:
        """Delegate to ``QueryEngine`` (keeps unit tests and legacy callers working)."""
        await self._query_engine.run_query(
            text,
            loop_id=loop_id,
            autonomous=autonomous,
            max_iterations=max_iterations,
            preferred_subagent=preferred_subagent,
            client_id=client_id,
            interactive=interactive,
            model=model,
            model_params=model_params,
            attachments=attachments,
            checkpoint_thread_id=checkpoint_thread_id,
        )

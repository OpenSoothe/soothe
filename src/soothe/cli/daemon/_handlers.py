"""Client connection handling, input processing, and query execution for daemon."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from soothe.cli.daemon.protocol import decode, encode
from soothe.cli.thread_logger import ThreadLogger

if TYPE_CHECKING:
    from soothe.cli.daemon.server import _ClientConn

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2


class DaemonHandlersMixin:
    """Client connection handling and query execution mixin.

    Mixed into ``SootheDaemon`` -- all ``self.*`` attributes are defined
    on the concrete class.
    """

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        from soothe.cli.daemon.server import _ClientConn

        client = _ClientConn(reader=reader, writer=writer)
        self._clients.append(client)
        logger.info("Client connected (total=%d)", len(self._clients))

        try:
            initial_state = "running" if self._query_running else ("idle" if self._running else "stopped")
            initial_msg = {
                "type": "status",
                "state": initial_state,
                "thread_id": self._runner.current_thread_id or "",
                "input_history": self._input_history.history[-100:],
            }

            client.writer.write(encode(initial_msg))
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
                await self._handle_client_message(client, msg)
        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            self._clients = [c for c in self._clients if c is not client]
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
            logger.info("Client disconnected (total=%d)", len(self._clients))

    async def _handle_client_message(
        self,
        client: _ClientConn,
        msg: dict[str, Any],
    ) -> None:
        msg_type = msg.get("type", "")
        if msg_type == "input":
            text = msg.get("text", "").strip()
            if text:
                max_iterations = msg.get("max_iterations")
                parsed_max: int | None = (
                    max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else None
                )
                await self._current_input_queue.put(
                    {
                        "type": "input",
                        "text": text,
                        "autonomous": bool(msg.get("autonomous", False)),
                        "max_iterations": parsed_max,
                    }
                )
        elif msg_type == "command":
            cmd = msg.get("cmd", "")
            await self._current_input_queue.put({"type": "command", "cmd": cmd})
        elif msg_type == "resume_thread":
            thread_id = msg.get("thread_id", "")
            if thread_id:
                self._runner.set_current_thread_id(thread_id)
                await self._broadcast(
                    {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
                )
        elif msg_type == "detach":
            await self._send(client, {"type": "status", "state": "detached"})
        else:
            logger.debug("Unknown client message type: %s", msg_type)

    # -- input processing loop -----------------------------------------------

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
                        await self._broadcast({"type": "status", "state": "stopping"})
                        self._running = False
                        if self._stop_event:
                            self._stop_event.set()
                        break
                    await self._handle_command(cmd)
                elif msg_type == "input":
                    text = msg["text"]
                    await self._run_query(
                        text,
                        autonomous=bool(msg.get("autonomous", False)),
                        max_iterations=msg.get("max_iterations"),
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Daemon input loop handler error")
                self._query_running = False
                await self._broadcast(
                    {
                        "type": "event",
                        "namespace": [],
                        "mode": "custom",
                        "data": {"type": "soothe.error", "error": "Daemon failed to process input"},
                    }
                )
                await self._broadcast(
                    {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
                )

    async def _handle_command(self, cmd: str) -> None:
        """Execute a slash command and broadcast the response.

        Args:
            cmd: The slash command to execute.
        """
        from io import StringIO

        from rich.console import Console

        from soothe.cli.slash_commands import handle_slash_command

        output = StringIO()
        console = Console(file=output, force_terminal=False, width=100)

        should_exit = await handle_slash_command(
            cmd,
            self._runner,
            console,
            current_plan=None,
            thread_logger=self._thread_logger,
            input_history=self._input_history,
        )

        response_text = output.getvalue()
        if response_text.strip():
            await self._broadcast(
                {
                    "type": "command_response",
                    "content": response_text,
                }
            )

        if should_exit:
            await self._broadcast({"type": "status", "state": "stopping"})
            self._running = False
            if self._stop_event:
                self._stop_event.set()

    async def _run_query(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
    ) -> None:
        """Stream a query through SootheRunner and broadcast events."""
        thread_id = self._runner.current_thread_id or ""

        if not self._thread_logger or self._thread_logger._thread_id != thread_id:
            self._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )

        if self._thread_logger:
            self._thread_logger.log_user_input(text)

        if self._input_history:
            self._input_history.add(text)

        self._query_running = True
        await self._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        full_response: list[str] = []

        try:
            stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
            if autonomous:
                stream_kwargs["autonomous"] = True
                if max_iterations is not None:
                    stream_kwargs["max_iterations"] = max_iterations
            async for chunk in self._runner.astream(text, **stream_kwargs):
                if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                    continue
                namespace, mode, data = chunk

                self._thread_logger.log(tuple(namespace), mode, data)

                is_msg_pair = isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                if not namespace and mode == "messages" and is_msg_pair:
                    msg, _metadata = data
                    from soothe.cli.tui_shared import extract_text_from_ai_message

                    full_response.extend(extract_text_from_ai_message(msg))

                event_msg = {
                    "type": "event",
                    "namespace": list(namespace),
                    "mode": mode,
                    "data": data,
                }
                await self._broadcast(event_msg)
        except asyncio.CancelledError:
            logger.info("Query cancelled during shutdown")
            raise
        except Exception as exc:
            logger.exception("Daemon query error")
            from soothe.utils.error_format import emit_error_event

            await self._broadcast(
                {
                    "type": "event",
                    "namespace": [],
                    "mode": "custom",
                    "data": emit_error_event(exc),
                }
            )
        finally:
            self._query_running = False

        final_thread_id = self._runner.current_thread_id or ""
        if final_thread_id and final_thread_id != thread_id:
            self._thread_logger = ThreadLogger(
                thread_id=final_thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )
            self._thread_logger.log_user_input(text)

        if full_response:
            self._thread_logger.log_assistant_response("".join(full_response))

        await self._broadcast({"type": "status", "state": "idle", "thread_id": final_thread_id})

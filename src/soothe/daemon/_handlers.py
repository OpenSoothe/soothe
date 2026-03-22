"""Client connection handling, input processing, and query execution for daemon."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from soothe.core.events import ERROR
from soothe.daemon.protocol import decode, encode
from soothe.daemon.thread_logger import ThreadLogger

if TYPE_CHECKING:
    from soothe.daemon.server import _ClientConn

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
        from soothe.daemon.server import _ClientConn

        client = _ClientConn(reader=reader, writer=writer)
        self._clients.append(client)
        logger.info("Client connected (total=%d)", len(self._clients))

        try:
            initial_state = "running" if self._query_running else ("idle" if self._running else "stopped")
            initial_msg = {
                "type": "status",
                "state": initial_state,
                "thread_id": "",  # Don't leak cached thread ID - client will request new/resume explicitly
                "input_history": [],  # Don't send history on initial connect - only when resuming
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
        client: _ClientConn | None,
        msg: dict[str, Any],
    ) -> None:
        """Handle a message from a client.

        Args:
            client: Client connection (None for messages from transport layer).
            msg: Message dict from the client.
        """
        msg_type = msg.get("type", "")
        if msg_type == "input":
            text = msg.get("text", "").strip()
            if text:
                max_iterations = msg.get("max_iterations")
                parsed_max: int | None = (
                    max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else None
                )
                subagent = msg.get("subagent")
                subagent = subagent.strip() or None if isinstance(subagent, str) else None
                await self._current_input_queue.put(
                    {
                        "type": "input",
                        "text": text,
                        "autonomous": bool(msg.get("autonomous", False)),
                        "max_iterations": parsed_max,
                        "subagent": subagent,
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
                    {
                        "type": "status",
                        "state": "idle",
                        "thread_id": self._runner.current_thread_id or "",
                        "thread_resumed": True,
                        "input_history": self._input_history.history[-100:] if self._input_history else [],
                    }
                )
        elif msg_type == "new_thread":
            # Clear the current thread ID to start a fresh thread
            self._runner.set_current_thread_id(None)
            await self._broadcast({"type": "status", "state": "idle", "thread_id": ""})
        elif msg_type == "detach":
            if client:
                await self._send(client, {"type": "status", "state": "detached"})
            else:
                await self._broadcast({"type": "status", "state": "detached"})
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
                    if cmd.strip().lower() == "/cancel":
                        await self._cancel_current_query()
                        continue
                    await self._handle_command(cmd)
                elif msg_type == "input":
                    text = msg["text"]
                    await self._run_query(
                        text,
                        autonomous=bool(msg.get("autonomous", False)),
                        max_iterations=msg.get("max_iterations"),
                        subagent=msg.get("subagent"),
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
                        "data": {"type": ERROR, "error": "Daemon failed to process input"},
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

        from soothe.ux.shared.slash_commands import handle_slash_command

        # Handle /clear command specially
        if cmd.strip().lower() == "/clear":
            await self._broadcast({"type": "clear"})
            return

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

    async def _cancel_current_query(self) -> None:
        """Cancel the currently running query if any."""
        if not self._query_running:
            await self._broadcast(
                {
                    "type": "command_response",
                    "content": "[yellow]No running query to cancel.[/yellow]",
                }
            )
            return

        if self._current_query_task and not self._current_query_task.done():
            logger.info("Cancelling current query task")
            self._current_query_task.cancel()

            # Wait for the task to actually be cancelled
            with contextlib.suppress(asyncio.CancelledError):
                await self._current_query_task

            self._query_running = False
            self._current_query_task = None

            await self._broadcast(
                {
                    "type": "command_response",
                    "content": "[green]Query cancelled successfully.[/green]",
                }
            )
            await self._broadcast(
                {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
            )
        else:
            await self._broadcast(
                {
                    "type": "command_response",
                    "content": "[yellow]No active query task found.[/yellow]",
                }
            )

    async def _run_query(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
    ) -> None:
        """Stream a query through SootheRunner and broadcast events.

        Args:
            text: The user input text.
            autonomous: Whether to run in autonomous mode.
            max_iterations: Maximum iterations for autonomous mode.
            subagent: Optional subagent name to route the query to.
        """
        thread_id = self._runner.current_thread_id or ""

        if not self._thread_logger or self._thread_logger._thread_id != thread_id:
            self._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )

        if self._thread_logger:
            self._thread_logger.log_user_input(text)

        # Update thread's updated_at timestamp
        await self._update_thread_timestamp(thread_id)

        if self._input_history:
            self._input_history.add(text)

        self._query_running = True
        await self._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        full_response: list[str] = []

        # Create task for cancellation support
        async def _run_stream() -> None:
            try:
                stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
                if autonomous:
                    stream_kwargs["autonomous"] = True
                    if max_iterations is not None:
                        stream_kwargs["max_iterations"] = max_iterations
                if subagent is not None:
                    stream_kwargs["subagent"] = subagent
                async for chunk in self._runner.astream(text, **stream_kwargs):
                    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                        continue
                    namespace, mode, data = chunk

                    self._thread_logger.log(tuple(namespace), mode, data)

                    is_msg_pair = isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                    if not namespace and mode == "messages" and is_msg_pair:
                        msg, _metadata = data
                        from soothe.ux.shared.rendering import extract_text_from_ai_message

                        full_response.extend(extract_text_from_ai_message(msg))

                    event_msg = {
                        "type": "event",
                        "namespace": list(namespace),
                        "mode": mode,
                        "data": data,
                    }
                    await self._broadcast(event_msg)
            except asyncio.CancelledError:
                logger.info("Query cancelled by user")
                await self._broadcast(
                    {
                        "type": "event",
                        "namespace": [],
                        "mode": "custom",
                        "data": {"type": ERROR, "error": "Query cancelled by user"},
                    }
                )
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

        try:
            self._current_query_task = asyncio.create_task(_run_stream())
            await self._current_query_task
        except asyncio.CancelledError:
            logger.info("Query task cancelled")
        finally:
            self._current_query_task = None

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

        # Update thread's updated_at timestamp for final response
        if final_thread_id:
            await self._update_thread_timestamp(final_thread_id)

        await self._broadcast({"type": "status", "state": "idle", "thread_id": final_thread_id})

    async def _update_thread_timestamp(self, thread_id: str) -> None:
        """Update the thread's updated_at timestamp to track activity."""
        if not thread_id or not hasattr(self._runner, "_durability"):
            return

        try:
            from datetime import UTC, datetime

            # Load current thread info
            thread_data = self._runner._durability._store.load(f"thread:{thread_id}")
            if thread_data:
                from soothe.protocols.durability import ThreadInfo

                thread_info = ThreadInfo.model_validate(thread_data)
                # Update timestamp
                thread_info = thread_info.model_copy(update={"updated_at": datetime.now(UTC)})
                self._runner._durability._store.save(f"thread:{thread_id}", thread_info.model_dump(mode="json"))
                logger.debug("Thread %s updated_at refreshed", thread_id)
        except Exception:
            logger.debug("Failed to update thread timestamp", exc_info=True)

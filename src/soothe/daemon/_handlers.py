"""Client connection handling, input processing, and query execution for daemon."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from soothe.core.event_catalog import CHITCHAT_RESPONSE, ERROR, FINAL_REPORT
from soothe.daemon.protocol import decode, encode
from soothe.daemon.thread_logger import InputHistory, ThreadLogger
from soothe.safety import validate_client_workspace

logger = logging.getLogger(__name__)

_STREAM_CHUNK_LENGTH = 3
_MSG_PAIR_LENGTH = 2


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
                "thread_id": "",  # Don't leak cached thread ID - client will request new/resume explicitly
                "input_history": [],  # Don't send history on initial connect - only when resuming
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
        client_id: str,
        msg: dict[str, Any],
    ) -> None:
        """Handle a message from a client.

        Args:
            client_id: Unique client identifier (never None).
            msg: Message dict from the client.
        """
        msg_type = msg.get("type", "")
        if msg_type == "input":
            text = msg.get("text", "").strip()
            if text:
                multi_threading_enabled = getattr(self._config.daemon, "multi_threading_enabled", False)
                # Check if daemon is busy: check both _active_threads and _query_running for compatibility
                has_active_threads = hasattr(self, "_active_threads") and bool(self._active_threads)
                has_active_query = has_active_threads or self._query_running
                if has_active_query and not multi_threading_enabled:
                    await self._send_client_message(
                        client_id,
                        {
                            "type": "error",
                            "code": "DAEMON_BUSY",
                            "message": (
                                "Daemon is already processing another query. "
                                "Wait for it to finish or cancel it before starting a new one."
                            ),
                            "thread_id": self._runner.current_thread_id if self._runner else "",
                        },
                    )
                    return

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
                        "client_id": client_id,  # RFC-0013: track query ownership
                    }
                )
        elif msg_type == "command":
            cmd = msg.get("cmd", "")
            await self._current_input_queue.put({"type": "command", "cmd": cmd})
        elif msg_type == "resume_thread":
            thread_id = msg.get("thread_id", "")
            client_workspace = msg.get("workspace")

            logger.info("Received resume_thread request for thread_id=%r from client=%s", thread_id, client_id)

            if client_workspace:
                try:
                    validated = validate_client_workspace(client_workspace)
                    logger.info(
                        "Client workspace %s provided for resume, thread will use persisted workspace",
                        validated,
                    )
                except ValueError as e:
                    logger.warning("Invalid client workspace on resume: %s", e)

            if thread_id:
                from soothe.core.thread import ThreadContextManager

                try:
                    manager = ThreadContextManager(
                        self._runner._durability, self._config, getattr(self._runner, "_context", None)
                    )
                    # Capture thread_info to get the resolved full thread_id
                    # (supports partial prefix matching in durability layer)
                    thread_info = await manager.resume_thread(str(thread_id))
                    resumed_thread_id = thread_info.thread_id
                    logger.info("resume_thread: resolved %r -> %s", thread_id, resumed_thread_id)
                    self._runner.set_current_thread_id(resumed_thread_id)

                    # Initialize thread logger for the resumed thread
                    self._thread_logger = ThreadLogger(
                        thread_id=resumed_thread_id,
                        retention_days=self._config.logging.thread_logging.retention_days,
                        max_size_mb=self._config.logging.thread_logging.max_size_mb,
                    )

                    # Load conversation history for display in TUI
                    conversation_history = self._thread_logger.recent_conversation(limit=50)

                    # Clear draft state if resuming an existing thread
                    self._draft_thread_id = None

                    # Send status directly to requesting client (not broadcast - no subscribers yet)
                    session = await self._session_manager.get_session(client_id)
                    logger.info("resume_thread: session for client %s = %s", client_id, session is not None)
                    if session:
                        await session.transport.send(
                            session.transport_client,
                            {
                                "type": "status",
                                "state": "idle",
                                "thread_id": resumed_thread_id,
                                "thread_resumed": True,
                                "input_history": self._input_history.history[-100:] if self._input_history else [],
                                "conversation_history": conversation_history,
                            },
                        )
                    logger.info("Resumed thread %s", resumed_thread_id)
                except KeyError as e:
                    logger.warning("resume_thread: KeyError for %r: %s", thread_id, e)
                    session = await self._session_manager.get_session(client_id)
                    if session:
                        await session.transport.send(
                            session.transport_client,
                            {
                                "type": "error",
                                "code": "THREAD_NOT_FOUND",
                                "message": f"Thread {thread_id} not found",
                            },
                        )
        elif msg_type == "daemon_ready":
            await self._send_client_message(client_id, self.daemon_ready_message())
        elif msg_type == "new_thread":
            # Extract workspace from client
            client_workspace = msg.get("workspace")
            if client_workspace:
                try:
                    thread_workspace = validate_client_workspace(client_workspace)
                    logger.info(
                        "Client %s requested workspace: %s",
                        client_id[:8],
                        thread_workspace,
                    )
                except ValueError as e:
                    logger.warning("Invalid client workspace: %s, using daemon default", e)
                    thread_workspace = self._daemon_workspace
            else:
                # No workspace provided, use daemon default
                thread_workspace = self._daemon_workspace

            # Start a fresh thread - create draft thread ID without persisting yet
            from soothe.core.runner._types import _generate_thread_id

            # Generate a draft thread ID (12-char alphanumeric)
            draft_thread_id = _generate_thread_id()

            # Track as draft (not persisted until first message)
            self._draft_thread_id = draft_thread_id
            self._runner.set_current_thread_id(draft_thread_id)

            # Store workspace for this thread (will be persisted on first input)
            if not hasattr(self, "_thread_workspaces"):
                self._thread_workspaces = {}
            self._thread_workspaces[draft_thread_id] = thread_workspace

            # Initialize input history for the draft thread
            self._input_history = InputHistory()

            # Send status directly to requesting client (not broadcast - no subscribers yet)
            session = await self._session_manager.get_session(client_id)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "status",
                        "state": "idle",
                        "thread_id": draft_thread_id,
                        "new_thread": True,
                        "workspace": str(thread_workspace),
                        "input_history": [],
                    },
                )
            logger.info("Created new thread %s with workspace %s", draft_thread_id, thread_workspace)
        # Thread management handlers (RFC-0017)
        elif msg_type == "thread_list":
            await self._handle_thread_list(msg)
        elif msg_type == "thread_create":
            await self._handle_thread_create(msg)
        elif msg_type == "thread_get":
            await self._handle_thread_get(msg)
        elif msg_type == "thread_archive":
            await self._handle_thread_archive(msg)
        elif msg_type == "thread_delete":
            await self._handle_thread_delete(msg)
        elif msg_type == "thread_messages":
            await self._handle_thread_messages(msg)
        elif msg_type == "thread_artifacts":
            await self._handle_thread_artifacts(msg)
        elif msg_type == "detach":
            # RFC-0013: Set detach_requested flag so remove_session doesn't auto-cancel
            session = await self._session_manager.get_session(client_id)
            if session:
                session.detach_requested = True
            await self._send_client_message(client_id, {"type": "status", "state": "detached"})
            logger.info("Client %s requested detach - query will continue after disconnect", client_id)
        elif msg_type == "subscribe_thread":
            thread_id = msg.get("thread_id", "").strip()
            verbosity = msg.get("verbosity", "normal")  # RFC-0022: optional, default='normal'

            if not thread_id:
                session = await self._session_manager.get_session(client_id)
                if session:
                    await session.transport.send(
                        session.transport_client,
                        {"type": "error", "code": "INVALID_MESSAGE", "message": "subscribe_thread requires thread_id"},
                    )
                return

            # Validate verbosity value (RFC-0022)
            valid_verbosity = {"quiet", "minimal", "normal", "detailed", "debug"}
            if verbosity not in valid_verbosity:
                session = await self._session_manager.get_session(client_id)
                if session:
                    await session.transport.send(
                        session.transport_client,
                        {
                            "type": "error",
                            "code": "INVALID_MESSAGE",
                            "message": f"Invalid verbosity value: {verbosity}. "
                            f"Must be one of: {', '.join(sorted(valid_verbosity))}",
                        },
                    )
                return

            try:
                # Subscribe with verbosity preference (RFC-0022)
                await self._session_manager.subscribe_thread(client_id, thread_id, verbosity=verbosity)

                # Send confirmation with echoed verbosity
                session = await self._session_manager.get_session(client_id)
                if session:
                    await session.transport.send(
                        session.transport_client,
                        {
                            "type": "subscription_confirmed",
                            "thread_id": thread_id,
                            "client_id": client_id,
                            "verbosity": verbosity,  # RFC-0022: echo verbosity
                        },
                    )
                logger.info(
                    "Client %s subscribed to thread %s with verbosity=%s",
                    client_id,
                    thread_id,
                    verbosity,
                )
            except ValueError as e:
                logger.exception("Subscription failed")
                session = await self._session_manager.get_session(client_id)
                if session:
                    await session.transport.send(
                        session.transport_client,
                        {
                            "type": "error",
                            "code": "SUBSCRIPTION_FAILED",
                            "message": str(e),
                        },
                    )
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
                        # IG-085 (RFC-0013): Treat /exit and /quit as client detach
                        # Daemon should NOT stop - only explicit 'soothe daemon stop' shuts down daemon
                        logger.info("Received %s command - treating as client detach (daemon keeps running)", cmd)
                        await self._broadcast({"type": "status", "state": "detached"})
                        # Do NOT set self._running = False
                        # Do NOT break - daemon continues running
                        continue
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
                        client_id=msg.get("client_id"),  # RFC-0013: pass for ownership tracking
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

    async def _handle_thread_list(self, msg: dict[str, Any]) -> None:
        """Handle thread_list message.

        Args:
            msg: Message dict with optional filter and include_stats.
        """
        from soothe.core.thread import ThreadContextManager, ThreadFilter

        filter_data = msg.get("filter")
        thread_filter = None
        if filter_data:
            thread_filter = ThreadFilter(**filter_data)

        include_stats = msg.get("include_stats", False)
        include_last_message = msg.get("include_last_message", True)  # Default to True

        # Create ThreadContextManager
        manager = ThreadContextManager(self._runner._durability, self._config, getattr(self._runner, "_context", None))

        threads = await manager.list_threads(
            thread_filter,
            include_stats=include_stats,
            include_last_message=include_last_message,
        )

        await self._broadcast(
            {
                "type": "thread_list_response",
                "threads": [t.model_dump(mode="json") for t in threads],
                "total": len(threads),
            }
        )

    async def _handle_thread_create(self, msg: dict[str, Any]) -> None:
        """Handle thread_create message.

        Args:
            msg: Message dict with optional initial_message and metadata.
        """
        from soothe.core.thread import ThreadContextManager

        initial_message = msg.get("initial_message")
        metadata = msg.get("metadata")

        # Create ThreadContextManager
        manager = ThreadContextManager(self._runner._durability, self._config, getattr(self._runner, "_context", None))

        thread_info = await manager.create_thread(
            initial_message=initial_message,
            metadata=metadata,
        )

        await self._broadcast(
            {
                "type": "thread_created",
                "thread_id": thread_info.thread_id,
                "status": thread_info.status,
            }
        )

    async def _handle_thread_get(self, msg: dict[str, Any]) -> None:
        """Handle thread_get message.

        Args:
            msg: Message dict with thread_id.
        """
        from soothe.core.thread import ThreadContextManager

        thread_id = msg["thread_id"]

        try:
            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            thread = await manager.get_thread(thread_id)
            await self._broadcast(
                {
                    "type": "thread_get_response",
                    "thread": thread.model_dump(mode="json"),
                }
            )
        except KeyError:
            await self._broadcast(
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                }
            )

    async def _handle_thread_archive(self, msg: dict[str, Any]) -> None:
        """Handle thread_archive message.

        Args:
            msg: Message dict with thread_id.
        """
        from soothe.core.thread import ThreadContextManager

        thread_id = msg["thread_id"]

        try:
            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            await manager.archive_thread(thread_id)
            await self._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "archive",
                    "thread_id": thread_id,
                    "success": True,
                    "message": "Thread archived successfully",
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "archive",
                    "thread_id": thread_id,
                    "success": False,
                    "message": str(e),
                }
            )

    async def _handle_thread_delete(self, msg: dict[str, Any]) -> None:
        """Handle thread_delete message.

        Args:
            msg: Message dict with thread_id.
        """
        from soothe.core.thread import ThreadContextManager

        thread_id = msg["thread_id"]

        try:
            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            await manager.delete_thread(thread_id)
            await self._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "delete",
                    "thread_id": thread_id,
                    "success": True,
                    "message": "Thread deleted successfully",
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "delete",
                    "thread_id": thread_id,
                    "success": False,
                    "message": str(e),
                }
            )

    async def _handle_thread_messages(self, msg: dict[str, Any]) -> None:
        """Handle thread_messages message.

        Args:
            msg: Message dict with thread_id, optional limit and offset.
        """
        from soothe.core.thread import ThreadContextManager

        thread_id = msg["thread_id"]
        limit = msg.get("limit", 100)
        offset = msg.get("offset", 0)

        try:
            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            messages = await manager.get_thread_messages(
                thread_id,
                limit=limit,
                offset=offset,
            )
            await self._broadcast(
                {
                    "type": "thread_messages_response",
                    "thread_id": thread_id,
                    "messages": [m.model_dump(mode="json") for m in messages],
                    "limit": limit,
                    "offset": offset,
                }
            )
        except KeyError:
            await self._broadcast(
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                }
            )

    async def _handle_thread_artifacts(self, msg: dict[str, Any]) -> None:
        """Handle thread_artifacts message.

        Args:
            msg: Message dict with thread_id.
        """
        from soothe.core.thread import ThreadContextManager

        thread_id = msg["thread_id"]

        try:
            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            artifacts = await manager.get_thread_artifacts(thread_id)
            await self._broadcast(
                {
                    "type": "thread_artifacts_response",
                    "thread_id": thread_id,
                    "artifacts": [a.model_dump(mode="json") for a in artifacts],
                }
            )
        except KeyError:
            await self._broadcast(
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                }
            )

    async def _handle_command(self, cmd: str) -> None:
        """Execute a slash command and broadcast the response.

        Args:
            cmd: The slash command to execute.
        """
        from io import StringIO

        from rich.console import Console

        from soothe.ux.tui.commands import handle_slash_command

        # Handle /clear command specially
        if cmd.strip().lower() == "/clear":
            await self._broadcast({"type": "clear"})
            return

        output = StringIO()
        console = Console(file=output, force_terminal=False, width=120)

        # IG-085: Return value no longer used to stop daemon
        # /exit and /quit commands now just detach client, not stop daemon
        # Daemon should only stop via explicit 'soothe daemon stop'
        await handle_slash_command(
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

    async def _cancel_current_query(self) -> None:
        """Cancel the currently running query if any.

        Silently ignores cancellation requests when no query is running.
        The TUI handles the UX for this case (IG-053).
        """
        if not self._query_running:
            # Silently ignore - TUI will handle the UX
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
                    "content": "[green]Query cancelled.[/green]",
                }
            )
            await self._broadcast(
                {"type": "status", "state": "idle", "thread_id": self._runner.current_thread_id or ""}
            )

    async def _run_query(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        client_id: str | None = None,
    ) -> None:
        """Stream a query through SootheRunner and broadcast events.

        Supports both single-threaded and multi-threaded execution based on configuration.

        Args:
            text: The user input text.
            autonomous: Whether to run in autonomous mode.
            max_iterations: Maximum iterations for autonomous mode.
            subagent: Optional subagent name to route the query to.
            client_id: Optional client ID for thread ownership tracking (RFC-0013).
        """
        # Check if multi-threading is enabled (RFC-0017)
        multi_threading_enabled = getattr(self._config.daemon, "multi_threading_enabled", False)

        if multi_threading_enabled and self._thread_executor:
            # Use multi-threaded execution with ThreadExecutor
            await self._run_query_multithreaded(
                text,
                autonomous=autonomous,
                max_iterations=max_iterations,
                subagent=subagent,
                client_id=client_id,
            )
            return

        # Single-threaded execution
        thread_id = await self._ensure_active_thread_id()

        # Persist draft thread on first message
        if self._draft_thread_id and self._draft_thread_id == thread_id:
            from soothe.core.thread import ThreadContextManager

            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            # Persist the draft thread with its existing ID (not a new UUID)
            thread_info = await manager.create_thread(thread_id=self._draft_thread_id)
            # The thread_id should remain the same since we passed it explicitly
            actual_thread_id = thread_info.thread_id

            # No need to migrate subscriptions since thread_id stays the same
            # Just clear the draft flag
            logger.info("Persisted draft thread %s", actual_thread_id)
            self._draft_thread_id = None

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

        # Use lock to ensure atomic state transition
        query_state_lock = getattr(self, "_query_state_lock", None)
        if query_state_lock:
            async with query_state_lock:
                self._query_running = True
                # Register in _active_threads for consistent tracking
                self._active_threads[thread_id] = None  # Placeholder, will set task below
        else:
            self._query_running = True

        await self._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        # RFC-0013: Claim thread ownership for cancel-on-disconnect
        if client_id:
            await self._session_manager.claim_thread_ownership(client_id, thread_id)

        full_response: list[str] = []

        async def _run_stream() -> None:
            chunk_count = 0  # Track chunks inside the function
            try:
                stream_kwargs: dict[str, Any] = {"thread_id": thread_id}
                if autonomous:
                    stream_kwargs["autonomous"] = True
                    if max_iterations is not None:
                        stream_kwargs["max_iterations"] = max_iterations
                if subagent is not None:
                    stream_kwargs["subagent"] = subagent
                logger.debug("Starting runner.astream() for thread %s", thread_id)
                async for chunk in self._runner.astream(text, **stream_kwargs):
                    chunk_count += 1
                    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
                        logger.debug("Skipping invalid chunk #%d: type=%s", chunk_count, type(chunk).__name__)
                        continue
                    namespace, mode, data = chunk
                    logger.debug("Received chunk #%d: namespace=%s, mode=%s", chunk_count, namespace, mode)

                    self._thread_logger.log(tuple(namespace), mode, data)

                    if (
                        not namespace
                        and mode == "custom"
                        and isinstance(data, dict)
                        and (output_text := self._extract_custom_output_text(data))
                    ):
                        full_response.append(output_text)

                    is_msg_pair = isinstance(data, (tuple, list)) and len(data) == _MSG_PAIR_LENGTH
                    if not namespace and mode == "messages" and is_msg_pair:
                        msg, _metadata = data
                        from soothe.ux.core.rendering import extract_text_from_ai_message

                        full_response.extend(extract_text_from_ai_message(msg))

                    event_msg = {
                        "type": "event",
                        "thread_id": thread_id,
                        "namespace": list(namespace),
                        "mode": mode,
                        "data": data,
                    }
                    await self._broadcast(event_msg)
                logger.debug("runner.astream() completed, total chunks: %d", chunk_count)
            except asyncio.CancelledError:
                logger.info("Query cancelled by user")
                await self._broadcast(
                    {
                        "type": "event",
                        "thread_id": thread_id,
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
                        "thread_id": thread_id,
                        "namespace": [],
                        "mode": "custom",
                        "data": emit_error_event(exc),
                    }
                )
            finally:
                # Clear state in finally block - this runs even on cancellation
                self._query_running = False
                # Remove from _active_threads if present
                if hasattr(self, "_active_threads"):
                    self._active_threads.pop(thread_id, None)

        try:
            task = asyncio.create_task(_run_stream())
            self._current_query_task = task
            # Also register in _active_threads for consistent tracking
            self._active_threads[thread_id] = task
            await task
        except asyncio.CancelledError:
            logger.info("Query task cancelled")
        finally:
            self._current_query_task = None
            # RFC-0013: Release thread ownership on query completion
            if client_id:
                await self._session_manager.release_thread_ownership(client_id)

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

        completion_thread_id = thread_id or final_thread_id
        await self._broadcast({"type": "status", "state": "idle", "thread_id": completion_thread_id})

    async def _run_query_multithreaded(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        client_id: str | None = None,
    ) -> None:
        """Execute query using ThreadExecutor for concurrent thread execution.

        Args:
            text: The user input text.
            autonomous: Whether to run in autonomous mode.
            max_iterations: Maximum iterations for autonomous mode.
            subagent: Optional subagent name to route the query to.
            client_id: Optional client ID for thread ownership tracking (RFC-0013).
        """
        thread_id = await self._ensure_active_thread_id()

        # Persist draft thread on first message (same as _run_query)
        if self._draft_thread_id and self._draft_thread_id == thread_id:
            from soothe.core.thread import ThreadContextManager

            manager = ThreadContextManager(
                self._runner._durability, self._config, getattr(self._runner, "_context", None)
            )
            # Persist the draft thread with its existing ID (not a new UUID)
            thread_info = await manager.create_thread(thread_id=self._draft_thread_id)
            # The thread_id should remain the same since we passed it explicitly
            actual_thread_id = thread_info.thread_id

            # No need to migrate subscriptions since thread_id stays the same
            # Just clear the draft flag
            logger.info("Persisted draft thread %s", actual_thread_id)
            self._draft_thread_id = None

        # Initialize thread logger
        if not self._thread_logger or self._thread_logger._thread_id != thread_id:
            self._thread_logger = ThreadLogger(
                thread_id=thread_id,
                retention_days=self._config.logging.thread_logging.retention_days,
                max_size_mb=self._config.logging.thread_logging.max_size_mb,
            )

        if self._thread_logger:
            self._thread_logger.log_user_input(text)

        # Update thread timestamp
        await self._update_thread_timestamp(thread_id)

        if self._input_history:
            self._input_history.add(text)

        # Mark thread as running
        self._query_running = True
        if hasattr(self, "_active_threads"):
            self._active_threads[thread_id] = asyncio.current_task()
        await self._broadcast({"type": "status", "state": "running", "thread_id": thread_id})

        # RFC-0013: Claim thread ownership for cancel-on-disconnect
        if client_id:
            await self._session_manager.claim_thread_ownership(client_id, thread_id)

        full_response: list[str] = []

        try:
            # Build kwargs for runner.astream (excluding thread_id which is positional)
            stream_kwargs: dict[str, Any] = {}
            if autonomous:
                stream_kwargs["autonomous"] = True
                if max_iterations is not None:
                    stream_kwargs["max_iterations"] = max_iterations
            if subagent is not None:
                stream_kwargs["subagent"] = subagent

            # Use ThreadExecutor for concurrent execution with rate limiting
            # execute_thread signature: execute_thread(thread_id, user_input, **kwargs)
            stream_tuple_length = 3
            msg_pair_length = 2
            async for chunk in self._thread_executor.execute_thread(thread_id, text, **stream_kwargs):
                if not isinstance(chunk, tuple) or len(chunk) != stream_tuple_length:
                    continue
                namespace, mode, data = chunk

                # Log to thread-specific logger
                self._thread_logger.log(tuple(namespace), mode, data)

                if (
                    not namespace
                    and mode == "custom"
                    and isinstance(data, dict)
                    and (output_text := self._extract_custom_output_text(data))
                ):
                    full_response.append(output_text)

                # Extract response text
                is_msg_pair = isinstance(data, (tuple, list)) and len(data) == msg_pair_length
                if not namespace and mode == "messages" and is_msg_pair:
                    msg, _metadata = data
                    from soothe.ux.core.rendering import extract_text_from_ai_message

                    full_response.extend(extract_text_from_ai_message(msg))

                # Broadcast event to clients
                event_msg = {
                    "type": "event",
                    "thread_id": thread_id,
                    "namespace": list(namespace),
                    "mode": mode,
                    "data": data,
                }
                await self._broadcast(event_msg)

        except asyncio.CancelledError:
            logger.info("Query cancelled by user in thread %s", thread_id)
            await self._broadcast(
                {
                    "type": "event",
                    "thread_id": thread_id,
                    "namespace": [],
                    "mode": "custom",
                    "data": {"type": ERROR, "error": f"Query cancelled in thread {thread_id}"},
                }
            )
            raise
        except Exception as exc:
            logger.exception("Multi-threaded query error in thread %s", thread_id)
            from soothe.utils.error_format import emit_error_event

            await self._broadcast(
                {
                    "type": "event",
                    "thread_id": thread_id,
                    "namespace": [],
                    "mode": "custom",
                    "data": emit_error_event(exc),
                }
            )
        finally:
            self._query_running = False
            if hasattr(self, "_active_threads"):
                self._active_threads.pop(thread_id, None)
            # RFC-0013: Release thread ownership on query completion
            if client_id:
                await self._session_manager.release_thread_ownership(client_id)

        # Log final response
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

        # Update final timestamp
        if final_thread_id:
            await self._update_thread_timestamp(final_thread_id)

        completion_thread_id = thread_id or final_thread_id
        await self._broadcast({"type": "status", "state": "idle", "thread_id": completion_thread_id})

    async def _cancel_thread(self, thread_id: str) -> None:
        """Cancel a specific thread's execution.

        Uses _query_state_lock to ensure atomic state transitions.
        Awaits task cancellation to ensure cleanup completes before returning.

        Args:
            thread_id: Thread ID to cancel.
        """
        # Use lock to ensure atomic state transitions
        query_state_lock = getattr(self, "_query_state_lock", None)
        if query_state_lock:
            async with query_state_lock:
                await self._cancel_thread_locked(thread_id)
        else:
            # Fallback if lock not available (shouldn't happen)
            await self._cancel_thread_locked(thread_id)

    async def _cancel_thread_locked(self, thread_id: str) -> None:
        """Internal method to cancel thread while holding state lock.

        Args:
            thread_id: Thread ID to cancel.
        """
        # Check _active_threads first (works for both single and multi-threaded mode)
        if hasattr(self, "_active_threads") and thread_id in self._active_threads:
            task = self._active_threads.pop(thread_id, None)
            if task and not task.done():
                task.cancel()
                logger.info("Cancelled thread %s", thread_id)
                # Await task cancellation to ensure cleanup completes
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            # Clear legacy state flags for consistency
            self._query_running = False
            self._current_query_task = None
            await self._broadcast(
                {
                    "type": "status",
                    "state": "idle",
                    "thread_id": thread_id,
                    "cancelled": True,
                }
            )
            return

        # Fallback: check _current_query_task (legacy single-threaded mode)
        if self._current_query_task and not self._current_query_task.done():
            current_thread = self._runner.current_thread_id if self._runner else None
            if current_thread == thread_id:
                self._current_query_task.cancel()
                logger.info("Cancelled thread %s (legacy single-threaded mode)", thread_id)
                # Await task cancellation
                with contextlib.suppress(asyncio.CancelledError):
                    await self._current_query_task
                # Clear all state
                self._query_running = False
                self._current_query_task = None
                await self._broadcast({"type": "status", "state": "idle", "thread_id": thread_id})
                return

        logger.debug("Thread %s not found or already complete", thread_id)

    def _get_active_threads(self) -> list[str]:
        """Get list of currently active thread IDs.

        Returns:
            List of thread IDs currently executing.
        """
        if hasattr(self, "_active_threads"):
            return list(self._active_threads.keys())
        return []

    @staticmethod
    def _extract_custom_output_text(data: dict[str, Any]) -> str | None:
        """Extract assistant-visible output text from custom protocol events."""
        from soothe.ux.core.message_processing import strip_internal_tags

        event_type = str(data.get("type", ""))
        if event_type == CHITCHAT_RESPONSE:
            content = data.get("content", "")
            cleaned = strip_internal_tags(str(content))
            return cleaned or None
        if event_type == FINAL_REPORT:
            content = data.get("summary", "")
            cleaned = strip_internal_tags(str(content))
            return cleaned or None
        return None

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

    async def _ensure_active_thread_id(self) -> str:
        """Ensure current query runs with a concrete thread ID."""
        current = str(self._runner.current_thread_id or "").strip()
        if current:
            return current

        from soothe.core.thread import ThreadContextManager

        manager = ThreadContextManager(self._runner._durability, self._config, getattr(self._runner, "_context", None))
        thread_info = await manager.create_thread()
        self._runner.set_current_thread_id(thread_info.thread_id)
        return thread_info.thread_id

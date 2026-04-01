"""Transport message dispatch for the daemon (IG-110).

Maps JSON message types to handlers using ``SootheRunner`` public APIs instead
of reaching into ``runner._durability``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe.core.runner._types import _generate_thread_id
from soothe.core.workspace import validate_client_workspace
from soothe.logging import InputHistory, ThreadLogger

logger = logging.getLogger(__name__)

_CLIENT_LABEL_LEN = 8


def _client_label(client_id: Any) -> str:
    """Short label for logs when ``client_id`` may be a legacy connection object."""
    if isinstance(client_id, str):
        return client_id[:_CLIENT_LABEL_LEN] if len(client_id) >= _CLIENT_LABEL_LEN else client_id
    return f"obj:{id(client_id) & 0xFFFF_FFFF:x}"


class MessageRouter:
    """Dispatches client messages by ``type`` field."""

    def __init__(self, daemon: Any) -> None:
        """Keep a reference to the daemon for config, runner, and session access."""
        self._daemon = daemon

    async def dispatch(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle a single client message."""
        d = self._daemon
        msg_type = msg.get("type", "")
        logger.debug("[IG-110] Received message type=%s from client=%s", msg_type, _client_label(client_id))

        if msg_type == "input":
            text = msg.get("text", "").strip()
            if text:
                multi_threading_enabled = getattr(d._config.daemon, "multi_threading_enabled", False)
                has_active_threads = bool(d._active_threads)
                has_active_query = has_active_threads or d._query_running
                if has_active_query and not multi_threading_enabled:
                    await d._send_client_message(
                        client_id,
                        {
                            "type": "error",
                            "code": "DAEMON_BUSY",
                            "message": (
                                "Daemon is already processing another query. "
                                "Wait for it to finish or cancel it before starting a new one."
                            ),
                            "thread_id": d._runner.current_thread_id if d._runner else "",
                        },
                    )
                    return

                max_iterations = msg.get("max_iterations")
                parsed_max: int | None = (
                    max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else None
                )
                subagent = msg.get("subagent")
                subagent = subagent.strip() or None if isinstance(subagent, str) else None
                logger.debug("[IG-110] Putting input in queue: text=%s, client=%s", text[:30], _client_label(client_id))
                await d._current_input_queue.put(
                    {
                        "type": "input",
                        "text": text,
                        "autonomous": bool(msg.get("autonomous", False)),
                        "max_iterations": parsed_max,
                        "subagent": subagent,
                        "client_id": client_id,
                    }
                )
                logger.debug("[IG-110] Input put in queue successfully")
            return

        if msg_type == "command":
            cmd = msg.get("cmd", "")
            await d._current_input_queue.put({"type": "command", "cmd": cmd})
            return

        if msg_type == "resume_thread":
            await self._handle_resume_thread(client_id, msg)
            return

        if msg_type == "daemon_ready":
            await d._send_client_message(client_id, d.daemon_ready_message())
            return

        if msg_type == "new_thread":
            await self._handle_new_thread(client_id, msg)
            return

        if msg_type == "thread_list":
            await self._handle_thread_list(msg)
            return
        if msg_type == "thread_create":
            await self._handle_thread_create(msg)
            return
        if msg_type == "thread_get":
            await self._handle_thread_get(msg)
            return
        if msg_type == "thread_archive":
            await self._handle_thread_archive(msg)
            return
        if msg_type == "thread_delete":
            await self._handle_thread_delete(msg)
            return
        if msg_type == "thread_messages":
            await self._handle_thread_messages(msg)
            return
        if msg_type == "thread_artifacts":
            await self._handle_thread_artifacts(msg)
            return

        if msg_type == "detach":
            session = await d._session_manager.get_session(client_id)
            if session:
                session.detach_requested = True
            await d._send_client_message(client_id, {"type": "status", "state": "detached"})
            logger.info("Client %s requested detach - query will continue after disconnect", client_id)
            return

        if msg_type == "subscribe_thread":
            await self._handle_subscribe_thread(client_id, msg)
            return

        logger.debug("Unknown client message type: %s", msg_type)

    async def _handle_resume_thread(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
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

        if not thread_id:
            return

        try:
            thread_info = await d._runner.resume_persisted_thread(str(thread_id))
            resumed_thread_id = thread_info.thread_id
            logger.info("resume_thread: resolved %r -> %s", thread_id, resumed_thread_id)
            d._runner.set_current_thread_id(resumed_thread_id)

            d._thread_registry.set_client_thread(client_id, resumed_thread_id)
            reg = d._thread_registry.ensure(resumed_thread_id, is_draft=False)
            reg.thread_logger = ThreadLogger(
                thread_id=resumed_thread_id,
                retention_days=d._config.logging.thread_logging.retention_days,
                max_size_mb=d._config.logging.thread_logging.max_size_mb,
            )
            d._thread_logger = reg.thread_logger

            conversation_history = d._thread_logger.recent_conversation(limit=50)

            session = await d._session_manager.get_session(client_id)
            logger.info("resume_thread: session for client %s = %s", client_id, session is not None)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "status",
                        "state": "idle",
                        "thread_id": resumed_thread_id,
                        "thread_resumed": True,
                        "input_history": d._input_history.history[-100:] if d._input_history else [],
                        "conversation_history": conversation_history,
                    },
                )
            logger.info("Resumed thread %s", resumed_thread_id)
        except KeyError as e:
            logger.warning("resume_thread: KeyError for %r: %s", thread_id, e)
            session = await d._session_manager.get_session(client_id)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "error",
                        "code": "THREAD_NOT_FOUND",
                        "message": f"Thread {thread_id} not found",
                    },
                )

    async def _handle_new_thread(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        client_workspace = msg.get("workspace")
        if client_workspace:
            try:
                thread_workspace = validate_client_workspace(client_workspace)
                logger.info(
                    "Client %s requested workspace: %s",
                    _client_label(client_id),
                    thread_workspace,
                )
            except ValueError as e:
                logger.warning("Invalid client workspace: %s, using daemon default", e)
                thread_workspace = d._daemon_workspace
        else:
            thread_workspace = d._daemon_workspace

        draft_thread_id = _generate_thread_id()
        d._thread_registry.ensure(draft_thread_id, is_draft=True)
        d._thread_registry.set_workspace(draft_thread_id, Path(thread_workspace))
        d._thread_registry.set_client_thread(client_id, draft_thread_id)
        d._runner.set_current_thread_id(draft_thread_id)

        d._input_history = InputHistory()

        session = await d._session_manager.get_session(client_id)
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

    async def _handle_thread_list(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        from soothe.core.thread import ThreadFilter

        filter_data = msg.get("filter")
        thread_filter = None
        if filter_data:
            thread_filter = ThreadFilter(**filter_data)

        include_stats = msg.get("include_stats", False)
        include_last_message = msg.get("include_last_message", True)

        threads = await d._runner.list_persisted_threads(
            thread_filter,
            include_stats=include_stats,
            include_last_message=include_last_message,
        )

        await d._broadcast(
            {
                "type": "thread_list_response",
                "threads": [t.model_dump(mode="json") for t in threads],
                "total": len(threads),
            }
        )

    async def _handle_thread_create(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        initial_message = msg.get("initial_message")
        metadata = msg.get("metadata")

        thread_info = await d._runner.create_persisted_thread(
            initial_message=initial_message,
            metadata=metadata,
        )

        await d._broadcast(
            {
                "type": "thread_created",
                "thread_id": thread_info.thread_id,
                "status": thread_info.status,
            }
        )

    async def _handle_thread_get(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            thread = await d._runner.get_persisted_thread(thread_id)
            await d._broadcast(
                {
                    "type": "thread_get_response",
                    "thread": thread.model_dump(mode="json"),
                }
            )
        except KeyError:
            await d._broadcast(
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                }
            )

    async def _handle_thread_archive(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            await d._runner.archive_persisted_thread(thread_id)
            await d._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "archive",
                    "thread_id": thread_id,
                    "success": True,
                    "message": "Thread archived successfully",
                }
            )
        except Exception as e:
            await d._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "archive",
                    "thread_id": thread_id,
                    "success": False,
                    "message": str(e),
                }
            )

    async def _handle_thread_delete(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            await d._runner.delete_persisted_thread(thread_id)
            d._thread_registry.remove(thread_id)
            await d._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "delete",
                    "thread_id": thread_id,
                    "success": True,
                    "message": "Thread deleted successfully",
                }
            )
        except Exception as e:
            await d._broadcast(
                {
                    "type": "thread_operation_ack",
                    "operation": "delete",
                    "thread_id": thread_id,
                    "success": False,
                    "message": str(e),
                }
            )

    async def _handle_thread_messages(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]
        limit = msg.get("limit", 100)
        offset = msg.get("offset", 0)

        try:
            messages = await d._runner.get_persisted_thread_messages(
                thread_id,
                limit=limit,
                offset=offset,
            )
            await d._broadcast(
                {
                    "type": "thread_messages_response",
                    "thread_id": thread_id,
                    "messages": [m.model_dump(mode="json") for m in messages],
                    "limit": limit,
                    "offset": offset,
                }
            )
        except KeyError:
            await d._broadcast(
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                }
            )

    async def _handle_thread_artifacts(self, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            artifacts = await d._runner.get_persisted_thread_artifacts(thread_id)
            await d._broadcast(
                {
                    "type": "thread_artifacts_response",
                    "thread_id": thread_id,
                    "artifacts": [a.model_dump(mode="json") for a in artifacts],
                }
            )
        except KeyError:
            await d._broadcast(
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                }
            )

    async def _handle_subscribe_thread(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg.get("thread_id", "").strip()
        verbosity = msg.get("verbosity", "normal")

        if not thread_id:
            session = await d._session_manager.get_session(client_id)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {"type": "error", "code": "INVALID_MESSAGE", "message": "subscribe_thread requires thread_id"},
                )
            return

        valid_verbosity = {"quiet", "minimal", "normal", "detailed", "debug"}
        if verbosity not in valid_verbosity:
            session = await d._session_manager.get_session(client_id)
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
            await d._session_manager.subscribe_thread(client_id, thread_id, verbosity=verbosity)

            session = await d._session_manager.get_session(client_id)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "subscription_confirmed",
                        "thread_id": thread_id,
                        "client_id": client_id,
                        "verbosity": verbosity,
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
            session = await d._session_manager.get_session(client_id)
            if session:
                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "error",
                        "code": "SUBSCRIPTION_FAILED",
                        "message": str(e),
                    },
                )

"""Transport message dispatch for the daemon (IG-110).

Maps JSON message types to handlers using ``SootheRunner`` public APIs instead
of reaching into ``runner._durability``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe_sdk.langchain_wire import messages_from_wire_dicts

from soothe.core.runner._types import _generate_thread_id
from soothe.core.workspace import validate_client_workspace
from soothe.logging import ThreadLogger
from soothe.utils.text_preview import preview_first

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
        logger.debug(
            "[MsgRouter] Received message type=%s from client=%s",
            msg_type,
            _client_label(client_id),
        )

        if msg_type == "input":
            text = msg.get("text", "").strip()
            if text:
                # IG-054: Capacity check moved to query_engine.py to eliminate race
                # between checking len(_active_threads) and actually creating the task
                max_iterations = msg.get("max_iterations")
                parsed_max: int | None = (
                    max_iterations
                    if isinstance(max_iterations, int) and max_iterations > 0
                    else None
                )
                subagent = msg.get("subagent")
                subagent = subagent.strip() or None if isinstance(subagent, str) else None
                raw_model = msg.get("model")
                model = (
                    raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
                )
                raw_params = msg.get("model_params")
                model_params = raw_params if isinstance(raw_params, dict) else None
                logger.debug(
                    "[MsgRouter] Putting input in queue: text=%s, client=%s",
                    preview_first(text, 30),
                    _client_label(client_id),
                )
                await d._current_input_queue.put(
                    {
                        "type": "input",
                        "text": text,
                        "autonomous": bool(msg.get("autonomous", False)),
                        "max_iterations": parsed_max,
                        "subagent": subagent,
                        "client_id": client_id,
                        "interactive": bool(msg.get("interactive", False)),
                        "model": model,
                        "model_params": model_params,
                    }
                )
                logger.debug("[MsgRouter] Input put in queue successfully")
            return

        if msg_type == "command":
            cmd = msg.get("cmd", "")
            normalized = cmd.strip().lower()
            # IG-161: These must not go through _current_input_queue — the loop is blocked
            # inside await run_query() until the stream ends, so queued commands would not
            # run until too late (same as /cancel).
            if normalized in ("/exit", "/quit"):
                logger.info(
                    "Received %s via router — treating as client detach (daemon keeps running)",
                    normalized,
                )
                await d._broadcast({"type": "status", "state": "detached"})
                return
            if normalized == "/cancel" and getattr(d, "_query_engine", None) is not None:
                await d._query_engine.cancel_current_query()
                return
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
            await self._handle_thread_list(client_id, msg)
            return
        if msg_type == "thread_create":
            await self._handle_thread_create(client_id, msg)
            return
        if msg_type == "thread_get":
            await self._handle_thread_get(client_id, msg)
            return
        if msg_type == "thread_archive":
            await self._handle_thread_archive(client_id, msg)
            return
        if msg_type == "thread_delete":
            await self._handle_thread_delete(client_id, msg)
            return
        if msg_type == "thread_messages":
            await self._handle_thread_messages(client_id, msg)
            return
        if msg_type == "thread_artifacts":
            await self._handle_thread_artifacts(client_id, msg)
            return
        if msg_type == "thread_status":
            await self._handle_thread_status(client_id, msg)
            return
        if msg_type == "thread_state":
            await self._handle_thread_state(client_id, msg)
            return
        if msg_type == "thread_update_state":
            await self._handle_thread_update_state(client_id, msg)
            return
        if msg_type == "resume_interrupts":
            await self._handle_resume_interrupts(client_id, msg)
            return

        # Loop RPC handlers (RFC-504 Loop Management CLI Commands)
        if msg_type == "loop_list":
            await self._handle_loop_list(client_id, msg)
            return
        if msg_type == "loop_get":
            await self._handle_loop_get(client_id, msg)
            return
        if msg_type == "loop_tree":
            await self._handle_loop_tree(client_id, msg)
            return
        if msg_type == "loop_prune":
            await self._handle_loop_prune(client_id, msg)
            return
        if msg_type == "loop_delete":
            await self._handle_loop_delete(client_id, msg)
            return
        if msg_type == "loop_reattach":
            await self._handle_loop_reattach(client_id, msg)
            return

        # Loop lifecycle RPC handlers (RFC-503 Loop-First UX)
        if msg_type == "loop_subscribe":
            await self._handle_loop_subscribe(client_id, msg)
            return
        if msg_type == "loop_detach":
            await self._handle_loop_detach(client_id, msg)
            return
        if msg_type == "loop_new":
            await self._handle_loop_new(client_id, msg)
            return
        if msg_type == "loop_input":
            await self._handle_loop_input(client_id, msg)
            return

        if msg_type == "detach":
            session = await d._session_manager.get_session(client_id)
            if session:
                session.detach_requested = True
            await d._send_client_message(client_id, {"type": "status", "state": "detached"})
            logger.info(
                "Client %s requested detach - query will continue after disconnect", client_id
            )
            return

        if msg_type == "subscribe_thread":
            await self._handle_subscribe_thread(client_id, msg)
            return

        if msg_type == "skills_list":
            await self._handle_skills_list(client_id, msg)
            return

        if msg_type == "invoke_skill":
            await self._handle_invoke_skill(client_id, msg)
            return

        if msg_type == "models_list":
            await self._handle_models_list(client_id, msg)
            return

        # IG-174 Phase 0: Daemon RPC endpoints
        if msg_type == "daemon_status":
            await self._handle_daemon_status(client_id, msg)
            return

        if msg_type == "daemon_shutdown":
            await self._handle_daemon_shutdown(client_id, msg)
            return

        if msg_type == "config_get":
            await self._handle_config_get(client_id, msg)
            return

        logger.debug("Unknown client message type: %s", msg_type)

    async def _handle_resume_thread(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg.get("thread_id", "")
        client_workspace = msg.get("workspace")

        logger.info(
            "Received resume_thread request for thread_id=%r from client=%s", thread_id, client_id
        )

        validated_resume_ws: Path | None = None
        if client_workspace:
            try:
                validated_resume_ws = validate_client_workspace(client_workspace)
                logger.info("Resume with client workspace: %s", validated_resume_ws)
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
            if validated_resume_ws is not None:
                d._thread_registry.set_workspace(resumed_thread_id, validated_resume_ws)
            elif d._thread_registry.get_workspace(resumed_thread_id) is None:
                d._thread_registry.set_workspace(resumed_thread_id, Path(d._daemon_workspace))
            reg.thread_logger = ThreadLogger(
                thread_id=resumed_thread_id,
                retention_days=d._config.logging.thread_logging.retention_days,
                max_size_mb=d._config.logging.thread_logging.max_size_mb,
            )
            d._thread_logger = reg.thread_logger

            conversation_history = d._thread_logger.recent_conversation(limit=50)

            # Get global cross-thread input history for TUI
            global_history_list = []
            if d._global_history:
                global_history_list = d._global_history.get_recent(limit=100)

            # IG-228: Check if thread is actively running in background (after detach)
            is_active = resumed_thread_id in d._active_threads
            thread_status = "running" if is_active else "idle"

            session = await d._session_manager.get_session(client_id)
            logger.info("resume_thread: session for client %s = %s", client_id, session is not None)
            if session:
                # Subscribe client to thread events if thread is running
                # Avoid duplicate subscription if client already subscribed via bootstrap
                if is_active and resumed_thread_id not in session.subscriptions:
                    try:
                        await d._session_manager.subscribe_thread(
                            client_id, resumed_thread_id, verbosity=session.verbosity
                        )
                        logger.info(
                            "Client %s subscribed to active thread %s",
                            client_id,
                            resumed_thread_id,
                        )
                        # Send subscription confirmation so client bootstrap completes
                        await session.transport.send(
                            session.transport_client,
                            {
                                "type": "subscription_confirmed",
                                "thread_id": resumed_thread_id,
                                "client_id": client_id,
                                "verbosity": session.verbosity,
                            },
                        )
                    except Exception:
                        logger.warning(
                            "Failed to subscribe client %s to active thread %s",
                            client_id,
                            resumed_thread_id,
                            exc_info=True,
                        )

                await session.transport.send(
                    session.transport_client,
                    {
                        "type": "status",
                        "state": thread_status,
                        "thread_id": resumed_thread_id,
                        "thread_resumed": True,
                        "input_history": global_history_list,
                        "conversation_history": conversation_history,
                    },
                )
            logger.info("Resumed thread %s (status=%s)", resumed_thread_id, thread_status)
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

        # Get global cross-thread input history for TUI
        global_history_list = []
        if d._global_history:
            global_history_list = d._global_history.get_recent(limit=100)

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
                    "input_history": global_history_list,
                },
            )
        logger.info("Created new thread %s with workspace %s", draft_thread_id, thread_workspace)

    async def _handle_thread_list(self, client_id: str, msg: dict[str, Any]) -> None:
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

        await d._send_client_message(
            client_id,
            {
                "type": "thread_list_response",
                "threads": [t.model_dump(mode="json") for t in threads],
                "total": len(threads),
                "request_id": msg.get("request_id"),
            },
        )

    async def _handle_thread_create(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        initial_message = msg.get("initial_message")
        metadata = msg.get("metadata")

        thread_info = await d._runner.create_persisted_thread(
            initial_message=initial_message,
            metadata=metadata,
        )

        await d._send_client_message(
            client_id,
            {
                "type": "thread_created",
                "thread_id": thread_info.thread_id,
                "status": thread_info.status,
                "request_id": msg.get("request_id"),
            },
        )

    async def _handle_thread_get(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            thread = await d._runner.get_persisted_thread(thread_id)
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_get_response",
                    "thread": thread.model_dump(mode="json"),
                    "request_id": msg.get("request_id"),
                },
            )
        except KeyError:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                    "request_id": msg.get("request_id"),
                },
            )

    async def _handle_thread_archive(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            await d._runner.archive_persisted_thread(thread_id)
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_operation_ack",
                    "operation": "archive",
                    "thread_id": thread_id,
                    "success": True,
                    "message": "Thread archived successfully",
                    "request_id": msg.get("request_id"),
                },
            )
        except Exception as e:
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_operation_ack",
                    "operation": "archive",
                    "thread_id": thread_id,
                    "success": False,
                    "message": str(e),
                    "request_id": msg.get("request_id"),
                },
            )

    async def _handle_thread_delete(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            await d._runner.delete_persisted_thread(thread_id)
            d._thread_registry.remove(thread_id)
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_operation_ack",
                    "operation": "delete",
                    "thread_id": thread_id,
                    "success": True,
                    "message": "Thread deleted successfully",
                    "request_id": msg.get("request_id"),
                },
            )
        except Exception as e:
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_operation_ack",
                    "operation": "delete",
                    "thread_id": thread_id,
                    "success": False,
                    "message": str(e),
                    "request_id": msg.get("request_id"),
                },
            )

    async def _handle_thread_messages(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]
        limit = msg.get("limit", 100)
        offset = msg.get("offset", 0)
        include_events = msg.get("include_events", False)  # NEW: full history mode

        try:
            messages = await d._runner.get_persisted_thread_messages(
                thread_id,
                limit=limit,
                offset=offset,
                include_events=include_events,
            )
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_messages_response",
                    "thread_id": thread_id,
                    "messages": [m.model_dump(mode="json") for m in messages],
                    "limit": limit,
                    "offset": offset,
                    "include_events": include_events,
                    "request_id": msg.get("request_id"),
                },
            )
        except KeyError:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                    "request_id": msg.get("request_id"),
                },
            )

    async def _handle_thread_artifacts(self, client_id: str, msg: dict[str, Any]) -> None:
        d = self._daemon
        thread_id = msg["thread_id"]

        try:
            artifacts = await d._runner.get_persisted_thread_artifacts(thread_id)
            await d._send_client_message(
                client_id,
                {
                    "type": "thread_artifacts_response",
                    "thread_id": thread_id,
                    "artifacts": [a.model_dump(mode="json") for a in artifacts],
                    "request_id": msg.get("request_id"),
                },
            )
        except KeyError:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "THREAD_NOT_FOUND",
                    "message": f"Thread {thread_id} not found",
                    "request_id": msg.get("request_id"),
                },
            )

    async def _handle_thread_status(self, client_id: str, msg: dict[str, Any]) -> None:
        """Query thread runtime status (running vs idle).

        Returns thread state for reconnecting to active threads.
        """
        d = self._daemon
        thread_id = str(msg.get("thread_id", "")).strip()

        if not thread_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "thread_id required",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        # Check thread registry for runtime state
        thread_state = d._thread_registry.get(thread_id)

        status = {
            "thread_id": thread_id,
            "state": "idle"
            if not thread_state
            else ("running" if thread_state.query_running else "idle"),
            "has_active_query": thread_state.query_running if thread_state else False,
            "last_activity": thread_state.last_activity if thread_state else None,
        }

        await d._send_client_message(
            client_id,
            {
                "type": "thread_status_response",
                **status,
                "request_id": msg.get("request_id"),
            },
        )

    async def _handle_thread_state(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return raw checkpoint state values for a thread."""
        d = self._daemon
        thread_id = str(msg.get("thread_id", "")).strip()
        if not thread_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_MESSAGE",
                    "message": "thread_state requires thread_id",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        values = await d._runner.get_thread_state_values(thread_id)

        # Encode LangChain messages explicitly so the TUI can round-trip them.
        messages = values.get("messages")
        if isinstance(messages, list):
            try:
                from langchain_core.messages.base import messages_to_dict

                values = dict(values)
                values["messages"] = messages_to_dict(messages)
            except Exception:
                logger.debug(
                    "Failed to serialize thread_state messages for %s", thread_id, exc_info=True
                )

        await d._send_client_message(
            client_id,
            {
                "type": "thread_state_response",
                "thread_id": thread_id,
                "values": values,
                "request_id": msg.get("request_id"),
            },
        )

    async def _handle_thread_update_state(self, client_id: str, msg: dict[str, Any]) -> None:
        """Persist partial checkpoint state values for a thread.

        Responds immediately before performing the state update to avoid timeout
        during interrupt cleanup (IG-228).
        """
        d = self._daemon
        thread_id = str(msg.get("thread_id", "")).strip()
        values = msg.get("values")
        if not thread_id or not isinstance(values, dict):
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_MESSAGE",
                    "message": "thread_update_state requires thread_id and values",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        # Respond immediately to avoid client timeout during interrupt cleanup
        await d._send_client_message(
            client_id,
            {
                "type": "thread_update_state_response",
                "thread_id": thread_id,
                "success": True,
                "request_id": msg.get("request_id"),
            },
        )

        # Deserialize messages if present
        if isinstance(values.get("messages"), list):
            try:
                values = dict(values)
                values["messages"] = messages_from_wire_dicts(values["messages"])
            except Exception:
                logger.debug(
                    "Failed to deserialize thread_update_state messages for %s",
                    thread_id,
                    exc_info=True,
                )

        # Perform state update in background after responding
        try:
            await d._runner.update_thread_state_values(thread_id, values)
        except (RuntimeError, OSError, ValueError, KeyError) as e:
            # Catch specific exceptions from checkpoint/IO errors, not system interrupts
            logger.warning(
                "Failed to persist thread state for %s after acknowledgment: %s",
                thread_id,
                e,
                exc_info=True,
            )

    async def _handle_resume_interrupts(self, client_id: str, msg: dict[str, Any]) -> None:
        """Resume an interactive daemon turn paused on HITL or ask_user."""
        d = self._daemon
        thread_id = str(msg.get("thread_id", "")).strip()
        resume_payload = msg.get("resume_payload")
        if not thread_id or not isinstance(resume_payload, dict):
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_MESSAGE",
                    "message": "resume_interrupts requires thread_id and resume_payload",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        future = d._pending_interrupt_responses.get(thread_id)
        if future is None or future.done():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "NO_PENDING_INTERRUPT",
                    "message": f"No pending interrupt for thread {thread_id}",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        future.set_result(resume_payload)
        await d._send_client_message(
            client_id,
            {
                "type": "interrupts_resumed",
                "thread_id": thread_id,
                "success": True,
                "request_id": msg.get("request_id"),
            },
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
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "subscribe_thread requires thread_id",
                    },
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
            # IG-228: Subscribe even if already subscribed (client expects confirmation)
            await d._session_manager.subscribe_thread(client_id, thread_id, verbosity=verbosity)

            session = await d._session_manager.get_session(client_id)
            if session:
                # Always send subscription confirmation so client bootstrap completes
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

    async def _handle_skills_list(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return wire-safe skill metadata for the daemon's agent config."""
        d = self._daemon
        from soothe.skills.catalog import wire_entries_for_agent_config

        skills = wire_entries_for_agent_config(d._config)
        await d._send_client_message(
            client_id,
            {
                "type": "skills_list_response",
                "skills": skills,
                "request_id": msg.get("request_id"),
            },
        )

    async def _handle_models_list(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return model rows from the daemon host ``SootheConfig`` (for TUI ``/model``)."""
        d = self._daemon
        from soothe.config.models_catalog import build_models_list_payload

        payload = build_models_list_payload(d._config)
        await d._send_client_message(
            client_id,
            {
                "type": "models_list_response",
                "models": payload["models"],
                "default_model": payload.get("default_model"),
                "request_id": msg.get("request_id"),
            },
        )

    async def _handle_invoke_skill(self, client_id: str, msg: dict[str, Any]) -> None:
        """Resolve a skill on the daemon host, ack the client, then queue the composed turn."""
        d = self._daemon
        from soothe.skills.catalog import (
            build_skill_invocation_envelope,
            read_skill_markdown,
            resolve_skill_directory,
        )

        # IG-054: Capacity check moved to query_engine.py to eliminate race

        raw_skill = msg.get("skill")
        if not isinstance(raw_skill, str) or not raw_skill.strip():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_MESSAGE",
                    "message": "invoke_skill requires non-empty string field: skill",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        args_val = msg.get("args", "")
        args = args_val if isinstance(args_val, str) else ""

        meta = resolve_skill_directory(d._config, raw_skill)
        if meta is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "SKILL_NOT_FOUND",
                    "message": f"Unknown skill: {raw_skill.strip()!r}",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        md = read_skill_markdown(meta)
        if md is None or not md.strip():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "SKILL_LOAD_FAILED",
                    "message": f"Could not read SKILL.md for skill: {meta.get('name', raw_skill)!r}",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        envelope = build_skill_invocation_envelope(meta, md, args)
        echo = {
            "skill_name": meta["name"],
            "description": meta.get("description", ""),
            "source": meta.get("source", ""),
            "body": md,
            "args": args,
        }

        await d._send_client_message(
            client_id,
            {
                "type": "invoke_skill_response",
                "request_id": msg.get("request_id"),
                "echo": echo,
            },
        )

        await d._current_input_queue.put(
            {
                "type": "input",
                "text": envelope.prompt,
                "autonomous": False,
                "max_iterations": None,
                "subagent": None,
                "client_id": client_id,
                "interactive": True,
            },
        )

    async def _handle_daemon_status(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle daemon_status RPC request (IG-174 Phase 0).

        Args:
            client_id: Client connection identifier.
            msg: Request message with optional request_id.
        """
        import os

        d = self._daemon
        request_id = msg.get("request_id")

        # Check daemon running state
        running = d._running
        port_live = False
        if d._transport_manager is not None:
            for transport in d._transport_manager.get_transport_info():
                if transport.get("type") == "websocket":
                    port_live = bool(transport.get("running"))
                    break

        # Count active threads
        active_threads = len(d._active_threads) if hasattr(d, "_active_threads") else 0

        response = {
            "type": "daemon_status_response",
            "request_id": request_id,
            "running": running,
            "port_live": port_live,
            "active_threads": active_threads,
            "daemon_pid": os.getpid() if running else None,
        }

        await d._send_client_message(client_id, response)

    async def _handle_daemon_shutdown(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle daemon_shutdown RPC request (IG-174 Phase 0).

        Args:
            client_id: Client connection identifier.
            msg: Request message with optional request_id.
        """
        import asyncio

        d = self._daemon
        request_id = msg.get("request_id")

        # Send acknowledgment
        ack = {
            "type": "shutdown_ack",
            "request_id": request_id,
            "status": "acknowledged",
        }
        await d._send_client_message(client_id, ack)

        # Schedule shutdown after brief delay
        await asyncio.sleep(0.5)

        # Trigger daemon shutdown
        logger.info(
            "Daemon shutdown requested via WebSocket RPC from client=%s", _client_label(client_id)
        )
        await d.shutdown()

    async def _handle_config_get(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle config_get RPC request (IG-174 Phase 0).

        Args:
            client_id: Client connection identifier.
            msg: Request message with section and optional request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        section = msg.get("section", "all")

        # Get config section (wire-safe serialization)
        config_dict = d._config.model_dump()

        if section == "all":
            section_data = config_dict
        else:
            section_data = config_dict.get(section, {})

        response = {
            "type": "config_get_response",
            "request_id": request_id,
            section: section_data,
        }

        await d._send_client_message(client_id, response)

    # ---------------------------------------------------------------------------
    # Loop RPC Handlers (RFC-504 Loop Management CLI Commands)
    # ---------------------------------------------------------------------------

    async def _handle_loop_list(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_list RPC request (RFC-504).

        Args:
            client_id: Client connection identifier.
            msg: Request message with optional filter and limit.
        """
        import json

        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        filter_data = msg.get("filter")
        limit = msg.get("limit", 20)

        # Get all loop directories
        loops_dir = PersistenceDirectoryManager.get_loops_directory()

        loops = []
        if loops_dir.exists():
            for loop_dir in loops_dir.iterdir():
                if loop_dir.is_dir():
                    metadata_file = loop_dir / "metadata.json"
                    if metadata_file.exists():
                        try:
                            metadata = json.loads(metadata_file.read_text())

                            # Filter by status
                            if filter_data and filter_data.get("status"):
                                if metadata.get("status") != filter_data["status"]:
                                    continue

                            loops.append(
                                {
                                    "loop_id": metadata.get("loop_id", loop_dir.name),
                                    "status": metadata.get("status", "unknown"),
                                    "threads": len(metadata.get("thread_ids", [])),
                                    "goals": metadata.get("total_goals_completed", 0),
                                    "switches": metadata.get("total_thread_switches", 0),
                                    "created": metadata.get("created_at", "")[:16],
                                }
                            )
                        except Exception as e:
                            logger.warning(
                                "Failed to read metadata for %s: %s", loop_dir.name, str(e)
                            )

        # Sort by created_at (most recent first)
        loops.sort(key=lambda x: x["created"], reverse=True)

        # Limit results
        loops = loops[:limit]

        response = {
            "type": "loop_list_response",
            "request_id": request_id,
            "loops": loops,
            "total": len(loops),
        }

        await d._send_client_message(client_id, response)

    async def _handle_loop_get(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_get RPC request (RFC-504).

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id and optional verbose flag.
        """
        import json

        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.manager import (
            AgentLoopCheckpointPersistenceManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)

        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        # Load metadata
        metadata_file = loop_dir / "metadata.json"
        if not metadata_file.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_METADATA_MISSING",
                    "message": f"No metadata found for loop {loop_id}",
                    "request_id": request_id,
                },
            )
            return

        try:
            metadata = json.loads(metadata_file.read_text())
        except Exception as e:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_METADATA_PARSE_ERROR",
                    "message": f"Failed to read metadata: {str(e)}",
                    "request_id": request_id,
                },
            )
            return

        # Load checkpoint database
        persistence_manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Get failed branches
        branches = await persistence_manager.get_failed_branches_for_loop(loop_id)

        # Get checkpoint anchors
        anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 1000)

        loop_data = {
            "loop_id": metadata.get("loop_id", loop_id),
            "status": metadata.get("status", "unknown"),
            "schema_version": metadata.get("schema_version", "unknown"),
            "current_thread_id": metadata.get("current_thread_id", "unknown"),
            "thread_ids": metadata.get("thread_ids", []),
            "total_goals_completed": metadata.get("total_goals_completed", 0),
            "total_thread_switches": metadata.get("total_thread_switches", 0),
            "total_duration_ms": metadata.get("total_duration_ms", 0),
            "total_tokens_used": metadata.get("total_tokens_used", 0),
            "created_at": metadata.get("created_at", "unknown"),
            "updated_at": metadata.get("updated_at", "unknown"),
            "failed_branches": branches,
            "checkpoint_anchors": anchors,
        }

        response = {
            "type": "loop_get_response",
            "request_id": request_id,
            "loop": loop_data,
        }

        await d._send_client_message(client_id, response)

    async def _handle_loop_tree(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_tree RPC request (RFC-504).

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id and format.
        """
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.manager import (
            AgentLoopCheckpointPersistenceManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)

        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        persistence_manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Get checkpoint anchors (main line)
        anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 1000)

        # Get failed branches
        branches = await persistence_manager.get_failed_branches_for_loop(loop_id)

        # Build tree structure
        tree_data = {
            "main_line": [],
            "failed_branches": [],
        }

        # Group anchors by iteration
        iterations = {}
        for anchor in anchors:
            iter_num = anchor["iteration"]
            if iter_num not in iterations:
                iterations[iter_num] = {}
            iterations[iter_num][anchor["anchor_type"]] = anchor

        for iter_num in sorted(iterations.keys()):
            iter_data = iterations[iter_num]
            start_anchor = iter_data.get("iteration_start", {})
            end_anchor = iter_data.get("iteration_end", {})

            tree_data["main_line"].append(
                {
                    "iteration": iter_num,
                    "thread_id": start_anchor.get("thread_id", "unknown"),
                    "start_checkpoint": start_anchor.get("checkpoint_id", ""),
                    "end_checkpoint": end_anchor.get("checkpoint_id", ""),
                    "status": end_anchor.get("iteration_status", "unknown"),
                    "tools_executed": end_anchor.get("tools_executed", []),
                }
            )

        for branch in branches:
            tree_data["failed_branches"].append(
                {
                    "branch_id": branch["branch_id"],
                    "iteration": branch["iteration"],
                    "thread_id": branch["thread_id"],
                    "root_checkpoint": branch["root_checkpoint_id"],
                    "failure_checkpoint": branch["failure_checkpoint_id"],
                    "failure_reason": branch["failure_reason"],
                    "execution_path": branch.get("execution_path", []),
                    "avoid_patterns": branch.get("avoid_patterns", []),
                    "suggested_adjustments": branch.get("suggested_adjustments", []),
                }
            )

        response = {
            "type": "loop_tree_response",
            "request_id": request_id,
            "tree": tree_data,
        }

        await d._send_client_message(client_id, response)

    async def _handle_loop_prune(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_prune RPC request (RFC-504).

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id, retention_days, and dry_run.
        """
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.manager import (
            AgentLoopCheckpointPersistenceManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")
        retention_days = msg.get("retention_days", 30)
        dry_run = msg.get("dry_run", False)

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)

        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        persistence_manager = AgentLoopCheckpointPersistenceManager("sqlite")

        if dry_run:
            # Get branches but don't delete
            branches = await persistence_manager.get_failed_branches_for_loop(loop_id)
            remaining = len(branches)
            pruned = 0
        else:
            # Prune old branches
            pruned = await persistence_manager.prune_old_branches(loop_id, retention_days)
            remaining = len(await persistence_manager.get_failed_branches_for_loop(loop_id))

        result_data = {
            "pruned": pruned,
            "remaining": remaining,
            "dry_run": dry_run,
        }

        response = {
            "type": "loop_prune_response",
            "request_id": request_id,
            "result": result_data,
        }

        await d._send_client_message(client_id, response)

    async def _handle_loop_delete(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_delete RPC request (RFC-504).

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id.
        """
        import shutil

        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)

        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        # Delete loop directory
        try:
            shutil.rmtree(loop_dir)
            logger.info("Deleted loop directory: %s", loop_id)

            response = {
                "type": "loop_delete_response",
                "request_id": request_id,
                "success": True,
                "message": f"Loop {loop_id} deleted successfully",
            }

            await d._send_client_message(client_id, response)
        except Exception as e:
            logger.error("Failed to delete loop %s: %s", loop_id, str(e))

            response = {
                "type": "loop_delete_response",
                "request_id": request_id,
                "success": False,
                "message": f"Failed to delete loop: {str(e)}",
            }

            await d._send_client_message(client_id, response)

    async def _handle_loop_reattach(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_reattach RPC request (RFC-411).

        Reconstruct event history and replay to client for loop reattachment.

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id.
        """
        from soothe.daemon.reattachment_handler import handle_loop_reattach

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        # Execute reattachment handler
        await handle_loop_reattach(loop_id, d, client_id)

    async def _handle_loop_subscribe(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_subscribe RPC request (RFC-503).

        Subscribe client to loop topic for real-time event streaming.
        Used by loop continue and loop attach commands.

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id.
        """
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.daemon.reattachment_handler import handle_loop_reattach

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        # Check loop exists
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        # Reattachment handler handles subscription and history replay
        await handle_loop_reattach(loop_id, d, client_id)

        # Send subscribe response
        await d._send_client_message(
            client_id,
            {
                "type": "loop_subscribe_response",
                "loop_id": loop_id,
                "success": True,
                "request_id": request_id,
            },
        )

    async def _handle_loop_detach(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_detach RPC request (RFC-503).

        Unsubscribe client from loop events while loop continues running.
        Saves detachment checkpoint for later reattachment.

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id.
        """
        import json
        from datetime import UTC, datetime

        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id required",
                    "request_id": request_id,
                },
            )
            return

        # Check loop exists
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        # Update metadata with detachment timestamp
        metadata_file = loop_dir / "metadata.json"
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text())
                metadata["detached_at"] = datetime.now(UTC).isoformat()
                metadata["status"] = "detached"
                metadata_file.write_text(json.dumps(metadata, indent=2))
            except Exception as e:
                logger.warning("Failed to update metadata for detachment: %s", str(e))

        # Unsubscribe client from loop topic (if subscribed)
        session = await d._session_manager.get_session(client_id)
        if session and hasattr(session, "loop_subscription"):
            if session.loop_subscription:
                await d._event_bus.unsubscribe(session.loop_subscription, session.event_queue)
                session.loop_subscription = None
                logger.info("Client %s unsubscribed from loop %s", client_id, loop_id)

        # Send detach response
        await d._send_client_message(
            client_id,
            {
                "type": "loop_detach_response",
                "loop_id": loop_id,
                "success": True,
                "request_id": request_id,
            },
        )

    async def _handle_loop_new(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_new RPC request (RFC-503).

        Create fresh loop with new loop_id for new query/conversation.

        Args:
            client_id: Client connection identifier.
            msg: Request message (no parameters required).
        """
        import json
        from datetime import UTC, datetime

        from uuid_utils import uuid7

        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")

        # Generate new loop_id
        loop_id = str(uuid7())

        # Create loop directory
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        loop_dir.mkdir(parents=True, exist_ok=True)

        # Initialize metadata
        metadata = {
            "loop_id": loop_id,
            "status": "created",
            "thread_ids": [],
            "current_thread_id": None,
            "total_goals_completed": 0,
            "total_thread_switches": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        metadata_file = loop_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))

        logger.info("Created new loop %s", loop_id)

        # Send response
        await d._send_client_message(
            client_id,
            {
                "type": "loop_new_response",
                "loop_id": loop_id,
                "success": True,
                "request_id": request_id,
            },
        )

    async def _handle_loop_input(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_input RPC request (RFC-503).

        Send user input/prompt to active loop for processing.
        Integrates with QueryEngine by queueing input to daemon's input queue
        with thread_id from loop metadata.

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id and content.
        """
        import json
        from datetime import UTC, datetime
        from pathlib import Path

        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")
        content = msg.get("content")

        if not loop_id or not content:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id and content required",
                    "request_id": request_id,
                },
            )
            return

        # Check loop exists
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        if not loop_dir.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_FOUND",
                    "message": f"Loop {loop_id} not found",
                    "request_id": request_id,
                },
            )
            return

        # Load loop metadata to get current_thread_id
        metadata_file = loop_dir / "metadata.json"
        if not metadata_file.exists():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_METADATA_MISSING",
                    "message": f"No metadata found for loop {loop_id}",
                    "request_id": request_id,
                },
            )
            return

        try:
            metadata = json.loads(metadata_file.read_text())
        except Exception as e:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_METADATA_PARSE_ERROR",
                    "message": f"Failed to read metadata: {str(e)}",
                    "request_id": request_id,
                },
            )
            return

        # Get or create thread_id for execution
        thread_id = metadata.get("current_thread_id")

        if not thread_id:
            # Generate new thread_id if loop has no current thread
            from uuid_utils import uuid7

            thread_id = str(uuid7())

            # Update metadata with new thread
            metadata["current_thread_id"] = thread_id
            if thread_id not in metadata.get("thread_ids", []):
                metadata.setdefault("thread_ids", []).append(thread_id)
            metadata["status"] = "running"
            metadata["updated_at"] = datetime.now(UTC).isoformat()

            try:
                metadata_file.write_text(json.dumps(metadata, indent=2))
            except Exception as e:
                logger.warning("Failed to update loop metadata: %s", str(e))

        # Register thread in daemon's thread registry
        d._thread_registry.ensure(thread_id, is_draft=False)
        workspace = Path(d._daemon_workspace)
        d._thread_registry.set_workspace(thread_id, workspace)

        # Set runner's current thread to loop's thread
        d._runner.set_current_thread_id(thread_id)

        logger.info(
            "Queueing input for loop %s (thread %s): %s",
            loop_id,
            thread_id,
            preview_first(content, 50),
        )

        # Queue input for QueryEngine execution
        await d._current_input_queue.put(
            {
                "type": "input",
                "text": content,
                "autonomous": bool(msg.get("autonomous", False)),
                "max_iterations": msg.get("max_iterations"),
                "subagent": msg.get("subagent"),
                "client_id": client_id,
                "interactive": bool(msg.get("interactive", False)),
                "model": msg.get("model"),
                "model_params": msg.get("model_params"),
            }
        )

        # Send response (execution will happen asynchronously via QueryEngine)
        await d._send_client_message(
            client_id,
            {
                "type": "loop_input_response",
                "loop_id": loop_id,
                "thread_id": thread_id,
                "success": True,
                "request_id": request_id,
            },
        )

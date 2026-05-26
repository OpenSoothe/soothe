"""Transport message dispatch for the daemon (IG-110).

Maps JSON message types to handlers using ``SootheRunner`` public APIs instead
of reaching into ``runner._durability``.
"""

from __future__ import annotations

import logging
from typing import Any

from soothe.utils.text_preview import preview_first
from soothe_sdk.client.protocol import _serialize_for_json

from soothe_daemon.image_understanding import validate_and_normalize_image_attachments
from soothe_daemon.logging import set_client_id

logger = logging.getLogger(__name__)

_CLIENT_LABEL_LEN = 8

# Client messages logged at DEBUG on every dispatch; skip types that poll frequently.
_SKIP_PER_MESSAGE_DEBUG_TYPES = frozenset({"daemon_ready", "daemon_status"})


def _client_label(client_id: Any) -> str:
    """Short label for logs when ``client_id`` may be a legacy connection object."""
    if isinstance(client_id, str):
        return client_id[:_CLIENT_LABEL_LEN] if len(client_id) >= _CLIENT_LABEL_LEN else client_id
    return f"obj:{id(client_id) & 0xFFFF_FFFF:x}"


def _queue_options_from_daemon_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional runner fields for ``loop_input`` messages (IG-362).

    Args:
        msg: Raw client message dict.

    Returns:
        Keys to merge into the internal queue payload: ``autonomous``,
        ``max_iterations``, ``preferred_subagent``, ``model``,
        ``model_params``, ``intent_hint`` (normalized to lowercase when set).
    """
    max_iterations = msg.get("max_iterations")
    parsed_max: int | None = (
        max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else None
    )
    preferred_subagent = msg.get("preferred_subagent")
    preferred_norm = (
        preferred_subagent.strip() or None if isinstance(preferred_subagent, str) else None
    )
    raw_model = msg.get("model")
    model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
    raw_params = msg.get("model_params")
    model_params = raw_params if isinstance(raw_params, dict) else None
    raw_hint = msg.get("intent_hint")
    intent_hint = (
        raw_hint.strip().lower() if isinstance(raw_hint, str) and raw_hint.strip() else None
    )
    raw_schema = msg.get("response_schema")
    response_schema = raw_schema if isinstance(raw_schema, dict) and raw_schema else None
    raw_schema_name = msg.get("response_schema_name")
    response_schema_name = (
        raw_schema_name.strip()
        if isinstance(raw_schema_name, str) and raw_schema_name.strip()
        else None
    )
    raw_schema_strict = msg.get("response_schema_strict")
    response_schema_strict: bool | None
    if isinstance(raw_schema_strict, bool):
        response_schema_strict = raw_schema_strict
    else:
        response_schema_strict = None
    return {
        "autonomous": bool(msg.get("autonomous", False)),
        "max_iterations": parsed_max,
        "preferred_subagent": preferred_norm,
        "model": model,
        "model_params": model_params,
        "intent_hint": intent_hint,
        "response_schema": response_schema,
        "response_schema_name": response_schema_name,
        "response_schema_strict": response_schema_strict,
    }


def _coerce_loop_input_text(content: Any) -> str | None:
    """Normalize ``loop_input`` content to a non-empty user text string (IG-361).

    Preferred wire shape is a bare string. Some clients send a small JSON
    object (e.g. ``{"text": "..."}``); extract the first known string field.

    Args:
        content: Raw ``content`` field from a ``loop_input`` message.

    Returns:
        Stripped non-empty text, or ``None`` if no usable string was found.
    """
    if isinstance(content, str):
        stripped = content.strip()
        return stripped if stripped else None
    if isinstance(content, dict):
        for key in ("text", "prompt", "message", "input"):
            val = content.get(key)
            if isinstance(val, str):
                s = val.strip()
                if s:
                    return s
        return None
    return None


class MessageRouter:
    """Dispatches client messages by ``type`` field."""

    def __init__(self, daemon: Any) -> None:
        """Keep a reference to the daemon for config, runner, and session access."""
        self._daemon = daemon

    async def _client_subscribed_loop_id(self, client_id: Any) -> str | None:
        """Return the ``loop_id`` this client receives loop-scoped events for (IG-408).

        The session manager enforces **at most one** loop subscription per client
        (``subscribe_loop`` replaces any prior loop). **Many clients** may subscribe
        to the **same** loop; this method only answers "which loop is *this* client
        watching?", not ownership of the loop.

        If ``subscriptions`` ever contains more than one id (unexpected), pick a
        deterministic value and log a warning so behavior stays stable until
        multi-loop-per-client is explicitly designed.
        """
        session = await self._daemon._session_manager.get_session(client_id)
        if not session or not session.subscriptions:
            return None
        subs = session.subscriptions
        if len(subs) > 1:
            logger.warning(
                "[MsgRouter] Client %s has %d loop subscriptions (expected 1); using min(loop_id)",
                client_id,
                len(subs),
            )
        return min(subs)

    async def dispatch(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle a single client message."""
        # Set client_id in logging context for full ID in daemon.log
        if isinstance(client_id, str):
            set_client_id(client_id)
        d = self._daemon
        msg_type = msg.get("type", "")
        if msg_type not in _SKIP_PER_MESSAGE_DEBUG_TYPES:
            logger.debug(
                "[MsgRouter] Received message type=%s from client=%s",
                msg_type,
                client_id,
            )

        if msg_type == "command":
            cmd = msg.get("cmd", "")
            normalized = cmd.strip().lower()
            if normalized in ("/exit", "/quit"):
                logger.info(
                    "Received %s via router — treating as client detach (daemon keeps running)",
                    normalized,
                )
                await d._send_client_message(client_id, {"type": "status", "state": "detached"})
                return
            if normalized == "/cancel" and getattr(d, "_query_engine", None) is not None:
                owned = await d._session_manager.get_owned_loop(client_id)
                target_loop = owned or await self._client_subscribed_loop_id(client_id)
                if target_loop:
                    await d._query_engine.cancel_loop(target_loop)
                return
            active_loop = await self._client_subscribed_loop_id(client_id)
            if not active_loop:
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "NO_LOOP_SUBSCRIPTION",
                        "message": "loop_subscribe required before slash commands",
                    },
                )
                return
            await d._loop_input_dispatcher.enqueue(
                active_loop,
                {"type": "command", "cmd": cmd, "client_id": client_id},
            )
            return

        if msg_type == "daemon_ready":
            await d._send_client_message(client_id, d.daemon_ready_message())
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

        if msg_type == "skills_list":
            await self._handle_skills_list(client_id, msg)
            return

        if msg_type == "invoke_skill":
            await self._handle_invoke_skill(client_id, msg)
            return

        if msg_type == "models_list":
            await self._handle_models_list(client_id, msg)
            return

        if msg_type == "loop_messages":
            await self._handle_loop_messages(client_id, msg)
            return

        if msg_type == "loop_state_get":
            await self._handle_loop_state_get(client_id, msg)
            return

        if msg_type == "loop_state_update":
            await self._handle_loop_state_update(client_id, msg)
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

        if msg_type == "command_request":
            active_loop = await self._client_subscribed_loop_id(client_id)
            if not active_loop:
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "NO_LOOP_SUBSCRIPTION",
                        "message": "loop_subscribe required before command_request",
                        "request_id": msg.get("request_id"),
                    },
                )
                return
            req = dict(msg)
            req["client_id"] = client_id
            await d._loop_input_dispatcher.enqueue(active_loop, req)
            return

        logger.debug("Unknown client message type: %s", msg_type)

    async def _handle_skills_list(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return wire-safe skill metadata for the daemon's agent config."""
        d = self._daemon
        from soothe.skills.catalog import wire_entries_for_agent_config

        # Use client's loop workspace if subscribed, otherwise cwd
        workspace: str | None = None
        loop_id = await self._client_subscribed_loop_id(client_id)
        if loop_id:
            # Get workspace from thread registry (set by bind_execution_thread_for_loop)
            ws_path = d._thread_registry.get_workspace(d._current_thread_id or loop_id)
            if ws_path:
                workspace = str(ws_path)

        skills = wire_entries_for_agent_config(d._config, workspace)
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
            format_slash_skill_invoke_line,
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

        # Use client's loop workspace if subscribed, otherwise cwd
        workspace: str | None = None
        loop_id = await self._client_subscribed_loop_id(client_id)
        if loop_id:
            # Get workspace from thread registry (set by bind_execution_thread_for_loop)
            ws_path = d._thread_registry.get_workspace(d._current_thread_id or loop_id)
            if ws_path:
                workspace = str(ws_path)

        meta = resolve_skill_directory(d._config, raw_skill, workspace)
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

        active_loop = await self._client_subscribed_loop_id(client_id)
        if not active_loop:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "NO_LOOP_SUBSCRIPTION",
                    "message": "loop_subscribe required before invoke_skill",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        plain_user_line = format_slash_skill_invoke_line(str(meta.get("name", "")), args)
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

        await d._loop_input_dispatcher.enqueue(
            active_loop,
            {
                "type": "input",
                "text": plain_user_line,
                "autonomous": False,
                "max_iterations": None,
                "preferred_subagent": None,
                "client_id": client_id,
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
                    # Transports report client_count only; port is live when daemon is up.
                    port_live = bool(running)
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
        logger.info("Daemon shutdown requested via WebSocket RPC from client=%s", client_id)
        await d.stop()

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
    # Loop RPC Helpers (IG-246: Self-healing metadata sync)
    # ---------------------------------------------------------------------------

    async def _ensure_loop_exists(self, loop_id: str) -> bool:
        """Check the loop exists in the database.

        Args:
            loop_id: Loop identifier

        Returns:
            True if loop exists in DB, False otherwise.
        """
        metadata = await self._daemon._persistence_manager.get_loop_metadata(loop_id)
        return metadata is not None

    # ---------------------------------------------------------------------------
    # Loop RPC Handlers (RFC-504 Loop Management CLI Commands)
    # ---------------------------------------------------------------------------

    async def _handle_loop_list(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_list RPC request (RFC-504).

        Args:
            client_id: Client connection identifier.
            msg: Request message with optional filter and limit.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        filter_data = msg.get("filter")
        limit = msg.get("limit", 20)

        status_filter = filter_data.get("status") if filter_data else None

        rows = await d._persistence_manager.list_loops(status_filter=status_filter, limit=limit)
        loops = [
            {
                "loop_id": row["loop_id"],
                "status": row.get("status", "unknown"),
                "threads": len(row.get("thread_ids") or []),
                "goals": row.get("total_goals_completed", 0),
                "switches": row.get("total_thread_switches", 0),
                "created": (row.get("created_at") or "")[:16],
            }
            for row in rows
        ]

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

        # Load metadata from DB
        metadata = await d._persistence_manager.get_loop_metadata(loop_id)
        if metadata is None:
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

        # Get failed branches and checkpoint anchors
        branches = await d._persistence_manager.get_failed_branches_for_loop(loop_id)
        anchors = await d._persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 1000)

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
            "client_workspace": metadata.get("client_workspace"),
            "current_workspace": metadata.get("current_workspace"),
            "detached_at": metadata.get("detached_at"),
            "is_ephemeral": bool(metadata.get("is_ephemeral", False)),
            "last_message_at": metadata.get("last_message_at"),
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

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
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

        persistence_manager = d._persistence_manager

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

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
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

        persistence_manager = d._persistence_manager

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
        from soothe_daemon.loop_gc import purge_loop_fully

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

        metadata = await d._persistence_manager.get_loop_metadata(loop_id)
        if metadata is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "loop_delete_response",
                    "request_id": request_id,
                    "success": True,
                    "message": f"Loop {loop_id} not found (already deleted)",
                },
            )
            return

        try:
            await purge_loop_fully(d, loop_id, metadata)
            response = {
                "type": "loop_delete_response",
                "request_id": request_id,
                "success": True,
                "message": f"Loop {loop_id} deleted successfully",
            }
            await d._send_client_message(client_id, response)
        except Exception as e:
            logger.error("Failed to delete loop %s: %s", loop_id, str(e))
            await d._send_client_message(
                client_id,
                {
                    "type": "loop_delete_response",
                    "request_id": request_id,
                    "success": False,
                    "message": f"Failed to delete loop: {str(e)}",
                },
            )

    async def _handle_loop_reattach(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_reattach RPC request (RFC-411).

        Reconstruct event history and replay to client for loop reattachment.

        Args:
            client_id: Client connection identifier.
            msg: Request message with loop_id.
        """
        from soothe_daemon.event import handle_loop_reattach

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
        from soothe_daemon.event import handle_loop_reattach

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

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
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

        await handle_loop_reattach(loop_id, d, client_id)

        verbosity = msg.get("verbosity", "normal")
        wire_tier = msg.get("wire_tier", "full")
        stream_delivery = msg.get("stream_delivery", "batch")
        # Accept "streaming" for backwards compatibility, map to "adaptive"
        if stream_delivery not in ("batch", "streaming", "adaptive"):
            stream_delivery = "batch"
        if stream_delivery == "streaming":
            stream_delivery = "adaptive"  # Map old mode to new adaptive mode
        await d._session_manager.subscribe_loop(
            client_id,
            loop_id,
            verbosity=verbosity,
            stream_delivery=stream_delivery,
            wire_tier=wire_tier,
        )
        session = await d._session_manager.get_session(client_id)
        if session:
            await d._session_manager.send_to_client(
                session,
                {
                    "type": "subscription_confirmed",
                    "loop_id": loop_id,
                    "client_id": client_id,
                    "verbosity": verbosity,
                },
            )

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
        from datetime import UTC, datetime

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

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
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

        # Update detachment status in DB
        try:
            await d._persistence_manager.update_loop_metadata(
                loop_id,
                status="detached",
                detached_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            logger.warning("Failed to update metadata for detachment: %s", str(e))

        await d._session_manager.unsubscribe_loop(client_id, loop_id)

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

        Create fresh loop with new loop_id for new query/conversation. If the client
        provides a ``workspace`` field (e.g., user's CWD), validate it and record it
        as the loop's filesystem workspace. If client provides ``user`` field, store
        for workspace isolation (per-user workspace under $SOOTHE_HOME/workspaces/).

        Args:
            client_id: Client connection identifier.
            msg: Request message; may contain optional ``workspace`` and ``user`` fields.
        """
        from datetime import UTC, datetime

        from soothe.core.loop.state.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.core.workspace import resolve_loop_workspace, validate_client_workspace
        from uuid_utils import uuid7

        d = self._daemon
        request_id = msg.get("request_id")
        is_ephemeral = bool(msg.get("is_ephemeral", False))

        # Generate new loop_id
        loop_id = str(uuid7())

        # Resolve optional client workspace hint. Invalid hints fall back to
        # daemon workspace via _bind_execution_thread_for_loop.
        client_workspace: str | None = None
        raw_workspace = msg.get("client_workspace") or msg.get("workspace")
        if isinstance(raw_workspace, str) and raw_workspace.strip():
            try:
                resolved = validate_client_workspace(raw_workspace)
            except ValueError as e:
                logger.warning(
                    "[loop_new] Rejecting invalid client workspace %r: %s", raw_workspace, e
                )
            else:
                client_workspace = str(resolved)
                logger.info(
                    "[loop_new] Loop %s using client workspace: %s",
                    loop_id,
                    client_workspace,
                )

        # Extract user identity for workspace isolation
        user: str | None = None
        raw_user = msg.get("user_id") or msg.get("user")  # Support both field names
        if isinstance(raw_user, str) and raw_user.strip():
            user = raw_user.strip()
            logger.info("[loop_new] Loop %s user identity: %s", loop_id, user)

        raw_client_ws_id = msg.get("client_workspace_id")
        client_workspace_id: str | None = None
        if isinstance(raw_client_ws_id, str) and raw_client_ws_id.strip():
            client_workspace_id = raw_client_ws_id.strip()

        try:
            resolved_workspace = resolve_loop_workspace(
                loop_id=loop_id,
                client_workspace=client_workspace,
                user_id=user,
                client_workspace_id=client_workspace_id,
            )
        except ValueError as e:
            logger.warning(
                "[loop_new] Loop %s workspace resolution failed (%s); using daemon workspace",
                loop_id,
                e,
            )
            from soothe.core.workspace import resolve_daemon_workspace

            resolved_workspace = resolve_daemon_workspace()

        now = datetime.now(UTC).isoformat()

        # Create loop directory (still needed for goals/ and working_memory/ subdirs)
        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        loop_dir.mkdir(parents=True, exist_ok=True)

        # Register loop in database
        await d._persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=[],
            current_thread_id="",
            status="created",
        )

        meta_updates: dict[str, Any] = {
            "is_ephemeral": is_ephemeral,
            "last_message_at": now,
            "current_workspace": str(resolved_workspace),
        }
        if client_workspace is not None:
            meta_updates["client_workspace"] = client_workspace
        if user is not None:
            meta_updates["user_id"] = user
        if client_workspace_id is not None:
            meta_updates["client_workspace_id"] = client_workspace_id
        await d._persistence_manager.update_loop_metadata(loop_id, **meta_updates)

        logger.info(
            "Created new loop %s (ephemeral=%s workspace=%s)",
            loop_id,
            is_ephemeral,
            resolved_workspace,
        )

        # Send response
        await d._send_client_message(
            client_id,
            {
                "type": "loop_new_response",
                "loop_id": loop_id,
                "success": True,
                "is_ephemeral": is_ephemeral,
                "request_id": request_id,
            },
        )

    async def _handle_loop_input(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_input RPC: authorize, then enqueue to the loop's isolated input queue."""
        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")
        q_opts = _queue_options_from_daemon_message(msg)
        intent_hint_preview = q_opts.get("intent_hint")
        prompt_text = _coerce_loop_input_text(msg.get("content"))

        if not loop_id:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id is required",
                    "request_id": request_id,
                },
            )
            return

        if intent_hint_preview not in ("direct_llm", "image_to_text") and prompt_text is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id and non-empty content (string or object with text) required",
                    "request_id": request_id,
                },
            )
            return

        if not await self._ensure_loop_exists(loop_id):
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

        session = await d._session_manager.get_session(client_id)
        if not session or loop_id not in session.subscriptions:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_NOT_SUBSCRIBED",
                    "message": "loop_subscribe required before loop_input",
                    "request_id": request_id,
                },
            )
            return

        raw_attachments = msg.get("attachments")
        if raw_attachments is not None:
            normalized_attachments, attachment_error = validate_and_normalize_image_attachments(
                raw_attachments
            )
            if attachment_error is not None:
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": attachment_error,
                        "request_id": request_id,
                    },
                )
                return
            attachments_for_queue = normalized_attachments or None
        else:
            attachments_for_queue = None

        if intent_hint_preview in ("direct_llm", "image_to_text"):
            if intent_hint_preview == "image_to_text" and not attachments_for_queue:
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "INVALID_REQUEST",
                        "message": "intent_hint image_to_text requires non-empty attachments",
                        "request_id": request_id,
                    },
                )
                return
            if (
                intent_hint_preview == "direct_llm"
                and not prompt_text
                and not attachments_for_queue
            ):
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "INVALID_REQUEST",
                        "message": (
                            "intent_hint direct_llm requires non-empty content or attachments"
                        ),
                        "request_id": request_id,
                    },
                )
                return
            if intent_hint_preview == "image_to_text":
                q_opts["intent_hint"] = "direct_llm"

        response_schema = q_opts.get("response_schema")
        if response_schema is not None:
            if intent_hint_preview not in (None, "direct_llm", "image_to_text"):
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "INVALID_REQUEST",
                        "message": "response_schema is only supported with intent_hint direct_llm",
                        "request_id": request_id,
                    },
                )
                return
            if attachments_for_queue:
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "INVALID_REQUEST",
                        "message": "response_schema is not supported with direct_llm attachments",
                        "request_id": request_id,
                    },
                )
                return
            try:
                from soothe.utils.llm.schema_wire import validate_response_schema

                q_opts["response_schema"] = validate_response_schema(response_schema)
            except ValueError as exc:
                await d._send_client_message(
                    client_id,
                    {
                        "type": "error",
                        "code": "INVALID_REQUEST",
                        "message": str(exc),
                        "request_id": request_id,
                    },
                )
                return

        text_for_queue = prompt_text if prompt_text is not None else ""
        logger.info(
            "Queueing input for loop %s: %s",
            loop_id,
            preview_first(text_for_queue, 50),
        )

        queue_payload: dict[str, Any] = {
            "type": "input",
            "text": text_for_queue,
            "client_id": client_id,
            **q_opts,
        }
        if attachments_for_queue:
            queue_payload["attachments"] = attachments_for_queue

        await d._loop_input_dispatcher.enqueue(loop_id, queue_payload)

        try:
            await d._persistence_manager.touch_loop_last_message(loop_id)
        except Exception:
            logger.warning("Failed to update last_message_at for loop %s", loop_id, exc_info=True)

        await d._send_client_message(
            client_id,
            {
                "type": "loop_input_response",
                "loop_id": loop_id,
                "success": True,
                "request_id": request_id,
            },
        )

    async def _handle_loop_messages(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Return persisted conversation / activity rows for a loop (RFC-503 loop-first).

        Resolves the loop's bound LangGraph checkpoint id from metadata, then reads
        ThreadLogger rows via the runner (same storage as ``get_persisted_thread_messages``).
        """
        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")
        limit = msg.get("limit", 100)
        offset = msg.get("offset", 0)
        include_events = bool(msg.get("include_events", False))

        try:
            lim = int(limit) if isinstance(limit, (int, str)) else 100
        except (TypeError, ValueError):
            lim = 100
        try:
            off = int(offset) if isinstance(offset, (int, str)) else 0
        except (TypeError, ValueError):
            off = 0

        runner = d._runner
        if runner is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "RUNNER_UNAVAILABLE",
                    "message": "Daemon runner not initialized",
                    "request_id": request_id,
                },
            )
            return

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

        try:
            from soothe_daemon.loop_isolation import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, str(loop_id))
        except Exception as exc:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_CONTEXT",
                    "message": str(exc),
                    "request_id": request_id,
                },
            )
            return

        rows = await runner.get_persisted_thread_messages(
            checkpoint_thread_id,
            limit=lim,
            offset=off,
            include_events=include_events,
        )
        serialized: list[Any] = []
        for r in rows:
            if hasattr(r, "model_dump"):
                serialized.append(_serialize_for_json(r.model_dump(mode="json")))
            elif isinstance(r, dict):
                serialized.append(_serialize_for_json(r))
            else:
                serialized.append(_serialize_for_json(r))

        await d._send_client_message(
            client_id,
            {
                "type": "loop_messages_response",
                "request_id": request_id,
                "messages": serialized,
            },
        )

    async def _handle_loop_state_get(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Return LangGraph channel values for the loop's bound checkpoint thread."""
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

        runner = d._runner
        if runner is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "RUNNER_UNAVAILABLE",
                    "message": "Daemon runner not initialized",
                    "request_id": request_id,
                },
            )
            return

        try:
            from soothe_daemon.loop_isolation import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, str(loop_id))
            values = await runner.get_thread_state_values(checkpoint_thread_id)
        except Exception as exc:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_STATE",
                    "message": str(exc),
                    "request_id": request_id,
                },
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "loop_state_get_response",
                "request_id": request_id,
                "values": _serialize_for_json(values),
            },
        )

    async def _handle_loop_state_update(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Apply partial checkpoint values for the loop's bound checkpoint thread."""
        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")
        raw_values = msg.get("values")
        if not loop_id or not isinstance(raw_values, dict):
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_REQUEST",
                    "message": "loop_id and values dict required",
                    "request_id": request_id,
                },
            )
            return

        runner = d._runner
        if runner is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "RUNNER_UNAVAILABLE",
                    "message": "Daemon runner not initialized",
                    "request_id": request_id,
                },
            )
            return

        try:
            from soothe_daemon.loop_isolation import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, str(loop_id))
            await runner.update_thread_state_values(checkpoint_thread_id, dict(raw_values))
        except Exception as exc:
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "LOOP_STATE",
                    "message": str(exc),
                    "request_id": request_id,
                },
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "loop_state_update_response",
                "request_id": request_id,
                "success": True,
            },
        )

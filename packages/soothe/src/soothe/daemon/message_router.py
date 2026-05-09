"""Transport message dispatch for the daemon (IG-110).

Maps JSON message types to handlers using ``SootheRunner`` public APIs instead
of reaching into ``runner._durability``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe.core.workspace import resolve_loop_daemon_workspace
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)

_CLIENT_LABEL_LEN = 8


def _client_label(client_id: Any) -> str:
    """Short label for logs when ``client_id`` may be a legacy connection object."""
    if isinstance(client_id, str):
        return client_id[:_CLIENT_LABEL_LEN] if len(client_id) >= _CLIENT_LABEL_LEN else client_id
    return f"obj:{id(client_id) & 0xFFFF_FFFF:x}"


def _queue_options_from_daemon_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional runner fields shared by ``input`` and ``loop_input`` (IG-362).

    Args:
        msg: Raw client message dict.

    Returns:
        Keys to merge into the internal ``input`` queue payload: ``autonomous``,
        ``max_iterations``, ``preferred_subagent``, ``interactive``, ``model``,
        ``model_params``.
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
    return {
        "autonomous": bool(msg.get("autonomous", False)),
        "max_iterations": parsed_max,
        "preferred_subagent": preferred_norm,
        "interactive": bool(msg.get("interactive", False)),
        "model": model,
        "model_params": model_params,
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
                _client_label(client_id),
                len(subs),
            )
        return min(subs)

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
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "UNSUPPORTED_MESSAGE",
                    "message": "Use loop_input with a subscribed loop_id (global input removed)",
                },
            )
            return

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

    async def _handle_resume_interrupts(self, client_id: str, msg: dict[str, Any]) -> None:
        """Resume an interactive daemon turn paused on HITL or ask_user."""
        d = self._daemon
        loop_id = str(msg.get("loop_id", "")).strip()
        resume_payload = msg.get("resume_payload")
        if not loop_id or not isinstance(resume_payload, dict):
            logger.warning(
                "[MsgRouter] resume_interrupts rejected from client %s: missing loop_id or payload",
                str(client_id)[:8],
            )
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "INVALID_MESSAGE",
                    "message": "resume_interrupts requires loop_id and resume_payload",
                    "request_id": msg.get("request_id"),
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
                    "message": "loop_subscribe required before resume_interrupts",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        future = d._pending_interrupt_responses.get(loop_id)
        if future is None or future.done():
            await d._send_client_message(
                client_id,
                {
                    "type": "error",
                    "code": "NO_PENDING_INTERRUPT",
                    "message": f"No pending interrupt for loop {loop_id}",
                    "request_id": msg.get("request_id"),
                },
            )
            return

        future.set_result(resume_payload)
        await d._send_client_message(
            client_id,
            {
                "type": "interrupts_resumed",
                "loop_id": loop_id,
                "success": True,
                "request_id": msg.get("request_id"),
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

        await d._loop_input_dispatcher.enqueue(
            active_loop,
            {
                "type": "input",
                "text": envelope.prompt,
                "autonomous": False,
                "max_iterations": None,
                "preferred_subagent": None,
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
        logger.info(
            "Daemon shutdown requested via WebSocket RPC from client=%s", _client_label(client_id)
        )
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

    async def _ensure_loop_metadata(self, loop_id: str) -> Path | None:
        """Ensure loop dir + metadata.json exist. Reconstruct from SQLite if needed.

        Self-healing for:
        - Pre-existing loops (created before IG-246)
        - Edge cases where metadata.json was deleted

        Args:
            loop_id: Loop identifier

        Returns:
            loop_dir Path if loop exists (in filesystem or SQLite), None if not found
        """
        import json

        import aiosqlite

        from soothe.core.agent_loop.state.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
        metadata_file = loop_dir / "metadata.json"

        # Case 1: metadata.json exists → use it
        if metadata_file.exists():
            return loop_dir

        # Case 2: metadata.json missing → reconstruct from SQLite
        try:
            db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM agentloop_loops WHERE loop_id = ?", (loop_id,)
                )
                row = await cursor.fetchone()

                if row is None:
                    # Loop doesn't exist in SQLite → truly not found
                    return None

                # Reconstruct metadata from checkpoint
                metadata = {
                    "loop_id": row["loop_id"],
                    "status": row["status"],
                    "thread_ids": json.loads(row["thread_ids"]),
                    "current_thread_id": row["current_thread_id"],
                    "total_goals_completed": row["total_goals_completed"],
                    "total_thread_switches": row["total_thread_switches"],
                    "total_duration_ms": row["total_duration_ms"],
                    "total_tokens_used": row["total_tokens_used"],
                    "schema_version": row["schema_version"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }

                # Write metadata.json for future use
                loop_dir.mkdir(parents=True, exist_ok=True)
                metadata_file.write_text(json.dumps(metadata, indent=2))
                logger.info("Reconstructed metadata.json for loop %s from SQLite", loop_id)

                return loop_dir

        except Exception as e:
            logger.error("Failed to reconstruct metadata for loop %s: %s", loop_id, e)
            return None

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

        import aiosqlite

        from soothe.core.agent_loop.state.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")
        filter_data = msg.get("filter")
        limit = msg.get("limit", 20)

        # Get all loop directories from filesystem
        loops_dir = PersistenceDirectoryManager.get_loops_directory()

        filesystem_loops = set()
        loops = []
        if loops_dir.exists():
            for loop_dir in loops_dir.iterdir():
                if loop_dir.is_dir() and loop_dir.name != "loop_checkpoints.db":
                    filesystem_loops.add(loop_dir.name)
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

        # Query SQLite for loops missing from filesystem (IG-246 self-healing)
        db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
        if db_path.exists():
            try:
                async with aiosqlite.connect(db_path) as db:
                    cursor = await db.execute("SELECT loop_id FROM agentloop_loops")
                    rows = await cursor.fetchall()
                    sqlite_loops = {row[0] for row in rows}

                    # Find orphaned loops (in SQLite but not in filesystem)
                    orphaned_loops = sqlite_loops - filesystem_loops

                    # Self-heal: reconstruct metadata.json for orphaned loops
                    for loop_id in orphaned_loops:
                        await self._ensure_loop_metadata(loop_id)

                        # Now load the reconstructed metadata
                        loop_dir = PersistenceDirectoryManager.get_loop_directory(loop_id)
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
                                        "loop_id": metadata.get("loop_id", loop_id),
                                        "status": metadata.get("status", "unknown"),
                                        "threads": len(metadata.get("thread_ids", [])),
                                        "goals": metadata.get("total_goals_completed", 0),
                                        "switches": metadata.get("total_thread_switches", 0),
                                        "created": metadata.get("created_at", "")[:16],
                                    }
                                )
                                logger.info(
                                    "Self-healed orphaned loop %s (reconstructed metadata.json)",
                                    loop_id,
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to read reconstructed metadata for %s: %s",
                                    loop_id,
                                    str(e),
                                )
            except Exception as e:
                logger.error("Failed to query SQLite for orphaned loops: %s", str(e))

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

        from soothe.core.agent_loop.state.persistence.manager import (
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

        # Self-healing: ensure metadata.json exists (reconstruct from SQLite if needed)
        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
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

        # Load metadata (guaranteed to exist after _ensure_loop_metadata)
        metadata_file = loop_dir / "metadata.json"
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
        persistence_manager = AgentLoopCheckpointPersistenceManager(config=d._config)

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
        from soothe.core.agent_loop.state.persistence.manager import (
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

        # Self-healing: ensure metadata.json exists (reconstruct from SQLite if needed)
        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
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

        persistence_manager = AgentLoopCheckpointPersistenceManager(config=d._config)

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
        from soothe.core.agent_loop.state.persistence.manager import (
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

        # Self-healing: ensure metadata.json exists (reconstruct from SQLite if needed)
        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
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

        persistence_manager = AgentLoopCheckpointPersistenceManager(config=d._config)

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

        from soothe.core.agent_loop.state.persistence.directory_manager import (
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

        # Self-healing: ensure metadata.json exists (reconstruct from SQLite if needed)
        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
            # Already deleted or never existed
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

        # Delete loop directory and SQLite data (IG-246: comprehensive cleanup)
        try:
            import aiosqlite

            # Delete filesystem directory
            shutil.rmtree(loop_dir)
            logger.info("Deleted loop directory: %s", loop_id)

            # Delete from SQLite (all 4 tables)
            db_path = PersistenceDirectoryManager.get_loop_checkpoint_path()
            if db_path.exists():
                async with aiosqlite.connect(db_path) as db:
                    await db.execute("DELETE FROM agentloop_loops WHERE loop_id = ?", (loop_id,))
                    await db.execute("DELETE FROM checkpoint_anchors WHERE loop_id = ?", (loop_id,))
                    await db.execute("DELETE FROM failed_branches WHERE loop_id = ?", (loop_id,))
                    await db.execute("DELETE FROM goal_records WHERE loop_id = ?", (loop_id,))
                    await db.commit()
                    logger.info("Deleted loop %s from SQLite database", loop_id)

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

        # Self-healing: ensure metadata.json exists (reconstruct from SQLite if needed)
        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
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
        await d._session_manager.subscribe_loop(client_id, loop_id, verbosity=verbosity)
        session = await d._session_manager.get_session(client_id)
        if session:
            await session.transport.send(
                session.transport_client,
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
        import json
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

        # Self-healing: ensure metadata.json exists (reconstruct from SQLite if needed)
        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
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

        Create fresh loop with new loop_id for new query/conversation.

        Args:
            client_id: Client connection identifier.
            msg: Request message (no parameters required).
        """
        import json
        from datetime import UTC, datetime

        from uuid_utils import uuid7

        from soothe.core.agent_loop.state.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )

        d = self._daemon
        request_id = msg.get("request_id")

        # Generate new loop_id
        loop_id = str(uuid7())

        try:
            resolve_loop_daemon_workspace(loop_id)
        except ValueError:
            logger.warning("Skipping loop workspace init for invalid loop_id %s", loop_id)
        except OSError as e:
            logger.warning("Could not create loop workspace directory: %s", e)

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
        """Handle loop_input RPC: authorize, then enqueue to the loop's isolated input queue."""
        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")
        prompt_text = _coerce_loop_input_text(msg.get("content"))

        if not loop_id or prompt_text is None:
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

        loop_dir = await self._ensure_loop_metadata(loop_id)
        if loop_dir is None:
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

        logger.info(
            "Queueing input for loop %s: %s",
            loop_id,
            preview_first(prompt_text, 50),
        )

        await d._loop_input_dispatcher.enqueue(
            loop_id,
            {
                "type": "input",
                "text": prompt_text,
                "client_id": client_id,
                **_queue_options_from_daemon_message(msg),
            },
        )

        await d._send_client_message(
            client_id,
            {
                "type": "loop_input_response",
                "loop_id": loop_id,
                "success": True,
                "request_id": request_id,
            },
        )

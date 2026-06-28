"""Transport message dispatch for the daemon (IG-110).

Maps JSON message types to handlers using ``SootheRunner`` public APIs instead
of reaching into ``runner._durability``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import ValidationError
from soothe import __version__ as core_version
from soothe.foundation.loop.state.persistence.directory_manager import PersistenceDirectoryManager
from soothe.utils.text_preview import preview_first
from soothe_sdk.client.protocol import _serialize_for_json

from soothe_daemon import __version__ as daemon_version
from soothe_daemon.bootstrap.logging import set_client_id
from soothe_daemon.protocol.error_codes import (
    ErrorCode,
    ProtocolError,
    build_error_response,
)
from soothe_daemon.protocol.schemas import PARAMS_REGISTRY
from soothe_daemon.services.image_understanding import validate_and_normalize_image_attachments

logger = logging.getLogger(__name__)

_LOOP_PROMPT_PREVIEW_MAX = 200
_LOOP_PROMPT_SCAN_LIMIT = 32


def _peek_loop_prompt(loop_id: str) -> str | None:
    """Return the loop's initial user prompt from ``cards.jsonl``, if available.

    The /resume selector needs a short identifying snippet per loop. The
    cheapest authoritative source is the loop's display card ledger: the first
    ``op=create, kind=user`` line carries the original goal text. We scan only
    the first few records so a huge ledger does not slow the list RPC.

    Args:
        loop_id: Loop identifier whose cards.jsonl should be peeked.

    Returns:
        Stripped prompt text (capped at ``_LOOP_PROMPT_PREVIEW_MAX`` chars), or
        ``None`` when the ledger has no user card or cannot be read.
    """
    try:
        path = PersistenceDirectoryManager.get_loop_directory(loop_id) / "cards.jsonl"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as fh:
            for index, line in enumerate(fh):
                if index >= _LOOP_PROMPT_SCAN_LIMIT:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("op") != "create" or record.get("kind") != "user":
                    continue
                data = record.get("data")
                if not isinstance(data, dict):
                    continue
                content = data.get("content")
                if not isinstance(content, str):
                    continue
                cleaned = " ".join(content.split())
                if not cleaned:
                    return None
                if len(cleaned) > _LOOP_PROMPT_PREVIEW_MAX:
                    cleaned = cleaned[: _LOOP_PROMPT_PREVIEW_MAX - 1] + "…"
                return cleaned
    except Exception:  # noqa: BLE001 — peek is best-effort, never block the RPC
        logger.debug("peek_loop_prompt failed for %s", loop_id, exc_info=True)
    return None


# Client messages logged at DEBUG on every dispatch; skip types that poll frequently.
_SKIP_PER_MESSAGE_DEBUG_TYPES = frozenset({"daemon_ready", "daemon_status", "ping", "pong"})

# Daemon-supported capabilities for connection_ack negotiation (RFC-450 §8.2).
_DAEMON_CAPABILITIES = ["streaming", "batch", "heartbeat"]

# Messages exempt from handshake-complete enforcement (RFC-450 §8.2 §8.3).
# connection_init is the handshake itself; ping/pong must work even before the
# handshake completes so a slow client can keep the connection alive.
_HANDSHAKE_EXEMPT_TYPES = frozenset({"connection_init", "ping", "pong"})

# Protocol-1 envelope message classes (RFC-450 §5/§9).  When ``msg["type"]`` is
# one of these, ``dispatch()`` unwraps the envelope into the legacy flat format
# the handlers expect before the registry lookup.
_ENVELOPE_TYPES = frozenset({"request", "notification", "subscribe", "unsubscribe"})

# Method-name overrides for envelope → flat-type translation.  The SDK uses
# different method names in the protocol-1 envelope than the legacy flat ``type``
# values in HANDLER_REGISTRY.  This table maps the SDK method to the flat type.
# Methods not listed here pass through unchanged (e.g. ``loop_list`` → ``loop_list``).
_METHOD_TO_FLAT_TYPE: dict[str, str] = {
    # notification methods
    "slash_command": "command",  # SDK notify("slash_command") → _handle_command
    "disconnect": "detach",  # SDK notify("disconnect") → _handle_detach
    # subscribe methods
    "loop_events": "loop_subscribe",  # SDK subscribe("loop_events") → _handle_loop_subscribe
    "autopilot_events": "autopilot_subscribe",  # → _handle_autopilot_subscribe
    # request methods
    "rpc_command": "command_request",  # SDK request("rpc_command") → _handle_command_request
}


# ---------------------------------------------------------------------------
# Pydantic param models and PARAMS_REGISTRY are defined in schemas.py
# (RFC-450 §6.2).  The router imports the registry for its dispatch-time
# param validation.  All models use ``extra = "allow"`` so existing clients
# that send flat top-level fields (e.g. ``loop_id`` at the message root) are
# not rejected during the incremental migration window.
# ---------------------------------------------------------------------------


def _queue_options_from_daemon_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional runner fields for ``loop_input`` messages (IG-362).

    Args:
        msg: Raw client message dict.

    Returns:
        Keys to merge into the internal queue payload: ``autonomous``,
        ``max_iterations``, ``preferred_subagent``, ``model``,
        ``model_params``, ``intent_hint`` (normalized to lowercase when set),
        ``clarification_mode`` (RFC-622, normalized to ``"auto"``/``"manual"`` or ``None``).
    """
    max_iterations = msg.get("max_iterations")
    parsed_max: int | None = (
        max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else None
    )
    preferred_subagent = msg.get("preferred_subagent")
    preferred_norm = (
        preferred_subagent.strip() or None if isinstance(preferred_subagent, str) else None
    )
    raw_clar_mode = msg.get("clarification_mode")
    if isinstance(raw_clar_mode, str):
        candidate = raw_clar_mode.strip().lower()
        clarification_mode_norm: str | None = candidate if candidate in ("auto", "manual") else None
    else:
        clarification_mode_norm = None
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
    raw_clar_answers = msg.get("clarification_answers")
    clarification_answers: list[str] | None
    if isinstance(raw_clar_answers, list) and raw_clar_answers:
        clarification_answers = [str(a) for a in raw_clar_answers]
    else:
        clarification_answers = None
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
        "clarification_mode": clarification_mode_norm,
        "clarification_answer": bool(msg.get("clarification_answer", False)),
        "clarification_answers": clarification_answers,
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
    """Dispatches client messages by ``type`` field using a registry table.

    The ``HANDLER_REGISTRY`` maps each supported ``type`` value to the name of
    the async ``_handle_*`` method that processes it.  ``dispatch()`` performs
    a dict lookup instead of a linear ``if msg_type == ...`` chain, validates
    params via ``PARAMS_REGISTRY``, and sends standardized ``ErrorCode``
    responses for unknown types (-32601) and param validation failures
    (-32602).
    """

    # Maps message ``type`` → handler method name (bound on the instance).
    # ``daemon_ready`` is a legacy alias retained for backwards compatibility;
    # it replies with the daemon readiness message.
    HANDLER_REGISTRY: dict[str, str] = {
        "connection_init": "_handle_connection_init",
        "ping": "_handle_ping",
        "pong": "_handle_pong",
        "command": "_handle_command",
        "command_request": "_handle_command_request",
        "detach": "_handle_detach",
        "daemon_ready": "_handle_daemon_ready",
        "auth": "_handle_auth",
        "auth_refresh": "_handle_auth_refresh",
        "loop_list": "_handle_loop_list",
        "loop_get": "_handle_loop_get",
        "loop_tree": "_handle_loop_tree",
        "loop_prune": "_handle_loop_prune",
        "loop_delete": "_handle_loop_delete",
        "loop_reattach": "_handle_loop_reattach",
        "loop_subscribe": "_handle_loop_subscribe",
        "loop_detach": "_handle_loop_detach",
        "loop_new": "_handle_loop_new",
        "loop_input": "_handle_loop_input",
        "loop_messages": "_handle_loop_messages",
        "loop_state_get": "_handle_loop_state_get",
        "loop_state_update": "_handle_loop_state_update",
        "loop_cards_fetch": "_handle_loop_cards_fetch",
        "skills_list": "_handle_skills_list",
        "invoke_skill": "_handle_invoke_skill",
        "models_list": "_handle_models_list",
        "mcp_status": "_handle_mcp_status",
        "daemon_status": "_handle_daemon_status",
        "daemon_shutdown": "_handle_daemon_shutdown",
        "config_get": "_handle_config_get",
        "job_create": "_handle_job_create",
        "job_status": "_handle_job_status",
        "job_pause": "_handle_job_pause",
        "job_resume": "_handle_job_resume",
        "job_cancel": "_handle_job_cancel",
        "job_dag": "_handle_job_dag",
        "job_guidance": "_handle_job_guidance",
        "autopilot_subscribe": "_handle_autopilot_subscribe",
        "autopilot_unsubscribe": "_handle_autopilot_unsubscribe",
    }

    def __init__(self, daemon: Any) -> None:
        """Keep a reference to the daemon for config, runner, and session access."""
        self._daemon = daemon
        # Per-client handshake state (RFC-450 §8.2). Maps client_id →
        # (proto_version, capabilities). Legacy _ClientConn objects also carry
        # the flag on the object itself.
        self._handshake_state: dict[Any, tuple[str, list[str]]] = {}

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

    @staticmethod
    def _unwrap_envelope(msg_type: str, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Translate a protocol-1 envelope to the legacy flat handler format.

        The handlers expect messages keyed by ``type`` with operation fields at
        the top level (e.g. ``{"type": "loop_list", "verbose": True}``).  The
        protocol-1 envelope wraps these as ``{"type": "request", "method":
        "loop_list", "params": {"verbose": True}, "id": "..."}``.

        This method extracts ``method`` and ``params`` from the envelope and
        builds a flat dict whose ``type`` is the mapped method name (see
        ``_METHOD_TO_FLAT_TYPE`` for overrides like ``slash_command`` →
        ``command``).  The envelope ``id`` is carried as both ``request_id``
        and ``id`` so handlers and error responses can correlate it.

        ``params is None`` is treated as ``{}`` because the SDK drops empty
        params dicts to keep the wire form compact.

        Args:
            msg_type: The envelope ``type`` (request/notification/subscribe/
                unsubscribe).
            msg: The full envelope message dict.

        Returns:
            A flat message dict ready for handler dispatch, or ``None`` if the
            envelope is malformed (missing ``method``).
        """
        method = msg.get("method")
        # unsubscribe carries no method — the target is inferred from params.
        if msg_type != "unsubscribe" and not method:
            return None

        params = msg.get("params")
        if not isinstance(params, dict):
            params = {}

        proto = msg.get("proto", "1")
        envelope_id = msg.get("id")

        if msg_type == "unsubscribe":
            # No method field: infer the flat type from params content.
            flat_type = "loop_detach" if "loop_id" in params else "autopilot_unsubscribe"
        else:
            flat_type = _METHOD_TO_FLAT_TYPE.get(method, method)

        flat: dict[str, Any] = {
            "proto": proto,
            "type": flat_type,
        }
        # request and subscribe carry a correlation id; notifications do not.
        if msg_type in ("request", "subscribe", "unsubscribe") and envelope_id is not None:
            flat["request_id"] = envelope_id
            flat["id"] = envelope_id
        flat.update(params)
        return flat

    async def dispatch(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle a single client message via the ``HANDLER_REGISTRY`` dispatch table.

        Performs a dict lookup by ``msg.get("type")`` instead of a linear
        if-chain.  Unknown types receive ``-32601 METHOD_NOT_FOUND``; param
        validation failures receive ``-32602 INVALID_PARAMS``; handler-raised
        ``ProtocolError`` exceptions are serialized to the standard error
        envelope.

        Args:
            client_id: Client connection identifier.
            msg: Decoded message dict.
        """
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

        # -- Handshake enforcement (RFC-450 §8.2) -----------------------------
        # Messages received before connection_init/ack completes are rejected
        # with -32600 INVALID_REQUEST, except connection_init itself and
        # ping/pong (which may arrive during a slow handshake).
        if msg_type not in _HANDSHAKE_EXEMPT_TYPES:
            if not self._is_handshake_complete(client_id):
                err = build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "Handshake must complete before sending messages",
                    data={"type": msg_type},
                )
                await d._send_client_message(client_id, err)
                return

        # -- Protocol-1 envelope unwrapping (RFC-450 §5/§9) -------------------
        # When the message is a protocol-1 envelope (type is request/notification/
        # subscribe/unsubscribe), translate it to the legacy flat format the
        # handlers expect: type=method (with method-name overrides), params
        # spread to the top level, request_id/id carried from the envelope id.
        # Treat missing params as {} since the SDK drops empty params dicts.
        if msg_type in _ENVELOPE_TYPES:
            unwrapped = self._unwrap_envelope(msg_type, msg)
            if unwrapped is None:
                err = build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    f"Invalid envelope: missing 'method' for type={msg_type}",
                    request_id=msg.get("id"),
                    data={"type": msg_type},
                )
                await d._send_client_message(client_id, err)
                return
            msg = unwrapped
            msg_type = msg.get("type", "")

        # -- Registry dispatch -------------------------------------------------
        handler_name = self.HANDLER_REGISTRY.get(msg_type)
        if handler_name is None:
            # Unknown message type → -32601 METHOD_NOT_FOUND (replaces the
            # previous silent debug log).
            err = build_error_response(
                ErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {msg_type}",
                request_id=msg.get("request_id"),
                data={"method": msg_type},
            )
            await d._send_client_message(client_id, err)
            logger.debug("[MsgRouter] Unknown message type: %s", msg_type)
            return

        # -- Param validation (RFC-450 §6) -------------------------------------
        # Look up the params model by (type, method) for the envelope format,
        # falling back to (type, None) for legacy flat messages.
        method = msg.get("method")
        params_model = PARAMS_REGISTRY.get((msg_type, method))
        if params_model is None and method is not None:
            params_model = PARAMS_REGISTRY.get((msg_type, None))
        if params_model is not None:
            try:
                # In the envelope format, operation fields live under
                # ``params``.  In the legacy flat format, they live at the
                # top level of ``msg``.  Validate whichever carries the data.
                # All models use ``extra = "allow"`` so envelope keys pass.
                params = msg.get("params")
                target = params if isinstance(params, dict) else msg
                params_model.model_validate(target)
            except ValidationError as exc:
                errors = [
                    f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
                ]
                err = build_error_response(
                    ErrorCode.INVALID_PARAMS,
                    "Invalid params",
                    request_id=msg.get("request_id") or msg.get("id"),
                    data={"errors": errors},
                )
                await d._send_client_message(client_id, err)
                logger.debug(
                    "[MsgRouter] Param validation failed for type=%s: %s",
                    msg_type,
                    errors,
                )
                return

        # -- Handler call ------------------------------------------------------
        handler = getattr(self, handler_name)
        try:
            await handler(client_id, msg)
        except ProtocolError as exc:
            err = build_error_response(
                exc.code,
                exc.message,
                request_id=msg.get("request_id"),
                data=exc.data if exc.data else None,
            )
            await d._send_client_message(client_id, err)
            logger.debug(
                "[MsgRouter] Handler %s raised ProtocolError: %s",
                handler_name,
                exc.message,
            )

    # -- Handshake & heartbeat handlers (RFC-450 §8) -------------------------

    @staticmethod
    def _handshake_key(client_id: Any) -> Any:
        """Return a hashable key for ``client_id`` (handles unhashable _ClientConn).

        Args:
            client_id: Client identifier (string, int, or connection object).

        Returns:
            A hashable key: ``id(client_id)`` for unhashable objects, otherwise
            the original ``client_id``.
        """
        try:
            hash(client_id)
            return client_id
        except TypeError:
            return id(client_id)

    def _is_handshake_complete(self, client_id: Any) -> bool:
        """Check whether the protocol-1 handshake has completed for this client.

        Checks the router's per-client dict first, then falls back to the
        ``_ClientConn.handshake_complete`` flag for legacy TCP connections.
        When no ``_ClientConn`` is found (e.g. WebSocket sessions tracked by
        ``ClientSessionManager``), the handshake is enforced at the transport
        layer, so this method returns ``True`` to allow dispatch.

        Args:
            client_id: Client identifier or connection object.

        Returns:
            ``True`` if the handshake is complete or enforcement is deferred
            to the transport layer.
        """
        key = self._handshake_key(client_id)
        if key in self._handshake_state:
            return True
        conn = self._lookup_client_conn(client_id)
        if conn is not None:
            return getattr(conn, "handshake_complete", False)
        # WebSocket sessions enforce the handshake in the channel handler.
        return True

    def _lookup_client_conn(self, client_id: Any) -> Any:
        """Find a ``_ClientConn`` by client_id, if any.

        Args:
            client_id: Client identifier (string id or connection object).

        Returns:
            The matching ``_ClientConn`` or ``None``.
        """
        d = self._daemon
        clients = getattr(d, "_clients", None)
        if not clients:
            return None
        # _ClientConn objects are stored directly in the list
        if hasattr(client_id, "writer"):
            for c in clients:
                if c is client_id:
                    return c
            return None
        # Legacy TCP clients are dispatched as ``legacy:{id(client)}``
        if isinstance(client_id, str) and client_id.startswith("legacy:"):
            try:
                obj_id = int(client_id.split(":", 1)[1])
            except ValueError:
                return None
            for c in clients:
                if id(c) == obj_id:
                    return c
        return None

    def _mark_handshake_complete(
        self, client_id: Any, proto_version: str, capabilities: list[str]
    ) -> None:
        """Mark the handshake as complete and store negotiated parameters.

        Args:
            client_id: Client identifier or connection object.
            proto_version: Negotiated protocol version.
            capabilities: Negotiated capabilities (intersection).
        """
        key = self._handshake_key(client_id)
        self._handshake_state[key] = (proto_version, capabilities)
        conn = self._lookup_client_conn(client_id)
        if conn is not None:
            conn.handshake_complete = True
            conn.proto_version = proto_version
            conn.negotiated_capabilities = capabilities
        # Also track in the WebSocket channel's client info (if any) so the
        # transport layer can enforce handshake ordering on subsequent messages.
        d = self._daemon
        chan = getattr(d, "_channel_manager", None)
        if chan is not None:
            for ch in getattr(chan, "_channels", {}).values():
                ws_clients = getattr(ch, "_clients", None)
                if not ws_clients:
                    continue
                for _ws, info in ws_clients.items():
                    if info.get("client_id") == client_id:
                        info["handshake_complete"] = True
                        info["proto_version"] = proto_version
                        info["negotiated_capabilities"] = capabilities
                        break

    def _get_proto_version(self, client_id: Any) -> str | None:
        """Return the negotiated protocol version for a client, if any.

        Args:
            client_id: Client identifier.

        Returns:
            Protocol version string (e.g. ``"1"``) or ``None``.
        """
        key = self._handshake_key(client_id)
        entry = self._handshake_state.get(key)
        if entry is not None:
            return entry[0]
        conn = self._lookup_client_conn(client_id)
        if conn is not None:
            return getattr(conn, "proto_version", None)
        d = self._daemon
        chan = getattr(d, "_channel_manager", None)
        if chan is not None:
            for ch in getattr(chan, "_channels", {}).values():
                ws_clients = getattr(ch, "_clients", None)
                if not ws_clients:
                    continue
                for _ws, info in ws_clients.items():
                    if info.get("client_id") == client_id:
                        return info.get("proto_version")
        return None

    def _get_negotiated_capabilities(self, client_id: Any) -> list[str]:
        """Return the negotiated capabilities for a client, if any.

        Args:
            client_id: Client identifier.

        Returns:
            List of capability strings (may be empty).
        """
        key = self._handshake_key(client_id)
        entry = self._handshake_state.get(key)
        if entry is not None:
            return entry[1]
        conn = self._lookup_client_conn(client_id)
        if conn is not None:
            caps = getattr(conn, "negotiated_capabilities", None)
            return caps or []
        d = self._daemon
        chan = getattr(d, "_channel_manager", None)
        if chan is not None:
            for ch in getattr(chan, "_channels", {}).values():
                ws_clients = getattr(ch, "_clients", None)
                if not ws_clients:
                    continue
                for _ws, info in ws_clients.items():
                    if info.get("client_id") == client_id:
                        return info.get("negotiated_capabilities") or []
        return []

    def _mark_pong_received(self, client_id: Any) -> None:
        """Record that a pong was received (heartbeat liveness tracking).

        Args:
            client_id: Client identifier.
        """
        # The WebSocket channel tracks heartbeat liveness in its own client
        # info dict; for legacy TCP clients there is no heartbeat. This method
        # is a no-op extension point.
        d = self._daemon
        chan = getattr(d, "_channel_manager", None)
        if chan is not None:
            ws_chan = chan.get_channel("websocket") if hasattr(chan, "get_channel") else None
            if ws_chan is not None and hasattr(ws_chan, "_mark_pong_received"):
                ws_chan._mark_pong_received(client_id)

    async def _handle_connection_init(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``connection_init`` handshake message (RFC-450 §8.2).

        Parses client-declared protocol versions and capabilities, negotiates
        with the daemon's supported set, and responds with ``connection_ack``.

        Args:
            client_id: Client identifier.
            msg: Decoded ``connection_init`` message dict.
        """
        d = self._daemon
        params = msg.get("params") or {}
        accept_proto = params.get("accept_proto")
        if accept_proto is None:
            accept_proto = ["1"]
        client_capabilities = params.get("capabilities") or []

        ack = d.build_connection_ack(
            accept_proto=accept_proto,
            client_capabilities=client_capabilities,
        )
        result = ack.get("result") or {}

        # If incompatible, send ack and let the transport layer close the connection.
        if result.get("readiness_state") == "incompatible":
            await d._send_client_message(client_id, ack)
            logger.info(
                "[MsgRouter] Client %s rejected: no compatible protocol version",
                client_id,
            )
            return

        # Store negotiated parameters on the connection object.
        self._mark_handshake_complete(
            client_id,
            proto_version=result.get("protocol_version", "1"),
            capabilities=result.get("capabilities", []),
        )

        await d._send_client_message(client_id, ack)
        logger.info(
            "[MsgRouter] Handshake complete for client %s (proto=%s, caps=%s, state=%s)",
            client_id,
            result.get("protocol_version", "1"),
            result.get("capabilities", []),
            result.get("readiness_state", "unknown"),
        )

    async def _handle_ping(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``ping`` heartbeat message (RFC-450 §8.3).

        Responds with a ``pong`` message.

        Args:
            client_id: Client identifier.
            msg: Decoded ``ping`` message dict.
        """
        d = self._daemon
        pong = {"proto": "1", "type": "pong"}
        await d._send_client_message(client_id, pong)

    async def _handle_pong(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``pong`` heartbeat acknowledgment (RFC-450 §8.3).

        Pong is an acknowledgment of our ping; no response is sent.  This method
        records liveness via ``_mark_pong_received``.

        Args:
            client_id: Client connection identifier.
            msg: Decoded ``pong`` message dict.
        """
        self._mark_pong_received(client_id)

    async def _handle_command(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle legacy ``command`` (slash) messages.

        Routes ``/exit`` and ``/quit`` to detach, ``/cancel`` to loop
        cancellation, and everything else to the loop input dispatcher.

        Args:
            client_id: Client connection identifier.
            msg: Message dict with ``cmd`` field.
        """
        d = self._daemon
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
            err = build_error_response(
                ErrorCode.NO_LOOP_SUBSCRIPTION,
                "loop_subscribe required before slash commands",
            )
            await d._send_client_message(client_id, err)
            return
        await d._loop_input_dispatcher.enqueue(
            active_loop,
            {"type": "command", "cmd": cmd, "client_id": client_id},
        )

    async def _handle_detach(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``detach`` message — mark session as detached.

        Args:
            client_id: Client connection identifier.
            msg: Message dict.
        """
        d = self._daemon
        session = await d._session_manager.get_session(client_id)
        if session:
            session.detach_requested = True
        await d._send_client_message(client_id, {"type": "status", "state": "detached"})
        logger.info("Client %s requested detach - query will continue after disconnect", client_id)

    async def _handle_command_request(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``command_request`` RPC — enqueue structured command to loop.

        Args:
            client_id: Client connection identifier.
            msg: Message dict with ``request_id``.
        """
        d = self._daemon
        active_loop = await self._client_subscribed_loop_id(client_id)
        if not active_loop:
            err = build_error_response(
                ErrorCode.NO_LOOP_SUBSCRIPTION,
                "loop_subscribe required before command_request",
                request_id=msg.get("request_id"),
            )
            await d._send_client_message(client_id, err)
            return
        req = dict(msg)
        req["client_id"] = client_id
        await d._loop_input_dispatcher.enqueue(active_loop, req)

    async def _handle_daemon_ready(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle legacy ``daemon_ready`` message — reply with readiness info.

        Args:
            client_id: Client connection identifier.
            msg: Message dict.
        """
        d = self._daemon
        await d._send_client_message(client_id, d.daemon_ready_message())

    async def _handle_auth(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``auth`` WebSocket message (RFC-307 §WebSocket AKSK Flow).

        Args:
            client_id: Client identifier.
            msg: Message dict with ``access_key`` and ``secret_key``.
        """
        d = self._daemon
        from soothe_daemon.server.auth_handler import build_auth_response_error

        auth_handler = getattr(d, "_auth_handler", None)
        if auth_handler is None:
            await d._send_client_message(
                client_id,
                build_auth_response_error("identity_disabled"),
            )
            return

        access_key = msg.get("access_key", "")
        secret_key = msg.get("secret_key", "")

        if not access_key or not secret_key:
            await d._send_client_message(
                client_id,
                build_auth_response_error("missing_credentials"),
            )
            return

        response = auth_handler.handle_auth(access_key, secret_key)
        await d._send_client_message(client_id, response)

    async def _handle_auth_refresh(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``auth_refresh`` WebSocket message (RFC-307 §Token Refresh Flow).

        Args:
            client_id: Client identifier.
            msg: Message dict with ``refresh_token``.
        """
        d = self._daemon
        from soothe_daemon.server.auth_handler import build_refresh_response_error

        auth_handler = getattr(d, "_auth_handler", None)
        if auth_handler is None:
            await d._send_client_message(
                client_id,
                build_refresh_response_error("identity_disabled"),
            )
            return

        refresh_token = msg.get("refresh_token", "")
        if not refresh_token:
            await d._send_client_message(
                client_id,
                build_refresh_response_error("missing_refresh_token"),
            )
            return

        response = auth_handler.handle_refresh(refresh_token)
        await d._send_client_message(client_id, response)

    async def _handle_skills_list(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return wire-safe skill metadata for the daemon's agent config."""
        d = self._daemon
        from soothe.skills.catalog import wire_entries_for_agent_config

        # Use client's loop workspace if subscribed, otherwise cwd
        workspace: str | None = None
        loop_id = await self._client_subscribed_loop_id(client_id)
        if loop_id:
            current_thread_id = getattr(d, "_current_thread_id", None)
            ws_path = d._thread_registry.get_workspace(current_thread_id or loop_id)
            if ws_path:
                workspace = str(ws_path)
            else:
                # Thread registry not populated yet (before first loop_input);
                # read workspace from loop metadata set at loop_new time.
                meta = await d._persistence_manager.get_loop_metadata(loop_id)
                if meta:
                    raw_ws = meta.get("current_workspace") or meta.get("client_workspace")
                    if isinstance(raw_ws, str) and raw_ws.strip():
                        workspace = raw_ws.strip()

        skills = wire_entries_for_agent_config(d._config, workspace, skill_index=d._skill_index)
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

    async def _handle_mcp_status(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return MCP server status for the TUI MCP viewer."""
        d = self._daemon
        registry = d._mcp_registry
        if registry is None:
            await d._send_client_message(
                client_id,
                {
                    "type": "mcp_status_response",
                    "servers": [],
                    "request_id": msg.get("request_id"),
                },
            )
            return

        servers: list[dict[str, Any]] = []
        try:
            for name, conn in registry.connection_status().items():
                tools: list[dict[str, str]] = []
                for td in registry._tool_descriptors.get(name, []):
                    tools.append({"name": td.name, "description": td.description or ""})
                servers.append(
                    {
                        "name": name,
                        "transport": conn.transport.value
                        if hasattr(conn.transport, "value")
                        else str(conn.transport),
                        "connected": conn.connected,
                        "tools": tools,
                    }
                )
        except Exception:  # noqa: BLE001
            pass

        await d._send_client_message(
            client_id,
            {
                "type": "mcp_status_response",
                "servers": servers,
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
                build_error_response(
                    ErrorCode.INVALID_PARAMS,
                    "invoke_skill requires non-empty string field: skill",
                    request_id=msg.get("request_id"),
                ),
            )
            return

        args_val = msg.get("args", "")
        args = args_val if isinstance(args_val, str) else ""

        # Use client's loop workspace if subscribed, otherwise cwd
        workspace: str | None = None
        loop_id = await self._client_subscribed_loop_id(client_id)
        if loop_id:
            # Get workspace from thread registry (set by bind_execution_thread_for_loop)
            current_thread_id = getattr(d, "_current_thread_id", None)
            ws_path = d._thread_registry.get_workspace(current_thread_id or loop_id)
            if ws_path:
                workspace = str(ws_path)

        meta = resolve_skill_directory(d._config, raw_skill, workspace)
        if meta is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.SKILL_NOT_FOUND,
                    f"Unknown skill: {raw_skill.strip()!r}",
                    request_id=msg.get("request_id"),
                ),
            )
            return

        md = read_skill_markdown(meta)
        if md is None or not md.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.SKILL_LOAD_FAILED,
                    f"Could not read SKILL.md for skill: {meta.get('name', raw_skill)!r}",
                    request_id=msg.get("request_id"),
                ),
            )
            return

        active_loop = await self._client_subscribed_loop_id(client_id)
        if not active_loop:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.NO_LOOP_SUBSCRIPTION,
                    "loop_subscribe required before invoke_skill",
                    request_id=msg.get("request_id"),
                ),
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

        # Honor the client's RFC-622 mode for slash-skill turns too. Without
        # this, the synthetic loop input always carries None and the runner
        # falls back to ``config.agent.clarification.default_mode`` (typically
        # "auto"), so manual relay never engages for /skill:* invocations.
        clarification_mode = _queue_options_from_daemon_message(msg)["clarification_mode"]
        await d._loop_input_dispatcher.enqueue(
            active_loop,
            {
                "type": "input",
                "text": plain_user_line,
                "autonomous": False,
                "max_iterations": None,
                "preferred_subagent": None,
                "clarification_mode": clarification_mode,
                "client_id": client_id,
            },
        )

    async def _handle_daemon_status(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle daemon_status RPC request (IG-174 Phase 0).

        Args:
            client_id: Client connection identifier.
            msg: Request message with optional request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")

        # Check daemon running state
        running = d._running
        port_live = False
        channel_manager = d._channel_manager
        if channel_manager is not None:
            for channel in channel_manager.get_channel_info():
                if channel.get("type") == "websocket":
                    # Channels report client_count only; port is live when daemon is up.
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
            "readiness_state": d._readiness_state,
            "readiness_message": d._readiness_message,
            "daemon_version": daemon_version,
            "core_version": core_version,
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
            msg: Request message with optional ``filter`` and ``limit``.
                ``filter.status`` — narrows to one persisted status value.
                ``filter.exclude_empty`` — when True (default), hides loops
                with zero human + zero AI messages (IG-466).
                ``filter.workspace`` — narrows to loops with matching client_workspace.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        filter_data = msg.get("filter") or {}
        limit = msg.get("limit", 20)

        status_filter = filter_data.get("status") if isinstance(filter_data, dict) else None
        # Default to hiding empty loops so the picker stops showing bootstrap-only rows.
        exclude_empty = True
        if isinstance(filter_data, dict) and "exclude_empty" in filter_data:
            exclude_empty = bool(filter_data["exclude_empty"])
        workspace_filter = filter_data.get("workspace") if isinstance(filter_data, dict) else None

        rows = await d._persistence_manager.list_loops(
            status_filter=status_filter,
            limit=limit,
            exclude_empty=exclude_empty,
            workspace_filter=workspace_filter,
        )
        # Snapshot of loops with an active runner stream right now. Used to derive
        # `live` so consumers can distinguish stale "running" persisted status
        # from genuinely-running loops (this daemon only).
        active_loop_ids: set[str] = set(getattr(d, "_active_stream_loop_ids", ()) or ())
        loops = []
        for row in rows:
            loop_id = row["loop_id"]
            entry: dict[str, Any] = {
                "loop_id": loop_id,
                "status": row.get("status", "unknown"),
                "live": loop_id in active_loop_ids,
                "threads": len(row.get("thread_ids") or []),
                "goals": row.get("total_goals_completed", 0),
                "switches": row.get("total_thread_switches", 0),
                "human_messages": row.get("human_message_count", 0),
                "ai_messages": row.get("ai_message_count", 0),
                "last_message_at": row.get("last_message_at"),
                "updated_at": row.get("updated_at"),
                # Wire as full ISO 8601 (including the ``+00:00`` offset). The
                # previous ``[:16]`` truncation stripped the timezone suffix,
                # so the client's ``datetime.fromisoformat`` returned a naive
                # datetime that ``.astimezone()`` then treated as local — an
                # 8h drift in UTC+8 ("8h ago" for a loop created minutes ago).
                "created": row.get("created_at") or "",
                "duration_ms": int(row.get("total_duration_ms") or 0),
                "client_workspace": row.get("client_workspace"),
            }
            prompt = _peek_loop_prompt(loop_id)
            if prompt:
                entry["prompt"] = prompt
            loops.append(entry)

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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        # Load metadata from DB
        metadata = await d._persistence_manager.get_loop_metadata(loop_id)
        if metadata is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=request_id,
                ),
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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=request_id,
                ),
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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=request_id,
                ),
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
        from soothe_daemon.runtime.loop_gc import purge_loop_fully

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
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
        from soothe_daemon.event.reattachment import schedule_loop_reattach

        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=request_id,
                ),
            )
            return

        from soothe_daemon.runtime.loop_autopilot_mode import ensure_loop_autopilot_mode

        autopilot_mode = await ensure_loop_autopilot_mode(d, loop_id, broadcast=False)

        wire_tier = msg.get("wire_tier", "full")
        # IG-441: three first-class modes (batch / adaptive / streaming);
        # default to ``adaptive`` for new subscribers since it gives the best
        # all-round UX. Unknown values fall back to adaptive too.
        stream_delivery = msg.get("stream_delivery", "adaptive")
        if stream_delivery not in ("batch", "adaptive", "streaming"):
            stream_delivery = "adaptive"
        await d._session_manager.subscribe_loop(
            client_id,
            loop_id,
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
                },
            )

        await d._send_client_message(
            client_id,
            {
                "type": "loop_subscribe_response",
                "loop_id": loop_id,
                "success": True,
                "autopilot_mode": autopilot_mode,
                "request_id": request_id,
            },
        )

        schedule_loop_reattach(str(loop_id), d, client_id)

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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        # Check loop exists in DB
        if not await self._ensure_loop_exists(loop_id):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=request_id,
                ),
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
        from soothe.foundation.loop.state.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.foundation.workspace import resolve_loop_workspace, validate_client_workspace
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
            from soothe.foundation.workspace import resolve_daemon_workspace

            resolved_workspace = resolve_daemon_workspace()

        # RFC-621: translate client path to container path when workspace_mount configured.
        # Only translate when client_workspace was provided — daemon-fallback workspaces
        # (temp or $SOOTHE_HOME) are container-local and don't need translation.
        from soothe.foundation.workspace.resolution import translate_client_path_to_container

        mount = d._config.workspace_mount
        host_root = mount.host_root if mount and mount.is_configured else None
        container_root = mount.container_root if mount and mount.is_configured else None
        effective_workspace = resolved_workspace

        if client_workspace is not None and host_root is not None:
            try:
                effective_workspace = translate_client_path_to_container(
                    resolved_workspace,
                    host_root=host_root,
                    container_root=container_root,
                )
            except ValueError as e:
                logger.warning("[loop_new] Loop %s workspace mount error: %s", loop_id, e)
                await d._send_client_message(
                    client_id,
                    build_error_response(
                        ErrorCode.WORKSPACE_RESOLUTION_FAILED,
                        str(e),
                        request_id=request_id,
                    ),
                )
                return

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

        # last_message_at is populated on first counter increment, not at creation,
        # so empty-loop GC can detect bootstrap-only loops via COALESCE(last_message_at, created_at).
        meta_updates: dict[str, Any] = {
            "is_ephemeral": is_ephemeral,
            "current_workspace": str(effective_workspace),
        }
        if client_workspace is not None:
            meta_updates["client_workspace"] = client_workspace
        if user is not None:
            meta_updates["user_id"] = user
        if client_workspace_id is not None:
            meta_updates["client_workspace_id"] = client_workspace_id
        if host_root is not None:
            meta_updates["workspace_mapping"] = {
                "host_root": host_root,
                "container_root": container_root,
            }
        await d._persistence_manager.update_loop_metadata(loop_id, **meta_updates)

        from soothe_daemon.runtime.loop_autopilot_mode import ensure_loop_autopilot_mode

        autopilot_mode = await ensure_loop_autopilot_mode(d, loop_id, broadcast=True)

        logger.info(
            "Created new loop %s (ephemeral=%s workspace=%s autopilot_mode=%s)",
            loop_id,
            is_ephemeral,
            effective_workspace,
            autopilot_mode,
        )

        # Send response
        response_msg: dict[str, Any] = {
            "type": "loop_new_response",
            "loop_id": loop_id,
            "success": True,
            "is_ephemeral": is_ephemeral,
            "autopilot_mode": autopilot_mode,
            "request_id": request_id,
        }
        if host_root is not None:
            response_msg["workspace_mapping"] = {
                "host_root": host_root,
                "container_root": container_root,
                "client_workspace": client_workspace,
                "container_workspace": str(effective_workspace),
            }
        await d._send_client_message(client_id, response_msg)

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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id is required",
                    request_id=request_id,
                ),
            )
            return

        if intent_hint_preview not in ("direct_llm", "image_to_text") and prompt_text is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id and non-empty content (string or object with text) required",
                    request_id=request_id,
                ),
            )
            return

        if not await self._ensure_loop_exists(loop_id):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_FOUND,
                    f"Loop {loop_id} not found",
                    request_id=request_id,
                ),
            )
            return

        session = await d._session_manager.get_session(client_id)
        if not session or loop_id not in session.subscriptions:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_NOT_SUBSCRIBED,
                    "loop_subscribe required before loop_input",
                    request_id=request_id,
                ),
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
                    build_error_response(
                        ErrorCode.INVALID_PARAMS,
                        attachment_error,
                        request_id=request_id,
                    ),
                )
                return
            attachments_for_queue = normalized_attachments or None
        else:
            attachments_for_queue = None

        if intent_hint_preview in ("direct_llm", "image_to_text"):
            if intent_hint_preview == "image_to_text" and not attachments_for_queue:
                await d._send_client_message(
                    client_id,
                    build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        "intent_hint image_to_text requires non-empty attachments",
                        request_id=request_id,
                    ),
                )
                return
            if (
                intent_hint_preview == "direct_llm"
                and not prompt_text
                and not attachments_for_queue
            ):
                await d._send_client_message(
                    client_id,
                    build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        "intent_hint direct_llm requires non-empty content or attachments",
                        request_id=request_id,
                    ),
                )
                return
            if intent_hint_preview == "image_to_text":
                q_opts["intent_hint"] = "direct_llm"

        response_schema = q_opts.get("response_schema")
        if response_schema is not None:
            if intent_hint_preview not in (None, "direct_llm", "image_to_text"):
                await d._send_client_message(
                    client_id,
                    build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        "response_schema is only supported with intent_hint direct_llm",
                        request_id=request_id,
                    ),
                )
                return
            if attachments_for_queue:
                await d._send_client_message(
                    client_id,
                    build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        "response_schema is not supported with direct_llm attachments",
                        request_id=request_id,
                    ),
                )
                return
            try:
                from soothe.utils.llm.schema_wire import validate_response_schema

                q_opts["response_schema"] = validate_response_schema(response_schema)
            except ValueError as exc:
                await d._send_client_message(
                    client_id,
                    build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        str(exc),
                        request_id=request_id,
                    ),
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
            await d._persistence_manager.increment_loop_message_count(loop_id, human=1)
        except Exception:
            logger.warning(
                "Failed to increment human_message_count for loop %s", loop_id, exc_info=True
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
                build_error_response(
                    ErrorCode.RUNNER_UNAVAILABLE,
                    "Daemon runner not initialized",
                    request_id=request_id,
                ),
            )
            return

        if not loop_id:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        try:
            from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, str(loop_id))
        except Exception as exc:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_CONTEXT_ERROR,
                    str(exc),
                    request_id=request_id,
                ),
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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        runner = d._runner
        if runner is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.RUNNER_UNAVAILABLE,
                    "Daemon runner not initialized",
                    request_id=request_id,
                ),
            )
            return

        try:
            from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, str(loop_id))
            values = await runner.get_thread_state_values(checkpoint_thread_id)
        except Exception as exc:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_STATE_ERROR,
                    str(exc),
                    request_id=request_id,
                ),
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
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id and values dict required",
                    request_id=request_id,
                ),
            )
            return

        runner = d._runner
        if runner is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.RUNNER_UNAVAILABLE,
                    "Daemon runner not initialized",
                    request_id=request_id,
                ),
            )
            return

        raw_as_node = msg.get("as_node")
        as_node = str(raw_as_node) if isinstance(raw_as_node, str) and raw_as_node else None

        try:
            from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, str(loop_id))
            kwargs: dict[str, Any] = {}
            if as_node is not None:
                kwargs["as_node"] = as_node
            await runner.update_thread_state_values(
                checkpoint_thread_id, dict(raw_values), **kwargs
            )
        except Exception as exc:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_STATE_ERROR,
                    str(exc),
                    request_id=request_id,
                ),
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

    async def _handle_loop_cards_fetch(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Return the bound display-card snapshot for a loop (RFC-413).

        The card ledger is derived lazily from the loop's checkpoint + activity
        log on first access; this RPC waits for eager backfill if needed so the
        client receives a complete snapshot. Typical cost is ~50 ms for an
        active loop's cached ledger, ~1–3 s for a pre-413 loop's first read.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        loop_id = msg.get("loop_id")

        if not loop_id:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "loop_id required",
                    request_id=request_id,
                ),
            )
            return

        card_manager = getattr(d, "_card_manager", None)
        if card_manager is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.CARD_MANAGER_UNAVAILABLE,
                    "Daemon card manager not initialized",
                    request_id=request_id,
                ),
            )
            return

        from soothe_sdk.display.card_ledger import card_to_wire_dict

        try:
            loop_id_str = str(loop_id)
            if await card_manager.is_display_empty(loop_id_str):
                ledger = await card_manager.ensure_for_loop(loop_id_str)
                snapshot = ledger.snapshot()
                wire_cards: list[dict[str, Any]] = []
                latest_seq = 0
                context_tokens = 0
            else:
                # Force re-derivation so TUI resume receives the latest final
                # goal-completion response, not a stale cached snapshot.
                ledger = await card_manager.refresh(loop_id_str)
                snapshot = ledger.snapshot()
                wire_cards = [card_to_wire_dict(card) for card in snapshot]
                latest_seq = ledger.next_seq() - 1
                context_tokens = await self._read_loop_context_tokens(loop_id_str)
        except Exception as exc:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.CARDS_FETCH_FAILED,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "loop_cards_fetch_response",
                "request_id": request_id,
                "loop_id": str(loop_id),
                "cards": wire_cards,
                "seq": latest_seq,
                "context_tokens": context_tokens,
            },
        )

    async def _read_loop_context_tokens(self, loop_id: str) -> int:
        """Best-effort read of ``_context_tokens`` from the loop's checkpoint.

        Returns 0 on any failure — the TUI tolerates a zero token count
        (renders without the budget badge).
        """
        d = self._daemon
        runner = getattr(d, "_runner", None)
        if runner is None:
            return 0
        try:
            from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop

            checkpoint_thread_id = await bind_execution_thread_for_loop(d, loop_id)
            values = await runner.get_thread_state_values(checkpoint_thread_id)
        except Exception:
            logger.debug("Failed to read context_tokens for loop %s", loop_id, exc_info=True)
            return 0
        raw = values.get("_context_tokens") if isinstance(values, dict) else None
        if isinstance(raw, int) and raw >= 0:
            return raw
        return 0

    # ---------------------------------------------------------------------------
    # RFC-228: Autopilot Job IPC Handlers
    # ---------------------------------------------------------------------------

    async def _require_autopilot_service(
        self, client_id: Any, request_id: str | None
    ) -> Any | None:
        """Return the daemon's AutopilotService or send error response.

        Args:
            client_id: Client connection identifier.
            request_id: Optional request_id for error response.

        Returns:
            AutopilotService instance if available, None otherwise (error sent).
        """
        d = self._daemon
        service = getattr(d, "_autopilot_service", None)
        if service is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.AUTOPILOT_NOT_READY,
                    "Autopilot service not initialized or unavailable",
                    request_id=request_id,
                ),
            )
            return None
        return service

    async def _handle_job_create(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_create RPC request (RFC-228).

        Submit a root goal to AutopilotService, creating a new autopilot job.

        Args:
            client_id: Client connection identifier.
            msg: Request with goal (required), verification_rules (optional),
                workspace (optional), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        goal_text = msg.get("goal")
        # TODO: verification_rules to be passed to GoalEngine when supported
        _verification_rules = msg.get("verification_rules")  # noqa: F841

        if not isinstance(goal_text, str) or not goal_text.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "goal (non-empty string) is required",
                    request_id=request_id,
                ),
            )
            return

        # Resolve workspace path if provided
        workspace: str | None = None
        raw_workspace = msg.get("workspace")
        if raw_workspace and isinstance(raw_workspace, str) and raw_workspace.strip():
            try:
                from soothe.foundation.workspace import validate_client_workspace

                resolved = validate_client_workspace(raw_workspace.strip())
                workspace = str(resolved)
            except (ValueError, OSError):
                workspace = raw_workspace.strip()

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        # Submit root goal to AutopilotService
        try:
            goal = await service.submit_task(
                description=goal_text.strip(),
                priority=50,  # Default priority
                workspace=workspace,
            )
        except Exception as exc:
            logger.error("[JobCreate] Failed to submit task: %s", exc, exc_info=True)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_CREATE_FAILED,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "job_create_response",
                "job_id": goal.id,
                "status": goal.status,
                "request_id": request_id,
            },
        )
        logger.info("[JobCreate] Created job %s with goal: %s", goal.id, goal_text[:50])

    async def _handle_job_status(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_status RPC request (RFC-228).

        Query job state: goal status, counts, assigned workers.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id (required), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")

        if not isinstance(job_id, str) or not job_id.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "job_id is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        # Get root goal
        root_goal = await service.get_goal(job_id)
        if root_goal is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Job {job_id} not found",
                    request_id=request_id,
                ),
            )
            return

        # Use dag_snapshot to get goal descendants (RFC-228)
        dag = await service.dag_snapshot(job_id)
        nodes = dag.get("nodes", [])

        # Count goals by status
        active_count = sum(1 for n in nodes if n.get("status") == "active")
        completed_count = sum(1 for n in nodes if n.get("status") == "completed")
        failed_count = sum(1 for n in nodes if n.get("status") == "failed")
        cancelled_count = sum(1 for n in nodes if n.get("status") == "cancelled")
        total_count = len(nodes)

        # Collect workers assigned to active goals
        workers = [
            {"goal_id": n.get("id"), "loop_id": n.get("assigned_loop_id")}
            for n in nodes
            if n.get("status") == "active" and n.get("assigned_loop_id")
        ]

        # Get last error from failed goals
        last_error = None
        all_goals = await service.list_goals()
        for g in all_goals:
            if g.id == job_id or any(
                dep_id == job_id for dep_id in g.depends_on or []
            ):  # Approximate check
                if g.status == "failed" and g.error:
                    last_error = g.error
                    break

        await d._send_client_message(
            client_id,
            {
                "type": "job_status_response",
                "job_id": job_id,
                "status": root_goal.status,
                "active_goals": active_count,
                "completed_goals": completed_count,
                "failed_goals": failed_count,
                "cancelled_goals": cancelled_count,
                "total_goals": total_count,
                "workers": workers,
                "last_error": last_error,
                "request_id": request_id,
            },
        )

    async def _handle_job_pause(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_pause RPC request (RFC-228).

        Pause goal execution by suspending the root goal.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id (required), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")

        if not isinstance(job_id, str) or not job_id.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "job_id is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        goal_engine = service._ce

        # Check goal exists and is not already suspended
        goal = await goal_engine.get_goal(job_id)
        if goal is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Job {job_id} not found",
                    request_id=request_id,
                ),
            )
            return

        if goal.status == "suspended":
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_ALREADY_PAUSED,
                    f"Job {job_id} is already paused",
                    request_id=request_id,
                ),
            )
            return

        if goal.status in ("completed", "failed", "cancelled"):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_COMPLETED,
                    f"Job {job_id} is in terminal state {goal.status}",
                    request_id=request_id,
                ),
            )
            return

        # Suspend the root goal
        try:
            await goal_engine.suspend_goal(job_id, reason="user_pause")
        except Exception as exc:
            logger.error("[JobPause] Failed to suspend goal %s: %s", job_id, exc)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_PAUSE_FAILED,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "job_pause_response",
                "job_id": job_id,
                "status": "suspended",
                "request_id": request_id,
            },
        )
        logger.info("[JobPause] Paused job %s", job_id)

    async def _handle_job_resume(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_resume RPC request (RFC-228).

        Resume paused goal execution by reactivating the root goal.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id (required), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")

        if not isinstance(job_id, str) or not job_id.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "job_id is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        goal_engine = service._ce

        # Check goal exists and is suspended
        goal = await goal_engine.get_goal(job_id)
        if goal is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Job {job_id} not found",
                    request_id=request_id,
                ),
            )
            return

        if goal.status not in ("suspended", "blocked"):
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_PAUSED,
                    f"Job {job_id} is not paused (status: {goal.status})",
                    request_id=request_id,
                ),
            )
            return

        # Reactivate the root goal
        try:
            await goal_engine.reactivate_goal(job_id)
        except Exception as exc:
            logger.error("[JobResume] Failed to reactivate goal %s: %s", job_id, exc)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_RESUME_FAILED,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "job_resume_response",
                "job_id": job_id,
                "status": "pending",  # After reactivation, goal goes to pending
                "request_id": request_id,
            },
        )
        logger.info("[JobResume] Resumed job %s", job_id)

    async def _handle_job_cancel(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_cancel RPC request (RFC-228).

        Cancel job by cancelling the root goal via AutopilotService.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id (required), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")

        if not isinstance(job_id, str) or not job_id.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "job_id is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        # Cancel via AutopilotService (handles worker cleanup)
        try:
            cancelled = await service.cancel_goal(job_id, reason="user_cancel")
        except Exception as exc:
            logger.error("[JobCancel] Failed to cancel goal %s: %s", job_id, exc)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_CANCEL_FAILED,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        if cancelled is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Job {job_id} not found",
                    request_id=request_id,
                ),
            )
            return

        await d._send_client_message(
            client_id,
            {
                "type": "job_cancel_response",
                "job_id": job_id,
                "status": cancelled.status,
                "request_id": request_id,
            },
        )
        logger.info("[JobCancel] Cancelled job %s", job_id)

    async def _handle_job_dag(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_dag RPC request (RFC-228).

        Get GoalEngine DAG snapshot for visualization.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id (required), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")

        if not isinstance(job_id, str) or not job_id.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "job_id is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        # Check root goal exists
        root_goal = await service.get_goal(job_id)
        if root_goal is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Job {job_id} not found",
                    request_id=request_id,
                ),
            )
            return

        # Use AutopilotService.dag_snapshot() for visualization (RFC-228)
        dag = await service.dag_snapshot(job_id)

        await d._send_client_message(
            client_id,
            {
                "type": "job_dag_response",
                "job_id": job_id,
                "dag": dag,
                "request_id": request_id,
            },
        )

    async def _handle_job_guidance(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_guidance RPC request (RFC-228).

        Send user guidance to GoalEngine for absorption.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id, goal_id (optional), text, request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")
        goal_id = msg.get("goal_id")  # Optional - specific goal or root
        text = msg.get("text")

        if not isinstance(job_id, str) or not job_id.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "job_id is required",
                    request_id=request_id,
                ),
            )
            return

        if not isinstance(text, str) or not text.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "text (non-empty string) is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        goal_engine = service._ce

        # Determine target goal
        target_id = goal_id if goal_id else job_id
        target_goal = await goal_engine.get_goal(target_id)
        if target_goal is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.GOAL_NOT_FOUND,
                    f"Goal {target_id} not found",
                    request_id=request_id,
                ),
            )
            return

        # Absorb guidance via GoalEngine (RFC-228)
        scope = "goal" if goal_id else "job"
        absorbed = await goal_engine.absorb_guidance(target_id, text.strip(), scope=scope)

        logger.info(
            "[JobGuidance] Guidance for job=%s goal=%s absorbed=%s: %s",
            job_id,
            target_id,
            absorbed,
            text[:50],
        )

        await d._send_client_message(
            client_id,
            {
                "type": "job_guidance_response",
                "job_id": job_id,
                "goal_id": target_id,
                "absorbed": absorbed,
                "request_id": request_id,
            },
        )

    async def _handle_autopilot_subscribe(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_subscribe RPC request (RFC-228).

        Subscribe client to autopilot worker events (bypasses autopilot__* filter).

        Args:
            client_id: Client connection identifier.
            msg: Request with request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")

        session_manager = d._session_manager
        session = await session_manager.get_session(client_id)
        if session is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.NO_SESSION,
                    "Client session not found",
                    request_id=request_id,
                ),
            )
            return

        # Set autopilot subscription flag (enables worker event bypass)
        session.autopilot_subscribed = True

        # Subscribe to autopilot topic for client-visible events (RFC-228)
        await d._event_bus.subscribe("autopilot", session.event_queue)

        await d._send_client_message(
            client_id,
            {
                "type": "autopilot_subscribe_response",
                "client_id": client_id,
                "subscribed": True,
                "request_id": request_id,
            },
        )
        logger.info("[AutopilotSubscribe] Client %s subscribed to autopilot events", client_id)

    async def _handle_autopilot_unsubscribe(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_unsubscribe RPC request (RFC-228).

        Release autopilot worker event subscription.

        Args:
            client_id: Client connection identifier.
            msg: Request with request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")

        session_manager = d._session_manager
        session = await session_manager.get_session(client_id)
        if session is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.NO_SESSION,
                    "Client session not found",
                    request_id=request_id,
                ),
            )
            return

        # Clear autopilot subscription flag
        session.autopilot_subscribed = False

        # Unsubscribe from autopilot topic (RFC-228)
        await d._event_bus.unsubscribe("autopilot", session.event_queue)

        await d._send_client_message(
            client_id,
            {
                "type": "autopilot_unsubscribe_response",
                "client_id": client_id,
                "subscribed": False,
                "request_id": request_id,
            },
        )
        logger.info(
            "[AutopilotUnsubscribe] Client %s unsubscribed from autopilot events", client_id
        )

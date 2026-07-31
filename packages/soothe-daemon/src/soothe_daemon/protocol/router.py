"""Transport message dispatch for the daemon (IG-110).

Maps JSON message types to handlers using ``SootheRunner`` public APIs instead
of reaching into ``runner._durability``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import ValidationError
from soothe import __version__ as core_version
from soothe.sloop.checkpoints.directory_manager import PersistenceDirectoryManager
from soothe_nano.utils.text_preview import preview_first
from soothe_sdk.wire.protocol import _serialize_for_json

from soothe_daemon import __version__ as daemon_version
from soothe_daemon.bootstrap.logging import set_client_id
from soothe_daemon.protocol.error_codes import (
    ErrorCode,
    RpcProtocolError,
    build_error_response,
)
from soothe_daemon.protocol.intent_hints import validate_and_normalize_intent_hint
from soothe_daemon.protocol.schemas import PARAMS_REGISTRY
from soothe_daemon.protocol.validation import validate_message
from soothe_daemon.services.image_understanding import validate_and_normalize_image_attachments

logger = logging.getLogger(__name__)

_LOOP_PROMPT_PREVIEW_MAX = 200
_LOOP_AI_RESPONSE_PREVIEW_MAX = 160


def _peek_loop_prompt(loop_id: str) -> str | None:
    """Return the loop's initial user prompt from ``display.db``, if available."""
    try:
        from soothe_daemon.display.display_store import get_display_card_store

        return get_display_card_store().peek_user_prompt(
            loop_id, max_chars=_LOOP_PROMPT_PREVIEW_MAX
        )
    except Exception:  # noqa: BLE001 — peek is best-effort, never block the RPC
        logger.debug("peek_loop_prompt failed for %s", loop_id, exc_info=True)
    return None


def _peek_latest_assistant_response(loop_id: str) -> str | None:
    """Return latest assistant response preview from ``display.db``."""
    try:
        from soothe_daemon.display.display_store import get_display_card_store

        return get_display_card_store().peek_latest_assistant_response(
            loop_id,
            max_chars=_LOOP_AI_RESPONSE_PREVIEW_MAX,
        )
    except Exception:  # noqa: BLE001 — preview is best-effort, never block the RPC
        logger.debug("peek_latest_assistant_response failed for %s", loop_id, exc_info=True)
    return None


def _resolve_loop_topic(
    *,
    prompt: str | None,
    resume_topic: str | None,
) -> str:
    """Return the resume-picker topic label for one loop row."""
    stored = (resume_topic or "").strip()
    if stored:
        return stored
    goal_text = (prompt or "").strip()
    return goal_text or "(no goal)"


# Client messages logged at DEBUG on every dispatch; skip types that poll frequently.
_SKIP_PER_MESSAGE_DEBUG_TYPES = frozenset({"daemon_status", "ping", "pong"})

# Daemon-supported capabilities for connection_ack negotiation (RFC-450 §8.2).
_DAEMON_CAPABILITIES = ["streaming", "batch", "heartbeat", "receipts"]

# Messages exempt from handshake-complete enforcement (RFC-450 §8.2 §8.3).
# connection_init is the handshake itself; ping/pong must work even before the
# handshake completes so a slow client can keep the connection alive.
_HANDSHAKE_EXEMPT_TYPES = frozenset({"connection_init", "ping", "pong"})

# Protocol-1 envelope message classes (RFC-450 §5/§9). Messages of these types
# carry ``method``/``params``/``id`` and are dispatched to handlers by method.
_ENVELOPE_TYPES = frozenset({"request", "notification", "subscribe", "unsubscribe"})

# Method-name → handler method name for envelope dispatch (RFC-450 §5/§9). The
# daemon accepts protocol-1 envelopes only; the five method names below map to
# handlers whose internal names predate the envelope method naming. All other
# methods (``loop_list``, ``job_create``, …) map to ``_handle_<method>``.
_METHOD_TO_HANDLER: dict[str, str] = {
    # notification methods
    "slash_command": "_handle_command",
    "disconnect": "_handle_detach",
    # subscribe methods
    "loop_events": "_handle_loop_subscribe",
    "autopilot_events": "_handle_autopilot_subscribe",
    # request methods
    "rpc_command": "_handle_command_request",
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
        ``model_params``, ``router_profile``, ``intent_hint`` (normalized to lowercase when set),
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
    raw_router_profile = msg.get("router_profile")
    router_profile = (
        raw_router_profile.strip()
        if isinstance(raw_router_profile, str) and raw_router_profile.strip()
        else None
    )
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
        "router_profile": router_profile,
        "intent_hint": intent_hint,
        "response_schema": response_schema,
        "response_schema_name": response_schema_name,
        "response_schema_strict": response_schema_strict,
        "clarification_mode": clarification_mode_norm,
        "clarification_answer": bool(msg.get("clarification_answer", False)),
        "clarification_answers": clarification_answers,
        "resume_interrupted": bool(msg.get("resume_interrupted", False)),
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

    # Maps message ``type`` → handler method name for the non-envelope control
    # types (connection_init, ping, pong). All RPC/notification/subscribe
    # methods are dispatched by envelope ``method`` via :data:`_METHOD_TO_HANDLER`
    # (for the five method-name overrides) or the ``_handle_<method>`` convention.
    HANDLER_REGISTRY: dict[str, str] = {
        "connection_init": "_handle_connection_init",
        "ping": "_handle_ping",
        "pong": "_handle_pong",
    }

    @classmethod
    def _resolve_handler(cls, flat_type: str) -> str | None:
        """Return the handler method name for a flattened envelope method.

        ``flat_type`` is the envelope ``method`` (or the unsubscribe-inferred
        key). The five method-name overrides in :data:`_METHOD_TO_HANDLER` map
        to their handlers; every other method maps to ``_handle_<method>``.

        Args:
            flat_type: Flattened method/handler key.

        Returns:
            Handler method name, or ``None`` if no handler exists.
        """
        if flat_type in _METHOD_TO_HANDLER:
            return _METHOD_TO_HANDLER[flat_type]
        handler = f"_handle_{flat_type}"
        return handler if hasattr(cls, handler) else None

    def __init__(self, daemon: Any) -> None:
        """Keep a reference to the daemon for config, runner, and session access."""
        self._daemon = daemon
        # Per-client handshake state (RFC-450 §8.2). Maps client_id →
        # (proto_version, capabilities).
        self._handshake_state: dict[Any, tuple[str, list[str]]] = {}

    async def _send_response(
        self,
        client_id: Any,
        request_id: str | None,
        result: dict[str, Any],
        *,
        proto: str = "1",
    ) -> None:
        """Send a protocol-1 response envelope to a client (RFC-450 §9.1).

        Wraps ``result`` in the standard ``{proto, type:'response', result, id}``
        envelope and dispatches via ``d._send_client_message``. When
        ``request_id`` is ``None`` the ``id`` field is omitted (notification-
        style responses, though this is unusual).

        Args:
            client_id: Client connection identifier.
            request_id: The originating request's correlation id, or ``None``.
            result: The result payload dict (method-specific return value).
            proto: Protocol version string (default ``"1"``).
        """
        d = self._daemon
        envelope: dict[str, Any] = {
            "proto": proto,
            "type": "response",
            "result": result,
        }
        if request_id is not None:
            envelope["id"] = request_id
        await d._send_client_message(client_id, envelope)

    async def _send_next(
        self,
        client_id: Any,
        subscription_id: str | None,
        payload: dict[str, Any],
        *,
        proto: str = "1",
    ) -> None:
        """Send a protocol-1 ``next`` event for an active subscription (RFC-450 §9.4).

        Streaming/subscription events use ``{proto, type:'next', payload, id}``
        where ``id`` matches the original subscription request's id. The stream
        terminates with a separate ``complete`` message (not sent here).

        Args:
            client_id: Client connection identifier.
            subscription_id: The subscription correlation id from the original
                ``subscribe`` request.
            payload: The event payload dict.
            proto: Protocol version string (default ``"1"``).
        """
        d = self._daemon
        envelope: dict[str, Any] = {
            "proto": proto,
            "type": "next",
            "payload": payload,
        }
        if subscription_id is not None:
            envelope["id"] = subscription_id
        await d._send_client_message(client_id, envelope)

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
        """Flatten a protocol-1 envelope into the handler-facing message dict.

        Handlers consume a flat dict with operation fields at the top level
        (e.g. ``{"type": "loop_list", "verbose": True, "request_id": "..."}``).
        The protocol-1 envelope wraps these as
        ``{"type": "request", "method": "loop_list", "params": {"verbose": True},
        "id": "..."}``. This internal adapter extracts ``method``/``params`` and
        builds that flat dict so handlers stay agnostic to the envelope shape.

        The flat ``type`` is the envelope ``method`` (the handler-name key in
        :data:`_METHOD_TO_HANDLER`). ``unsubscribe`` carries no ``method``;
        its target is inferred from ``params`` (``loop_id`` → loop detach,
        otherwise autopilot unsubscribe).

        The envelope ``id`` is carried as both ``request_id`` and ``id`` so
        handlers and error responses can correlate it. ``params is None`` is
        treated as ``{}`` because the SDK drops empty params dicts.

        Args:
            msg_type: The envelope ``type`` (request/notification/subscribe/
                unsubscribe).
            msg: The full envelope message dict.

        Returns:
            A flat message dict ready for handler dispatch, or ``None`` if the
            envelope is malformed (missing ``method`` on a non-unsubscribe
            envelope).
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
            # No method field: infer the handler key from params content.
            flat_type = "loop_detach" if "loop_id" in params else "autopilot_unsubscribe"
        else:
            flat_type = method

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

    async def _dispatch_batch(self, client_id: Any, batch: list[Any]) -> None:
        """Process a batch request array (RFC-450 §5.6).

        Each item is dispatched independently. Responses are collected for items
        with an ``id`` field (notifications produce no response). Empty or invalid
        arrays return a single ``-32600 INVALID_REQUEST`` error.

        Args:
            client_id: Client connection identifier.
            batch: JSON array of protocol-1 messages.
        """
        d = self._daemon

        # Empty array → single error response
        if not batch:
            err = build_error_response(
                ErrorCode.INVALID_REQUEST,
                "Batch array is empty",
            )
            await d._send_client_message(client_id, err)
            return

        # Check batch capability (RFC-450 §5.6)
        caps = self._get_negotiated_capabilities(client_id)
        if "batch" not in caps:
            err = build_error_response(
                ErrorCode.INVALID_REQUEST,
                "Batch requests require 'batch' capability in connection_init",
            )
            await d._send_client_message(client_id, err)
            return

        responses: list[dict[str, Any]] = []

        for item in batch:
            # Skip non-dict items
            if not isinstance(item, dict):
                err = build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "Batch item must be a valid message object",
                )
                responses.append(err)
                continue

            # Process item via single-message dispatch logic
            # (handshake check, envelope unwrap, registry dispatch)
            item_type = item.get("type", "")

            # Handshake enforcement
            if item_type not in _HANDSHAKE_EXEMPT_TYPES:
                if not self._is_handshake_complete(client_id):
                    err = build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        "Handshake must complete before sending messages",
                        request_id=item.get("id"),
                        data={"type": item_type},
                    )
                    responses.append(err)
                    continue

            # Validation (on the raw envelope, before unwrapping)
            errors = validate_message(item)
            if errors:
                err = build_error_response(
                    ErrorCode.INVALID_PARAMS,
                    "Invalid params",
                    request_id=item.get("id"),
                    data={"errors": errors},
                )
                responses.append(err)
                continue

            # Envelope unwrapping
            if item_type in _ENVELOPE_TYPES:
                unwrapped = self._unwrap_envelope(item_type, item)
                if unwrapped is None:
                    err = build_error_response(
                        ErrorCode.INVALID_REQUEST,
                        f"Invalid envelope: missing 'method' for type={item_type}",
                        request_id=item.get("id"),
                        data={"type": item_type},
                    )
                    responses.append(err)
                    continue
                item = unwrapped
                item_type = item.get("type", "")
                handler_name = self._resolve_handler(item_type)
            else:
                handler_name = self.HANDLER_REGISTRY.get(item_type)

            # Registry dispatch
            if handler_name is None:
                err = build_error_response(
                    ErrorCode.METHOD_NOT_FOUND,
                    f"Method not found: {item_type}",
                    request_id=item.get("request_id") or item.get("id"),
                    data={"method": item_type},
                )
                responses.append(err)
                continue

            # Invoke handler
            handler = getattr(self, handler_name)
            request_id = item.get("request_id") or item.get("id")
            try:
                await handler(client_id, item)
                # Handler sends its own response via _send_response
                # For batch, we don't collect responses here since handlers
                # send directly to client. The batch array return is for
                # synchronous batch semantics only (not currently used).
                # Notifications have no id and produce no response entry.
                if request_id is not None:
                    # Handler already sent response; nothing to collect
                    pass
            except RpcProtocolError as exc:
                err = build_error_response(
                    exc.code,
                    exc.message,
                    request_id=request_id,
                    data=exc.data if exc.data else None,
                )
                if request_id is not None:
                    responses.append(err)
                # Send error directly for items with id
                await d._send_client_message(client_id, err)

        # Batch response: only sent if there were items with id that produced
        # responses. Since handlers send responses directly, we don't send a
        # batch array here unless all items failed validation before dispatch.
        # Per RFC-450 §5.6, the caller may not expect a batch response if
        # handlers sent individual responses.
        if responses:
            # Items that failed validation before handler dispatch
            # These need to be sent as a batch since handler didn't send them
            await d._send_client_message(client_id, responses)

    async def dispatch(self, client_id: Any, msg: dict[str, Any] | list[Any]) -> None:
        """Handle a single client message or batch via the ``HANDLER_REGISTRY`` dispatch table.

        Performs a dict lookup by ``msg.get("type")`` instead of a linear
        if-chain.  Unknown types receive ``-32601 METHOD_NOT_FOUND``; param
        validation failures receive ``-32602 INVALID_PARAMS``; handler-raised
        ``RpcProtocolError`` exceptions are serialized to the standard error
        envelope.

        RFC-450 §5.6: Batch requests (JSON arrays) are processed by dispatching
        each item independently and collecting responses into an array.

        Args:
            client_id: Client connection identifier.
            msg: Decoded message dict or batch array.
        """
        # Set client_id in logging context for full ID in daemon.log
        if isinstance(client_id, str):
            set_client_id(client_id)
        d = self._daemon

        # -- Batch dispatch (RFC-450 §5.6) --------------------------------------
        # A batch is a JSON array of protocol-1 messages. Process each item
        # and collect responses for items with id. Empty/invalid arrays return
        # a single error.
        if isinstance(msg, list):
            await self._dispatch_batch(client_id, msg)
            return

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

        # -- Protocol-1 envelope dispatch (RFC-450 §5/§9) ---------------------
        # The daemon accepts protocol-1 envelopes (request/notification/
        # subscribe/unsubscribe) plus the three control types in
        # HANDLER_REGISTRY (connection_init/ping/pong). Flat-form messages
        # (e.g. ``{type:"loop_get", loop_id:...}``) are rejected with
        # METHOD_NOT_FOUND — clients MUST use the envelope form.
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
            handler_name = self._resolve_handler(msg_type)
        else:
            handler_name = self.HANDLER_REGISTRY.get(msg_type)

        # -- Registry dispatch -------------------------------------------------
        if handler_name is None:
            # Unknown message type / method → -32601 METHOD_NOT_FOUND.
            err = build_error_response(
                ErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {msg_type}",
                request_id=msg.get("request_id") or msg.get("id"),
                data={"method": msg_type},
            )
            await d._send_client_message(client_id, err)
            logger.debug("[MsgRouter] Unknown message type: %s", msg_type)
            return

        # -- Param validation (RFC-450 §6) -------------------------------------
        # Validate the envelope ``params`` against the (type, method) model.
        # ``msg`` here is the flattened envelope: operation fields live at the
        # top level (spread from params), so validate ``msg`` itself.
        params_model = PARAMS_REGISTRY.get(("request", msg_type))
        if params_model is None:
            params_model = PARAMS_REGISTRY.get(("notification", msg_type))
        if params_model is None:
            params_model = PARAMS_REGISTRY.get(("subscribe", msg_type))
        if params_model is not None:
            try:
                params_model.model_validate(msg)
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
        except RpcProtocolError as exc:
            err = build_error_response(
                exc.code,
                exc.message,
                request_id=msg.get("request_id") or msg.get("id"),
                data=exc.data if exc.data else None,
            )
            await d._send_client_message(client_id, err)
            logger.debug(
                "[MsgRouter] Handler %s raised RpcProtocolError: %s",
                handler_name,
                exc.message,
            )

    # -- Handshake & heartbeat handlers (RFC-450 §8) -------------------------

    @staticmethod
    def _handshake_key(client_id: Any) -> Any:
        """Return a hashable key for ``client_id``.

        Args:
            client_id: Client identifier (string or other hashable value).

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
        """Check whether the protocol-1 handshake has completed for this client."""
        return self._handshake_key(client_id) in self._handshake_state

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

    async def _handle_delivery_ack(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Record client delivery acknowledgment for stream drain gating (IG-556)."""
        params = msg.get("params")
        if not isinstance(params, dict):
            params = msg
        loop_id = str(params.get("loop_id") or "").strip()
        try:
            seq = int(params.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if not loop_id or seq <= 0:
            return
        d = self._daemon
        d._session_manager.record_delivery_ack(str(client_id), loop_id, seq)

    async def _handle_command(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``slash_command`` notifications.

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

    async def _handle_auth(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``auth`` WebSocket message (RFC-307 §WebSocket AKSK Flow).

        Args:
            client_id: Client identifier.
            msg: Message dict with ``access_key`` and ``secret_key``.
        """
        d = self._daemon
        from soothe_daemon.server.auth_handler import build_auth_response_error

        request_id = msg.get("request_id")

        auth_handler = getattr(d, "_auth_handler", None)
        if auth_handler is None:
            result = build_auth_response_error("identity_disabled")
            result.pop("type", None)
            await self._send_response(client_id, request_id, result)
            return

        access_key = msg.get("access_key", "")
        secret_key = msg.get("secret_key", "")

        if not access_key or not secret_key:
            result = build_auth_response_error("missing_credentials")
            result.pop("type", None)
            await self._send_response(client_id, request_id, result)
            return

        response = auth_handler.handle_auth(access_key, secret_key)
        result = dict(response)
        result.pop("type", None)
        await self._send_response(client_id, request_id, result)

    async def _handle_auth_refresh(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle ``auth_refresh`` WebSocket message (RFC-307 §Token Refresh Flow).

        Args:
            client_id: Client identifier.
            msg: Message dict with ``refresh_token``.
        """
        d = self._daemon
        from soothe_daemon.server.auth_handler import build_refresh_response_error

        request_id = msg.get("request_id")

        auth_handler = getattr(d, "_auth_handler", None)
        if auth_handler is None:
            result = build_refresh_response_error("identity_disabled")
            result.pop("type", None)
            await self._send_response(client_id, request_id, result)
            return

        refresh_token = msg.get("refresh_token", "")
        if not refresh_token:
            result = build_refresh_response_error("missing_refresh_token")
            result.pop("type", None)
            await self._send_response(client_id, request_id, result)
            return

        response = auth_handler.handle_refresh(refresh_token)
        result = dict(response)
        result.pop("type", None)
        await self._send_response(client_id, request_id, result)

    async def _handle_skills_list(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return wire-safe skill metadata for the daemon's agent config."""
        import asyncio

        d = self._daemon
        from soothe_nano.skills.catalog import wire_entries_for_agent_config

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

        # Run filesystem I/O in a thread to avoid blocking the event loop
        skills = await asyncio.to_thread(
            wire_entries_for_agent_config,
            d._config,
            workspace,
            skill_index=d._skill_index,
        )
        await self._send_response(
            client_id,
            msg.get("request_id"),
            {"skills": skills},
        )

    async def _handle_models_list(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return model rows from the daemon host ``SootheConfig`` (for TUI ``/model``)."""
        d = self._daemon
        from soothe.config.models_catalog import build_models_list_payload

        payload = build_models_list_payload(d._config)
        await self._send_response(
            client_id,
            msg.get("request_id"),
            {
                "models": payload["models"],
                "default_model": payload.get("default_model"),
                "router_profiles": payload.get("router_profiles") or [],
                "active_router_profile": payload.get("active_router_profile"),
            },
        )

    async def _handle_mcp_status(self, client_id: str, msg: dict[str, Any]) -> None:
        """Return MCP server status for the TUI MCP viewer."""
        d = self._daemon
        registry = d._mcp_registry
        if registry is None:
            await self._send_response(
                client_id,
                msg.get("request_id"),
                {"servers": []},
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

        await self._send_response(
            client_id,
            msg.get("request_id"),
            {"servers": servers},
        )

    async def _handle_invoke_skill(self, client_id: str, msg: dict[str, Any]) -> None:
        """Resolve a skill on the daemon host, ack the client, then queue the composed turn."""
        d = self._daemon
        from soothe_nano.skills.catalog import (
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

        await self._send_response(
            client_id,
            msg.get("request_id"),
            {"echo": echo},
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

        await self._send_response(
            client_id,
            request_id,
            {
                "running": running,
                "port_live": port_live,
                "active_threads": active_threads,
                "daemon_pid": os.getpid() if running else None,
                "started_at": d._started_at,
                "readiness_state": d._readiness_state,
                "readiness_message": d._readiness_message,
                "daemon_version": daemon_version,
                "core_version": core_version,
            },
        )

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
        await self._send_response(
            client_id,
            request_id,
            {"status": "acknowledged"},
        )

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

        result: dict[str, Any] = {section: section_data}
        await self._send_response(client_id, request_id, result)

    async def _handle_config_reload(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle config_reload RPC request.

        Triggers immediate reload of watched config files.

        Args:
            client_id: Client connection identifier.
            msg: Request message with optional request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")

        # Check if config reload is enabled
        if not getattr(d, "_config_reload_enabled", False):
            await self._send_response(
                client_id,
                request_id,
                {
                    "success": False,
                    "error": "config_reload_not_enabled",
                    "message": "Config hot-reload is not enabled on this daemon",
                },
            )
            return

        # Trigger reload
        try:
            d.reload_config_now()
            await self._send_response(
                client_id,
                request_id,
                {"success": True, "message": "Config reload triggered"},
            )
        except Exception as e:
            logger.error("Config reload failed: %s", e)
            await self._send_response(
                client_id,
                request_id,
                {"success": False, "error": str(e)},
            )

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
            latest_ai_response = _peek_latest_assistant_response(loop_id)
            if latest_ai_response:
                entry["latest_ai_response"] = latest_ai_response
            entry["topic"] = _resolve_loop_topic(
                prompt=prompt,
                resume_topic=row.get("resume_topic"),
            )
            loops.append(entry)

        await self._send_response(
            client_id,
            request_id,
            {"loops": loops, "total": len(loops)},
        )

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

        await self._send_response(
            client_id,
            request_id,
            {"loop": loop_data},
        )

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

        await self._send_response(
            client_id,
            request_id,
            {"tree": tree_data},
        )

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

        await self._send_response(
            client_id,
            request_id,
            {"pruned": pruned, "remaining": remaining, "dry_run": dry_run},
        )

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
            await self._send_response(
                client_id,
                request_id,
                {
                    "success": True,
                    "message": f"Loop {loop_id} not found (already deleted)",
                },
            )
            return

        try:
            await purge_loop_fully(d, loop_id, metadata)
            await self._send_response(
                client_id,
                request_id,
                {
                    "success": True,
                    "message": f"Loop {loop_id} deleted successfully",
                },
            )
        except Exception as e:
            logger.error("Failed to delete loop %s: %s", loop_id, str(e))
            await self._send_response(
                client_id,
                request_id,
                {
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

        # Acknowledge the request before streaming the replay. Per RFC-450
        # §5.2 a ``request`` with an ``id`` MUST receive a ``response``; the
        # replay itself is streamed as soothe.card.replay.* / history frames, not as
        # the response payload.
        await self._send_response(
            client_id,
            request_id,
            {"loop_id": loop_id, "success": True},
        )
        # Execute reattachment handler (schedules the background replay task)
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

        from soothe_daemon.runtime import DEPRECATED_LOOP_AUTOPILOT_MODE

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
            subscription_id=request_id,  # correlate protocol-1 ``next`` envelopes
        )

        # Per RFC-450 §9.4, subscription confirmation is a ``next`` event
        # carrying the subscription id (the request's correlation id).
        await self._send_next(
            client_id,
            request_id,
            {
                "loop_id": loop_id,
                "event": "subscribed",
                "success": True,
                "autopilot_mode": DEPRECATED_LOOP_AUTOPILOT_MODE,
                "client_id": client_id,
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
        await self._send_response(
            client_id,
            request_id,
            {"loop_id": loop_id, "success": True},
        )

    async def _handle_loop_new(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle loop_new RPC request (RFC-503).

        Create fresh loop with new loop_id for new query/conversation. If the client
        provides a ``workspace`` field (e.g., user's CWD), validate it and record it
        as the loop's filesystem workspace. If client provides ``user`` field, store
        for workspace isolation (per-user workspace under ``$SOOTHE_HOME/data/workspaces/``).

        Args:
            client_id: Client connection identifier.
            msg: Request message; may contain optional ``workspace`` and ``user`` fields.
        """
        from soothe.workspace import resolve_loop_workspace, validate_client_workspace
        from uuid_utils import uuid7

        d = self._daemon
        request_id = msg.get("request_id")
        is_ephemeral = bool(msg.get("is_ephemeral", False))

        from soothe.workspace import translate_client_path_to_container

        mount = d._config.workspace_mount
        host_root = mount.host_root if mount and mount.is_configured else None
        container_root = mount.container_root if mount and mount.is_configured else None

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
                if resolved.exists():
                    client_workspace = str(resolved)
                    logger.info(
                        "[loop_new] Loop %s using client workspace: %s",
                        loop_id,
                        client_workspace,
                    )
                elif host_root is not None:
                    # RFC-621: host paths are not present literally in the container;
                    # accept when mappable under workspace_mount.host_root.
                    try:
                        translate_client_path_to_container(
                            resolved,
                            host_root=host_root,
                            container_root=container_root,
                        )
                    except ValueError as e:
                        logger.info(
                            "[loop_new] Loop %s ignoring client workspace (not under host_root): %s",
                            loop_id,
                            e,
                        )
                    else:
                        client_workspace = str(resolved)
                        logger.info(
                            "[loop_new] Loop %s using mapped client workspace: %s",
                            loop_id,
                            client_workspace,
                        )
                else:
                    logger.info(
                        "[loop_new] Loop %s ignoring client workspace (not on daemon host): %s",
                        loop_id,
                        resolved,
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

        workspace_mapping: dict[str, str] | None = None
        if host_root is not None and container_root is not None:
            workspace_mapping = {
                "host_root": host_root,
                "container_root": container_root,
            }

        try:
            if client_workspace is not None and host_root is not None:
                effective_workspace = translate_client_path_to_container(
                    client_workspace,
                    host_root=host_root,
                    container_root=container_root,
                )
            else:
                effective_workspace = resolve_loop_workspace(
                    loop_id=loop_id,
                    client_workspace=client_workspace,
                    user_id=user,
                    client_workspace_id=client_workspace_id,
                    workspace_mapping=workspace_mapping,
                )
        except ValueError as e:
            if client_workspace is not None and host_root is not None:
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
            logger.warning(
                "[loop_new] Loop %s workspace resolution failed (%s); using daemon workspace",
                loop_id,
                e,
            )
            from soothe.workspace import resolve_daemon_workspace

            effective_workspace = resolve_daemon_workspace()

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

        from soothe_daemon.runtime import DEPRECATED_LOOP_AUTOPILOT_MODE

        logger.info(
            "Created new loop %s (ephemeral=%s workspace=%s)",
            loop_id,
            is_ephemeral,
            effective_workspace,
        )

        # Send response
        result: dict[str, Any] = {
            "loop_id": loop_id,
            "success": True,
            "is_ephemeral": is_ephemeral,
            "autopilot_mode": DEPRECATED_LOOP_AUTOPILOT_MODE,
        }
        if host_root is not None:
            result["workspace_mapping"] = {
                "host_root": host_root,
                "container_root": container_root,
                "client_workspace": client_workspace,
                "container_workspace": str(effective_workspace),
            }
        await self._send_response(client_id, request_id, result)

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

        has_response_schema = bool(q_opts.get("response_schema"))
        normalized_hint, hint_error = validate_and_normalize_intent_hint(
            intent_hint_preview,
            prompt_text=prompt_text,
            has_attachments=bool(attachments_for_queue),
            has_response_schema=has_response_schema,
        )
        if hint_error is not None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    hint_error,
                    request_id=request_id,
                ),
            )
            return
        if normalized_hint is not None:
            q_opts["intent_hint"] = normalized_hint

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

        response_schema = q_opts.get("response_schema")
        if response_schema is not None:
            try:
                from soothe_nano.utils.llm.schema_wire import validate_response_schema

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

        await self._send_response(
            client_id,
            request_id,
            {"loop_id": loop_id, "success": True},
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

        await self._send_response(
            client_id,
            request_id,
            {"messages": serialized},
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

        await self._send_response(
            client_id,
            request_id,
            {"values": _serialize_for_json(values)},
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

        await self._send_response(
            client_id,
            request_id,
            {"success": True},
        )

    async def _handle_loop_history_fetch(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Return goal display snapshots plus live card tail (RFC-631)."""
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

        try:
            loop_id_str = str(loop_id)
            loop_meta = await d._persistence_manager.get_loop_metadata(loop_id_str)
            loop_status = str((loop_meta or {}).get("status") or "")
            payload = await card_manager.fetch_loop_history(
                loop_id_str,
                loop_status=loop_status,
            )
            context_tokens = await self._read_loop_token_total(loop_id_str)
            payload["context_tokens"] = context_tokens
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

        await self._send_response(client_id, request_id, payload)

    async def _read_loop_token_total(self, loop_id: str) -> int:
        """Best-effort loop token total for TUI resume.

        Reads the authoritative ``total_tokens_used`` persisted by StrangeLoop
        into loop metadata during checkpoint saves.
        """
        d = self._daemon
        try:
            metadata = await d._persistence_manager.get_loop_metadata(loop_id)
            if isinstance(metadata, dict):
                raw_meta = metadata.get("total_tokens_used")
                if isinstance(raw_meta, int) and raw_meta >= 0:
                    return raw_meta
        except Exception:
            logger.debug(
                "Failed to read loop metadata tokens for loop %s",
                loop_id,
                exc_info=True,
            )
        return 0

    async def _handle_loop_execution_state_fetch(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Return focused execution-progress snapshot: plan, step_index, iteration, status.

        Lighter than ``loop_state_get`` (which returns the full channel-value
        dict). This RPC extracts the four fields a client needs to render a
        progress indicator from two sources:

        * ``iteration`` / ``status`` — from the loop metadata
          ``execution_checkpoint`` blob (the authoritative persisted values).
        * ``plan`` / ``step_index`` — best-effort from the bound checkpoint
          thread's graph channel values (``current_decision`` /
          ``previous_plan`` / ``completed_step_ids``).
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

        loop_id_str = str(loop_id)

        # --- iteration + status: from execution_checkpoint metadata blob ----
        iteration: int = 0
        loop_status: str = "idle"
        try:
            metadata = await d._persistence_manager.get_loop_metadata(loop_id_str)
        except Exception as exc:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.LOOP_EXECUTION_STATE_ERROR,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        if isinstance(metadata, dict):
            # iteration comes from the execution_checkpoint blob; status from
            # the loop metadata row (authoritative, same field loop_get surfaces).
            exec_cp = metadata.get("execution_checkpoint")
            if isinstance(exec_cp, dict):
                raw_iter = exec_cp.get("iteration")
                if isinstance(raw_iter, (int, float)) and raw_iter >= 0:
                    iteration = int(raw_iter)
                # Fall back to execution_checkpoint status only when the
                # metadata-level status is absent (e.g. legacy/pre-5.0 row).
                raw_exec_status = exec_cp.get("status")
                if isinstance(raw_exec_status, str) and raw_exec_status.strip():
                    loop_status = raw_exec_status.strip()
            meta_status = metadata.get("status")
            if isinstance(meta_status, str) and meta_status.strip():
                loop_status = meta_status.strip()

        # --- plan + step_index: best-effort from graph channel values --------
        plan: Any = None
        step_index: int = 0
        runner = d._runner
        if runner is not None:
            try:
                from soothe_daemon.runtime.loop_dispatcher import (
                    bind_execution_thread_for_loop,
                )

                checkpoint_thread_id = await bind_execution_thread_for_loop(d, loop_id_str)
                values = await runner.get_thread_state_values(checkpoint_thread_id)
            except Exception:
                logger.debug(
                    "execution_state_fetch: thread values read failed for %s",
                    loop_id_str,
                    exc_info=True,
                )
                values = {}

            # Prefer the in-flight decision; fall back to previous_plan.
            decision = values.get("current_decision")
            if decision is not None:
                plan = _serialize_for_json(decision)
            else:
                prev_plan = values.get("previous_plan")
                if prev_plan is not None:
                    plan = _serialize_for_json(prev_plan)

            # step_index = number of completed steps within the current plan.
            completed = values.get("completed_step_ids")
            if isinstance(completed, (list, tuple, set)):
                step_index = len(completed)

        payload = _serialize_for_json(
            {
                "loop_id": loop_id_str,
                "plan": plan,
                "step_index": step_index,
                "iteration": iteration,
                "status": loop_status,
            }
        )
        await self._send_response(client_id, request_id, payload)

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
        # TODO: verification_rules to be passed to ContextEngine when supported
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
                from soothe.workspace import validate_client_workspace

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

        await self._send_response(
            client_id,
            request_id,
            {"job_id": goal.id, "status": goal.status},
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

        await self._send_response(
            client_id,
            request_id,
            {
                "job_id": job_id,
                "status": root_goal.status,
                "active_goals": active_count,
                "completed_goals": completed_count,
                "failed_goals": failed_count,
                "cancelled_goals": cancelled_count,
                "total_goals": total_count,
                "workers": workers,
                "last_error": last_error,
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

        context_engine = service._ce

        # Check goal exists and is not already suspended
        goal = await context_engine.get_goal(job_id)
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
            await context_engine.suspend_goal(job_id, reason="user_pause")
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

        await self._send_response(
            client_id,
            request_id,
            {"job_id": job_id, "status": "suspended"},
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

        context_engine = service._ce

        # Check goal exists and is suspended
        goal = await context_engine.get_goal(job_id)
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
            await context_engine.reactivate_goal(job_id)
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

        await self._send_response(
            client_id,
            request_id,
            {"job_id": job_id, "status": "pending"},
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

        await self._send_response(
            client_id,
            request_id,
            {"job_id": job_id, "status": cancelled.status},
        )
        logger.info("[JobCancel] Cancelled job %s", job_id)

    async def _handle_job_dag(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_dag RPC request (RFC-228).

        Get ContextEngine DAG snapshot for visualization.

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

        await self._send_response(
            client_id,
            request_id,
            {"job_id": job_id, "dag": dag},
        )

    async def _handle_job_guidance(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle job_guidance RPC request (RFC-228).

        Send user guidance to ContextEngine for absorption.

        Args:
            client_id: Client connection identifier.
            msg: Request with job_id, goal_id (optional), content, request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        job_id = msg.get("job_id")
        goal_id = msg.get("goal_id")  # Optional - specific goal or root
        content = msg.get("content")

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

        if not isinstance(content, str) or not content.strip():
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    "content (non-empty string) is required",
                    request_id=request_id,
                ),
            )
            return

        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        context_engine = service._ce

        # Determine target goal
        target_id = goal_id if goal_id else job_id
        target_goal = await context_engine.get_goal(target_id)
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

        # Absorb guidance via ContextEngine (RFC-228)
        scope = "goal" if goal_id else "job"
        absorbed = await context_engine.absorb_guidance(target_id, content.strip(), scope=scope)

        logger.info(
            "[JobGuidance] Guidance for job=%s goal=%s absorbed=%s: %s",
            job_id,
            target_id,
            absorbed,
            content[:50],
        )

        await self._send_response(
            client_id,
            request_id,
            {
                "job_id": job_id,
                "goal_id": target_id,
                "absorbed": absorbed,
            },
        )

    async def _require_autopilot_service(
        self, client_id: Any, request_id: str | None
    ) -> Any | None:
        """Return the autopilot service or send a not-ready error and None."""
        d = self._daemon
        service = getattr(d, "_autopilot_service", None)
        if service is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.AUTOPILOT_NOT_READY,
                    "Autopilot service unavailable",
                    request_id=request_id,
                ),
            )
            return None
        return service

    async def _dispatch_autopilot_rpc(
        self,
        client_id: Any,
        msg: dict[str, Any],
        action: str,
    ) -> None:
        """Shared protocol-1 response path for ``autopilot_*`` request methods."""
        from soothe_daemon.protocol.autopilot_commands import run_autopilot_action

        d = self._daemon
        request_id = msg.get("request_id")
        service = await self._require_autopilot_service(client_id, request_id)
        if service is None:
            return

        payload = {
            key: value
            for key, value in msg.items()
            if key not in {"type", "proto", "method", "params", "id", "request_id"}
        }
        try:
            result = await run_autopilot_action(service, action, payload)
        except RuntimeError as exc:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INVALID_REQUEST,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return
        except Exception as exc:
            logger.error("[AutopilotRPC] %s failed: %s", action, exc, exc_info=True)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INTERNAL_ERROR,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        await self._send_response(client_id, request_id, result)

    async def _handle_autopilot_status(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_status request (CLI / AsyncCommandClient)."""
        await self._dispatch_autopilot_rpc(client_id, msg, "status")

    async def _handle_autopilot_submit(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_submit request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "submit")

    async def _handle_autopilot_list_goals(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_list_goals request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "list_goals")

    async def _handle_autopilot_get_goal(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_get_goal request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "get_goal")

    async def _handle_autopilot_cancel_goal(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_cancel_goal request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "cancel_goal")

    async def _handle_autopilot_cancel_all(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_cancel_all request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "cancel_all")

    async def _handle_autopilot_wake(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_wake request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "wake")

    async def _handle_autopilot_dream(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_dream request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "dream")

    async def _handle_autopilot_resume(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_resume request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "resume")

    async def _handle_autopilot_list_jobs(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_list_jobs request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "list_jobs")

    async def _handle_autopilot_get_job(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle autopilot_get_job request."""
        await self._dispatch_autopilot_rpc(client_id, msg, "get_job")

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

        # Per RFC-450 §9.4, subscription confirmation is a ``next`` event
        # carrying the subscription id (the request's correlation id).
        await self._send_next(
            client_id,
            request_id,
            {"client_id": client_id, "event": "subscribed", "subscribed": True},
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

        await self._send_response(
            client_id,
            request_id,
            {"client_id": client_id, "subscribed": False},
        )
        logger.info(
            "[AutopilotUnsubscribe] Client %s unsubscribed from autopilot events", client_id
        )

    # -- Cron RPC handlers (RFC-229) ---------------------------------------------

    async def _require_cron_service(self, client_id: Any, request_id: str | None) -> Any | None:
        """Return CronService if available, else send error response and return None.

        Args:
            client_id: Client connection identifier.
            request_id: Request correlation id.

        Returns:
            CronService instance or None if unavailable.
        """
        d = self._daemon
        service = getattr(d, "_cron_service", None)
        if service is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.AUTOPILOT_NOT_READY,
                    "Cron service not initialized",
                    request_id=request_id,
                ),
            )
            return None
        return service

    async def _handle_cron_add(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle cron_add RPC request (RFC-229).

        Create a scheduled job from natural language input.

        Args:
            client_id: Client connection identifier.
            msg: Request with text (required), priority (optional), request_id.
        """
        d = self._daemon
        request_id = msg.get("request_id")
        text = msg.get("text")
        priority = msg.get("priority")

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

        service = await self._require_cron_service(client_id, request_id)
        if service is None:
            return

        # Default user for daemon (single-user mode)
        from soothe.cron.extraction import AutopilotDisabledError
        from soothe.cron.models import DEFAULT_CRON_USER_ID, DuplicateCronJobError

        user_id = DEFAULT_CRON_USER_ID

        # Create job via CronService
        try:
            job = await service.add_job(text.strip(), user_id, priority=priority)
        except AutopilotDisabledError as exc:
            logger.warning("[CronAdd] Rejected: %s", exc.message)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.AUTOPILOT_NOT_READY,
                    exc.message,
                    request_id=request_id,
                ),
            )
            return
        except DuplicateCronJobError as exc:
            job = exc.existing_job
            logger.info("[CronAdd] Duplicate rejected, returning existing job %s", job.id)
            await self._send_response(
                client_id,
                request_id,
                {
                    "job_id": job.id,
                    "description": job.description,
                    "schedule_kind": job.schedule_kind.value,
                    "schedule_value": job.schedule_value,
                    "next_run": job.next_run.isoformat() if job.next_run else None,
                    "status": job.status.value,
                    "priority": job.priority,
                    "duplicate": True,
                },
            )
            return
        except Exception as exc:
            logger.error("[CronAdd] Failed to create job: %s", exc, exc_info=True)
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.INTERNAL_ERROR,
                    str(exc),
                    request_id=request_id,
                ),
            )
            return

        await self._send_response(
            client_id,
            request_id,
            {
                "job_id": job.id,
                "description": job.description,
                "schedule_kind": job.schedule_kind.value,
                "schedule_value": job.schedule_value,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "status": job.status.value,
                "priority": job.priority,
            },
        )
        logger.info("[CronAdd] Created cron job %s: %s", job.id, job.description[:50])

    async def _handle_cron_list(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle cron_list RPC request (RFC-229).

        List scheduled jobs for the user.

        Args:
            client_id: Client connection identifier.
            msg: Request with status (optional filter), request_id.
        """
        request_id = msg.get("request_id")
        status_filter = msg.get("status")

        service = await self._require_cron_service(client_id, request_id)
        if service is None:
            return

        from soothe.cron.models import DEFAULT_CRON_USER_ID

        user_id = DEFAULT_CRON_USER_ID

        # List jobs via CronService
        jobs = await service.list_jobs(user_id, status=status_filter)

        jobs_data = [
            {
                "id": job.id,
                "description": job.description,
                "schedule_kind": job.schedule_kind.value,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "status": job.status.value,
                "priority": job.priority,
            }
            for job in jobs
        ]

        await self._send_response(client_id, request_id, {"jobs": jobs_data})

    async def _handle_cron_show(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle cron_show RPC request (RFC-229).

        Get details for a specific scheduled job.

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

        service = await self._require_cron_service(client_id, request_id)
        if service is None:
            return

        from soothe.cron.models import DEFAULT_CRON_USER_ID

        user_id = DEFAULT_CRON_USER_ID

        # Get job via CronService
        job = await service.show_job(job_id.strip(), user_id)
        if job is None:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Cron job {job_id} not found",
                    request_id=request_id,
                ),
            )
            return

        await self._send_response(
            client_id,
            request_id,
            {
                "job_id": job.id,
                "description": job.description,
                "schedule_kind": job.schedule_kind.value,
                "schedule_value": job.schedule_value,
                "end_condition": job.end_condition,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "status": job.status.value,
                "priority": job.priority,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            },
        )

    async def _handle_cron_cancel(self, client_id: Any, msg: dict[str, Any]) -> None:
        """Handle cron_cancel RPC request (RFC-229).

        Cancel a scheduled job.

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

        service = await self._require_cron_service(client_id, request_id)
        if service is None:
            return

        from soothe.cron.models import DEFAULT_CRON_USER_ID

        user_id = DEFAULT_CRON_USER_ID

        # Cancel job via CronService
        cancelled = await service.cancel_job(job_id.strip(), user_id)
        if not cancelled:
            await d._send_client_message(
                client_id,
                build_error_response(
                    ErrorCode.JOB_NOT_FOUND,
                    f"Cron job {job_id} not found or cannot be cancelled",
                    request_id=request_id,
                ),
            )
            return

        await self._send_response(
            client_id,
            request_id,
            {"job_id": job_id.strip(), "cancelled": True},
        )
        logger.info("[CronCancel] Cancelled cron job %s", job_id)

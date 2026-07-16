"""Client connection handling for the daemon (IG-110).

Heavy logic lives in ``message_router`` and ``query_engine``; this mixin wires
transport entrypoints and the input queue loop.
"""

from __future__ import annotations

import logging
from typing import Any

import websockets.exceptions
from soothe.foundation.events import ERROR

from soothe_daemon.bootstrap.logging import set_client_id, set_loop_id
from soothe_daemon.protocol import ErrorCode, build_error_response, validate_message
from soothe_daemon.protocol.router import (
    _coerce_loop_input_text,
    _queue_options_from_daemon_message,
)

# Import RPC command handlers (RFC-454)
from soothe_daemon.server.commands import (
    _cmd_autopilot_dashboard,
    _cmd_cancel,
    _cmd_clear,
    _cmd_config,
    _cmd_cron_add,
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

    # Attach RPC handlers to mixin (RFC-454)
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
    _cmd_cron_add = _cmd_cron_add

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
                await self._session_manager.send_to_client(session, msg)
        except websockets.exceptions.ConnectionClosedOK:
            # Normal disconnect (code 1000) - expected, no error logging
            logger.debug("Client %r disconnected normally", client_id)
        except (websockets.exceptions.ConnectionClosedError, ConnectionError):
            # Abnormal disconnect - log as warning without full traceback
            logger.debug("Client %r disconnected unexpectedly", client_id)
        except Exception:
            # Unexpected error - log with full traceback
            logger.debug("Failed to send direct response to client %r", client_id, exc_info=True)

    async def _handle_client_message(self, client_id: str, msg: dict[str, Any]) -> None:
        """Handle a message from a client (WebSocket transport).

        Validates the message at the transport boundary (RFC-450 §6.4) before
        dispatching to the router.
        """
        errors = validate_message(msg)
        if errors:
            error_msg = build_error_response(
                ErrorCode.INVALID_PARAMS,
                "Invalid params",
                request_id=msg.get("request_id") or msg.get("id"),
                data={"errors": errors},
            )
            await self._send_client_message(client_id, error_msg)
            return
        await self._message_router.dispatch(client_id, msg)

    async def _process_loop_input_message(self, loop_id: str, msg: dict[str, Any]) -> None:
        """Process one loop-scoped message from ``LoopInputDispatcher`` (IG-408).

        Supported ``msg["type"]`` values for user turns: ``input`` (normalized queue
        payload from ``loop_input`` RPC) or ``loop_input`` (wire-shaped dict with
        ``content``). Other types are ignored with a warning except ``command`` and
        ``command_request``, which are handled above.
        """
        from soothe_daemon.runtime.loop_dispatcher import bind_execution_thread_for_loop

        # Set logging context for full loop_id and client_id in daemon.log
        set_loop_id(loop_id)
        client_id = msg.get("client_id")
        if client_id:
            set_client_id(str(client_id))

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

        # Emit running status early so client doesn't timeout waiting for query start.
        # Omit turn_id here: admit has not reserved the next generation yet, so
        # stamping the prior generation would poison the client's expected_turn_id.
        # run_query emits the authoritative running frame after admit.
        if self._query_engine is not None:
            self._query_engine.mark_loop_turn_starting(loop_id)
            await self._broadcast(
                self._query_engine._loop_scoped_client_message(
                    loop_id,
                    {"type": "status", "state": "running"},
                    turn_generation=0,
                )
            )
        else:
            await self._broadcast({"type": "status", "state": "running", "loop_id": loop_id})

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
                    loop_id if loop_id else "?",
                )
                return

            if msg_type == "loop_input":
                prompt_text = _coerce_loop_input_text(msg.get("content"))
                if prompt_text is None:
                    logger.warning(
                        "Loop worker loop_input missing usable content loop_id=%s",
                        loop_id if loop_id else "?",
                    )
                    return
            else:
                raw_text = msg.get("text")
                if not isinstance(raw_text, str):
                    logger.warning(
                        "Loop worker input missing str text loop_id=%s",
                        loop_id if loop_id else "?",
                    )
                    return
                prompt_text = raw_text

            card_manager = getattr(self, "_card_manager", None)
            if card_manager is not None:
                try:
                    await card_manager.record_user_prompt(loop_id, prompt_text)
                except Exception:
                    logger.debug("Failed to record user prompt card for %s", loop_id, exc_info=True)

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
                    model=model_kw,
                    model_params=model_params,
                    router_profile=qo.get("router_profile"),
                    attachments=attachments,
                    checkpoint_thread_id=checkpoint_thread_id,
                    intent_hint=intent_hint,
                    response_schema=qo.get("response_schema"),
                    response_schema_name=qo.get("response_schema_name"),
                    response_schema_strict=qo.get("response_schema_strict"),
                    clarification_mode=qo.get("clarification_mode"),
                    clarification_answer=bool(qo.get("clarification_answer", False)),
                    clarification_answers=qo.get("clarification_answers"),
                )
        except Exception:
            logger.exception("Daemon loop input handler error")
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

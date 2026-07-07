"""Daemon-backed session helpers for the Textual TUI."""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from soothe_sdk.client import (
    WebSocketClient,
    bootstrap_loop_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)
from soothe_sdk.client.protocol import _serialize_for_json

from soothe_cli.runtime.state.session_stats import TurnEventStats
from soothe_cli.runtime.wire.chunk_filter import should_drop_stream_chunk_early

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Match headless daemon client: brief read window after ``idle`` so stream events
# that arrive slightly after status are not dropped (``cli/execution/daemon.py``).
_POST_IDLE_DRAIN_DEADLINE_S = 0.5

# Align with ``bootstrap_loop_session`` daemon-ready wait (RFC-450 §8.2).
_RPC_HANDSHAKE_TIMEOUT_S = 20.0

# Brief close handshake on TUI exit — the daemon cleans up on disconnect anyway.
TUI_EXIT_HANDSHAKE_TIMEOUT_S = 0.3


def _unwrap_next(event: dict[str, Any] | None) -> dict[str, Any] | None:
    """Unwrap a protocol-1 ``next`` envelope to its inner streaming frame.

    Under protocol-1 (RFC-450 §9.3) the daemon wraps free-form streaming
    frames (``event``/``command_response``/card replay) in a
    ``{proto, type:"next", payload:{namespace, mode, data}}`` envelope. This
    helper returns the inner ``data`` dict (the legacy frame carrying
    ``type``/``mode``/``namespace``/``data``/``loop_id``) so the turn loop can
    branch on the same fields it consumed before the migration. ``status``
    frames and other protocol-1 messages (``response``/``error``/``complete``)
    are sent raw and pass through unchanged.

    Args:
        event: A raw wire frame as returned by ``client.read_event()``.

    Returns:
        The inner ``payload.data`` dict for ``next`` envelopes, the original
        frame otherwise, or ``None`` if ``event`` is ``None``.
    """
    if not isinstance(event, dict):
        return event
    if event.get("type") != "next":
        return event
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return event
    data = payload.get("data")
    return data if isinstance(data, dict) else event


class TuiDaemonSession:
    """Own the daemon websocket session used by the TUI."""

    def __init__(
        self,
        cfg: Any,
        *,
        workspace: str | None = None,
        post_idle_drain_deadline: float = _POST_IDLE_DRAIN_DEADLINE_S,
    ) -> None:
        self._cfg = cfg
        self._workspace = workspace
        ws_url = websocket_url_from_config(cfg)
        self._client = WebSocketClient(url=ws_url)
        self._rpc_client = WebSocketClient(url=ws_url)
        self._loop_id: str | None = None
        self._read_lock = asyncio.Lock()
        self._rpc_lock = asyncio.Lock()
        self._rpc_connected = False
        self._streaming = False
        self._post_idle_drain_deadline = post_idle_drain_deadline
        self._closed = False
        self.turn_event_stats = TurnEventStats()
        self.last_turn_end_state: str | None = None
        self.last_turn_cancellation_seen: bool = False
        self.last_turn_error_message: str | None = None

    @property
    def loop_id(self) -> str | None:
        """Active StrangeLoop id for this WebSocket session."""
        return self._loop_id

    async def connect(self, *, resume_loop_id: str | None = None) -> dict[str, Any]:
        """Connect and bootstrap a daemon loop session."""
        await connect_websocket_with_retries(self._client)
        status_event = await self._bootstrap_loop(resume_loop_id=resume_loop_id)
        return status_event

    async def _bootstrap_loop(self, *, resume_loop_id: str | None = None) -> dict[str, Any]:
        """Create or attach to a loop on an already-connected websocket."""
        # Determine stream_delivery mode from config (RFC-614)
        stream_delivery = self._resolve_stream_delivery_mode()

        status_event = await bootstrap_loop_session(
            self._client,
            resume_loop_id=resume_loop_id,
            stream_delivery=stream_delivery,
            workspace=self._workspace,
        )
        if status_event.get("type") == "error":
            raise RuntimeError(str(status_event.get("message", "daemon bootstrap failed")))
        self._loop_id = status_event.get("loop_id")
        return status_event

    def _resolve_stream_delivery_mode(self) -> str:
        """Determine stream delivery mode from config (RFC-614, IG-441).

        Returns one of ``batch`` | ``adaptive`` | ``streaming``. CLI override
        wins, then config; defaults to ``adaptive`` (smooth UX for long
        synthesis, see IG-441).
        """
        if (
            self._cfg
            and hasattr(self._cfg, "output_streaming_mode")
            and self._cfg.output_streaming_mode
        ):
            return str(self._cfg.output_streaming_mode)

        if self._cfg and hasattr(self._cfg, "agent"):
            streaming_cfg = self._cfg.agent.loop.output_streaming
            return str(streaming_cfg.mode)

        return "adaptive"

    async def new_loop(self) -> dict[str, Any]:
        """Start a new StrangeLoop conversation."""
        return await self._bootstrap_loop(resume_loop_id=None)

    async def switch_loop(self, loop_id: str) -> dict[str, Any]:
        """Subscribe to an existing loop (re-bootstrap on the same connection)."""
        return await self._bootstrap_loop(resume_loop_id=loop_id)

    async def ensure_connected(self) -> None:
        """Reconnect and re-subscribe to the active loop when the WebSocket died.

        No-op when the main client socket is still open. Used after daemon restart so
        the TUI can resume the current loop without exiting.

        Raises:
            ConnectionError: If reconnect or loop subscribe fails.
            RuntimeError: If bootstrap returns an error-shaped status event.
        """
        if self._client.is_connection_alive():
            return

        resume_loop_id = self._loop_id
        logger.info(
            "Daemon WebSocket closed; reconnecting%s",
            f" to loop {resume_loop_id[:8]}..." if resume_loop_id else "",
        )
        await self._client.close()
        if self._rpc_connected:
            await self._rpc_client.close()
            self._rpc_connected = False

        await connect_websocket_with_retries(self._client)
        await self._bootstrap_loop(resume_loop_id=resume_loop_id)

    async def close(self, *, handshake_timeout: float = 2.0) -> None:
        """Close the daemon websocket(s).

        Idempotent: safe to call from both quit handlers and ``run_textual_app``
        teardown. Closes stream and RPC sockets in parallel.

        Args:
            handshake_timeout: Per-socket WebSocket close-handshake budget.
        """
        if self._closed:
            return
        self._closed = True
        await asyncio.gather(
            self._client.close(handshake_timeout=handshake_timeout),
            self._rpc_client.close(handshake_timeout=handshake_timeout),
            return_exceptions=True,
        )
        self._rpc_connected = False

    async def detach(self) -> None:
        """Detach this client from the daemon.

        No-op when the stream socket is already closed (e.g. daemon restart or
        network drop before quit). The daemon treats disconnect as idempotent.
        """
        if not self._client.is_connected:
            logger.debug("Skipping detach — connection already closed")
            return
        try:
            await self._client.notify("disconnect", {})
        except ConnectionError:
            logger.debug("Daemon connection closed before detach")

    async def send_turn(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        preferred_subagent: str | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        attachments: list[dict[str, str]] | None = None,
        clarification_mode: str | None = None,
        clarification_answer: bool = False,
        clarification_answers: list[str] | None = None,
    ) -> None:
        """Send a new user turn to the daemon."""
        if not self._loop_id:
            raise RuntimeError("No active loop session")
        await self._client.send_input(
            self._loop_id,
            text,
            autonomous=autonomous,
            max_iterations=max_iterations,
            preferred_subagent=preferred_subagent,
            model=model,
            model_params=model_params,
            attachments=attachments,
            clarification_mode=clarification_mode,
            clarification_answer=clarification_answer,
            clarification_answers=clarification_answers,
        )

    async def cancel_remote_query(self) -> None:
        """Ask the daemon to cancel the in-flight query (same wire path as ``/cancel``)."""
        await self._client.notify("slash_command", {"cmd": "/cancel"})

    async def cancel_active_turn(self) -> None:
        """Cancel the in-flight query on the active loop (IG-533 ordering contract).

        Call before switching ``loop_id`` (e.g. ``/clear``) so synthesis on the
        prior loop is torn down server-side instead of filtered client-side.
        """
        await self.cancel_remote_query()

    async def _drain_stream_events_after_idle(
        self,
        *,
        expected_loop_id: str | None,
    ) -> Any:
        """Yield stream chunks that arrive just after ``idle`` (headless client parity)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + getattr(
            self, "_post_idle_drain_deadline", _POST_IDLE_DRAIN_DEADLINE_S
        )
        exp = expected_loop_id
        while loop.time() < deadline:
            try:
                event = await asyncio.wait_for(self._client.read_event(), timeout=0.25)
            except TimeoutError:
                break
            if not event:
                break
            event_type = event.get("type", "")
            # Unwrap protocol-1 ``next`` envelopes to the inner streaming frame
            # (RFC-450 §9.3); ``status``/``error`` arrive raw and pass through.
            if event_type == "next":
                event = _unwrap_next(event) or event
                event_type = event.get("type", "")
            event_loop_id = event.get("loop_id")
            if exp and isinstance(event_loop_id, str) and event_loop_id and event_loop_id != exp:
                logger.debug(
                    "Skipping daemon event for non-active loop %s (active=%s, type=%s)",
                    event_loop_id,
                    exp,
                    event_type,
                )
                continue
            if event_type == "error":
                # Protocol-1 error envelope: {type:'error', error:{code, message, data}}
                err_obj = event.get("error") or {}
                err_msg = str(err_obj.get("message") or event.get("message") or "daemon error")
                raise RuntimeError(err_msg)
            if event_type == "status":
                loop_ev = event.get("loop_id")
                if isinstance(loop_ev, str) and loop_ev:
                    self._loop_id = loop_ev
                    exp = loop_ev
                continue
            if event_type != "event":
                continue
            data = event.get("data")
            namespace = tuple(event.get("namespace", []) or [])
            mode = str(event.get("mode", ""))
            if should_drop_stream_chunk_early(namespace, mode, data):
                self.turn_event_stats.filtered_early += 1
                continue
            self.turn_event_stats.post_idle_drained += 1
            yield (namespace, mode, data)
            if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                continue

    async def list_loops(self, *, limit: int = 20) -> dict[str, Any]:
        """Return the ``loop_list`` result from the daemon (RPC socket, not stream socket)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.request("loop_list", {"limit": limit}, timeout=15.0)

    async def iter_turn_chunks(self) -> Any:
        """Yield `(namespace, mode, data)` chunks for the active daemon turn."""
        self.turn_event_stats = TurnEventStats()
        self.last_turn_end_state = None
        self.last_turn_cancellation_seen = False
        self.last_turn_error_message = None
        inbound_dropped_baseline = getattr(self._client, "inbound_dropped", 0)
        query_started = False
        expected_loop_id = self._loop_id
        self._streaming = True
        turn_read_started = time.monotonic()
        first_event_logged = False
        progress_seen = False
        stale_pending = self._client.peel_stale_pending_control_events()
        if stale_pending:
            logger.debug(
                "Peeled %d stale pending control frame(s) before turn (loop=%s): %s",
                len(stale_pending),
                (expected_loop_id or "?")[:16],
                ", ".join(stale_pending[:8]),
            )
        async with self._read_lock:
            try:
                while True:
                    if not progress_seen and time.monotonic() - turn_read_started > 30.0:
                        logger.warning(
                            "No daemon stream progress after %.0fs (loop=%s, "
                            "query_started=%s); check daemon sender / WebSocket reader",
                            time.monotonic() - turn_read_started,
                            (expected_loop_id or "?")[:16],
                            query_started,
                        )
                        turn_read_started = time.monotonic()
                    event = await self._client.read_event()
                    if event and not first_event_logged:
                        first_event_logged = True
                        logger.debug(
                            "First daemon event on turn: type=%s loop_id=%s",
                            event.get("type"),
                            event.get("loop_id"),
                        )
                    if not event:
                        if query_started and not self._client.is_connection_alive():
                            self.last_turn_end_state = "connection_lost"
                            raise ConnectionError("Daemon connection lost")
                        break

                    event_type = event.get("type", "")

                    # Protocol-1 wraps free-form streaming frames (event/
                    # command_response/card replay) in ``next`` envelopes; unwrap
                    # to the inner frame so the legacy ``type``/``data``/``mode``
                    # branches below keep working. ``status``/``error`` are sent
                    # raw and pass through unchanged.
                    if event_type == "next":
                        event = _unwrap_next(event) or event
                        event_type = event.get("type", "")

                    event_loop_id = event.get("loop_id")

                    if (
                        expected_loop_id
                        and isinstance(event_loop_id, str)
                        and event_loop_id
                        and event_loop_id != expected_loop_id
                    ):
                        logger.debug(
                            "Skipping daemon event for non-active loop %s (active=%s, type=%s)",
                            event_loop_id,
                            expected_loop_id,
                            event_type,
                        )
                        continue

                    if event_type == "error":
                        # Protocol-1 error envelope: {type:'error', error:{code, message, data}}
                        err_obj = event.get("error") or {}
                        err_msg = str(
                            err_obj.get("message") or event.get("message") or "daemon error"
                        )
                        raise RuntimeError(err_msg)

                    if event_type == "status":
                        loop_ev = event.get("loop_id")
                        if isinstance(loop_ev, str) and loop_ev:
                            self._loop_id = loop_ev
                            # Keep filter aligned with daemon-canonical loop_id whenever
                            # status carries it (avoids dropping subsequent events).
                            expected_loop_id = loop_ev
                        state = event.get("state", "")
                        if state == "running":
                            query_started = True
                            progress_seen = True
                        elif query_started and state in {"idle", "stopped"}:
                            self.last_turn_end_state = state
                            async for chunk in self._drain_stream_events_after_idle(
                                expected_loop_id=expected_loop_id,
                            ):
                                yield chunk
                            break
                        continue

                    if event_type == "command_response":
                        content = str(event.get("content", ""))
                        if "Cancellation requested" in content:
                            self.last_turn_cancellation_seen = True
                        continue

                    if event_type != "event":
                        continue

                    data = event.get("data")
                    namespace = tuple(event.get("namespace", []) or [])
                    mode = str(event.get("mode", ""))
                    if should_drop_stream_chunk_early(namespace, mode, data):
                        self.turn_event_stats.filtered_early += 1
                        continue
                    progress_seen = True
                    yield (namespace, mode, data)
                    # Graph auto-resumes LangGraph interrupts server-side; keep consuming events.
                    if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                        continue
            except Exception as exc:
                self.last_turn_error_message = str(exc)
                raise
            finally:
                self._streaming = False
                self.turn_event_stats.inbound_dropped = max(
                    0,
                    getattr(self._client, "inbound_dropped", 0) - inbound_dropped_baseline,
                )

    async def list_skills(self) -> list[dict[str, Any]]:
        """Return skill rows from the daemon catalog (no filesystem paths)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            response = await self._rpc_client.list_skills(timeout=15.0)
        skills = response.get("skills", [])
        if not isinstance(skills, list):
            return []
        return [s for s in skills if isinstance(s, dict)]

    async def list_models(self) -> dict[str, Any]:
        """Return daemon ``models_list`` result (models + default_model from server config)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.list_models(timeout=15.0)

    async def get_mcp_status(self) -> dict[str, Any]:
        """Return daemon ``mcp_status`` result (MCP server info for TUI viewer)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.get_mcp_status(timeout=15.0)

    async def invoke_skill(
        self,
        skill: str,
        args: str = "",
        *,
        clarification_mode: str | None = None,
    ) -> dict[str, Any]:
        """Resolve ``SKILL.md`` on the daemon and receive UI echo before the turn streams.

        Uses the loop WebSocket (``_client``), not the metadata RPC socket. The daemon
        enqueues the composed prompt on ``_client_subscribed_loop_id``; the RPC-only
        connection never receives ``loop_subscribe``, so skill turns would otherwise
        never start (no ``loop_input`` queue entry).

        ``clarification_mode`` is forwarded so slash-skill turns honor the
        TUI's Manual/Auto badge instead of always falling back to the daemon's
        configured default (RFC-622).
        """
        async with self._read_lock:
            return await self._client.invoke_skill(
                skill,
                args,
                timeout=120.0,
                clarification_mode=clarification_mode,
            )

    async def _ensure_rpc_connected(self) -> None:
        """Ensure dedicated RPC client is connected and handshake-complete."""
        if self._rpc_connected:
            return
        await connect_websocket_with_retries(self._rpc_client)
        await self._rpc_client.request_connection_init()
        await self._rpc_client.wait_for_connection_ack(ack_timeout_s=_RPC_HANDSHAKE_TIMEOUT_S)
        self._rpc_connected = True

    async def fetch_loop_cards(self, loop_id: str) -> SimpleNamespace:
        """Fetch the daemon's bound display-card snapshot for a loop.

        RFC-413: returns a populated ledger (eagerly backfilled if the loop
        has no ``cards.jsonl`` yet) so resume can render through the same
        binder that produced the original cards.

        Args:
            loop_id: StrangeLoop id.

        Returns:
            ``SimpleNamespace`` with ``cards: list[dict]``, ``seq: int``,
            ``success: bool``. On error, ``cards=[]`` and ``success=False`` so
            the caller can fall back to the legacy resume path.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return SimpleNamespace(cards=[], seq=0, success=False)

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            try:
                resp = await self._rpc_client.request(
                    "loop_cards_fetch",
                    {"loop_id": lid},
                    timeout=30.0,
                )
            except Exception:
                logger.warning(
                    "loop_cards_fetch failed for loop %s",
                    lid[:16],
                    exc_info=True,
                )
                return SimpleNamespace(cards=[], seq=0, success=False)

        raw_cards = resp.get("cards")
        cards = list(raw_cards) if isinstance(raw_cards, list) else []
        seq = int(resp.get("seq") or 0)
        context_tokens_raw = resp.get("context_tokens")
        context_tokens = (
            context_tokens_raw
            if isinstance(context_tokens_raw, int) and context_tokens_raw >= 0
            else 0
        )
        return SimpleNamespace(
            cards=cards,
            seq=seq,
            context_tokens=context_tokens,
            success=True,
        )

    async def fetch_loop_history(self, loop_id: str) -> SimpleNamespace:
        """Fetch goal display snapshots plus live card tail (RFC-631).

        Args:
            loop_id: StrangeLoop id.

        Returns:
            ``SimpleNamespace`` with ``goals``, ``live_cards``, ``live_goal_index``,
            ``context_tokens``, and ``success``.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return SimpleNamespace(
                goals=[],
                live_cards=[],
                live_goal_index=None,
                context_tokens=0,
                success=False,
            )

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            try:
                resp = await self._rpc_client.request(
                    "loop_history_fetch",
                    {"loop_id": lid},
                    timeout=30.0,
                )
            except Exception:
                logger.warning(
                    "loop_history_fetch failed for loop %s",
                    lid[:16],
                    exc_info=True,
                )
                return SimpleNamespace(
                    goals=[],
                    live_cards=[],
                    live_goal_index=None,
                    context_tokens=0,
                    success=False,
                )

        goals_raw = resp.get("goals")
        goals = list(goals_raw) if isinstance(goals_raw, list) else []
        live_raw = resp.get("live_cards")
        live_cards = list(live_raw) if isinstance(live_raw, list) else []
        live_goal_index = resp.get("live_goal_index")
        if live_goal_index is not None and not isinstance(live_goal_index, int):
            live_goal_index = None
        context_tokens_raw = resp.get("context_tokens")
        context_tokens = (
            context_tokens_raw
            if isinstance(context_tokens_raw, int) and context_tokens_raw >= 0
            else 0
        )
        success = bool(resp.get("success", True))
        return SimpleNamespace(
            goals=goals,
            live_cards=live_cards,
            live_goal_index=live_goal_index,
            context_tokens=context_tokens,
            success=success,
        )

    async def aget_loop_state(self, loop_id: str) -> Any:
        """Load StrangeLoop state channels from the daemon (``loop_state_get`` RPC).

        Returns a namespace with a ``values`` mapping so history code can share the
        same consumption pattern as the in-process agent snapshot, without passing
        graph config objects over the wire.

        Args:
            loop_id: StrangeLoop id.

        Returns:
            ``types.SimpleNamespace`` with ``values: dict[str, Any]``.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return SimpleNamespace(values={})

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            try:
                resp = await self._rpc_client.request(
                    "loop_state_get",
                    {"loop_id": lid},
                    timeout=30.0,
                )
            except Exception:
                logger.warning(
                    "loop_state_get failed for loop %s",
                    lid[:16],
                    exc_info=True,
                )
                return SimpleNamespace(values={})

        raw = resp.get("values")
        values: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
        return SimpleNamespace(values=values)

    async def aupdate_loop_state(
        self,
        loop_id: str,
        values: dict[str, Any],
        *,
        timeout: float = 10.0,
        as_node: str | None = None,
    ) -> None:
        """Merge partial state into the loop on the daemon host (``loop_state_update`` RPC).

        Args:
            loop_id: StrangeLoop id.
            values: Channel updates (e.g. ``messages``) in JSON-serializable form.
            timeout: RPC wait budget in seconds.
            as_node: Optional LangGraph node to attribute the write to. When
                omitted, the daemon picks a sensible default for the underlying
                agent graph.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return

        payload_values = _serialize_for_json(values)
        if not isinstance(payload_values, dict):
            return

        params: dict[str, Any] = {
            "loop_id": lid,
            "values": payload_values,
        }
        if as_node:
            params["as_node"] = as_node

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            await self._rpc_client.request(
                "loop_state_update",
                params,
                timeout=timeout,
            )

    async def fetch_conversation_log(
        self,
        loop_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        include_events: bool = False,
    ) -> list[dict[str, Any]]:
        """Load persisted rows for a loop from the daemon (conversation + optional events)."""
        lid = str(loop_id or "").strip()
        if not lid:
            return []

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            resp = await self._rpc_client.request(
                "loop_messages",
                {
                    "loop_id": lid,
                    "limit": limit,
                    "offset": offset,
                    "include_events": include_events,
                },
                timeout=10.0,
            )

        raw = resp.get("messages")
        if not isinstance(raw, list):
            return []
        return [m for m in raw if isinstance(m, dict)]

    async def fetch_goal_completion_text(self, loop_id: str) -> str | None:
        """Return the latest persisted ``goal_completion`` body for a loop, if any."""
        rows = await self.fetch_conversation_log(loop_id, limit=200, include_events=False)
        for row in reversed(rows):
            if row.get("phase") != "goal_completion":
                continue
            text = row.get("text") or row.get("content") or ""
            if isinstance(text, str) and text.strip():
                return text.strip()
        return None


DaemonSession = TuiDaemonSession

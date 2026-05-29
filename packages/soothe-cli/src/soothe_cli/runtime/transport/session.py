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
_POST_IDLE_DRAIN_DEADLINE_S = 2.5


class TuiDaemonSession:
    """Own the daemon websocket session used by the TUI."""

    def __init__(self, cfg: Any, *, workspace: str | None = None) -> None:
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
        self.turn_event_stats = TurnEventStats()

    @property
    def loop_id(self) -> str | None:
        """Active AgentLoop id for this WebSocket session."""
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
            verbosity="normal",
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
        """Start a new AgentLoop conversation."""
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

    async def close(self) -> None:
        """Close the daemon websocket."""
        await self._client.close()
        await self._rpc_client.close()
        self._rpc_connected = False

    async def detach(self) -> None:
        """Detach this client from the daemon."""
        await self._client.send_detach()

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
        )

    async def cancel_remote_query(self) -> None:
        """Ask the daemon to cancel the in-flight query (same wire path as ``/cancel``)."""
        await self._client.send_command("/cancel")

    async def _drain_stream_events_after_idle(
        self,
        *,
        expected_loop_id: str | None,
    ) -> Any:
        """Yield stream chunks that arrive just after ``idle`` (headless client parity)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _POST_IDLE_DRAIN_DEADLINE_S
        exp = expected_loop_id
        while loop.time() < deadline:
            try:
                event = await asyncio.wait_for(self._client.read_event(), timeout=0.25)
            except TimeoutError:
                break
            if not event:
                break
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
                raise RuntimeError(str(event.get("message", "daemon error")))
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
        """Return ``loop_list_response`` from the daemon (RPC socket, not stream socket)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.request_response(
                {"type": "loop_list", "limit": limit},
                response_type="loop_list_response",
                timeout=15.0,
            )

    async def iter_turn_chunks(self) -> Any:
        """Yield `(namespace, mode, data)` chunks for the active daemon turn."""
        self.turn_event_stats = TurnEventStats()
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
                            raise ConnectionError("Daemon connection lost")
                        break

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
                        raise RuntimeError(str(event.get("message", "daemon error")))

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
                            async for chunk in self._drain_stream_events_after_idle(
                                expected_loop_id=expected_loop_id,
                            ):
                                yield chunk
                            break
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
                    # Graph may auto-resume after HITL interrupts; keep consuming events.
                    if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                        continue
            finally:
                self._streaming = False

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
        """Return daemon ``models_list_response`` (models + default_model from server config)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.list_models(timeout=15.0)

    async def get_mcp_status(self) -> dict[str, Any]:
        """Return daemon ``mcp_status_response`` (MCP server info for TUI viewer)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.get_mcp_status(timeout=15.0)

    async def invoke_skill(self, skill: str, args: str = "") -> dict[str, Any]:
        """Resolve ``SKILL.md`` on the daemon and receive UI echo before the turn streams.

        Uses the loop WebSocket (``_client``), not the metadata RPC socket. The daemon
        enqueues the composed prompt on ``_client_subscribed_loop_id``; the RPC-only
        connection never receives ``loop_subscribe``, so skill turns would otherwise
        never start (no ``loop_input`` queue entry).
        """
        async with self._read_lock:
            return await self._client.invoke_skill(skill, args, timeout=120.0)

    async def _ensure_rpc_connected(self) -> None:
        """Ensure dedicated RPC client is connected."""
        if self._rpc_connected:
            return
        await connect_websocket_with_retries(self._rpc_client)
        self._rpc_connected = True

    async def aget_loop_state(self, loop_id: str) -> Any:
        """Load agent-loop state channels from the daemon (``loop_state_get`` RPC).

        Returns a namespace with a ``values`` mapping so history code can share the
        same consumption pattern as the in-process agent snapshot, without passing
        graph config objects over the wire.

        Args:
            loop_id: AgentLoop id.

        Returns:
            ``types.SimpleNamespace`` with ``values: dict[str, Any]``.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return SimpleNamespace(values={})

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            try:
                resp = await self._rpc_client.request_response(
                    {"type": "loop_state_get", "loop_id": lid},
                    response_type="loop_state_get_response",
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
    ) -> None:
        """Merge partial state into the loop on the daemon host (``loop_state_update`` RPC).

        Args:
            loop_id: AgentLoop id.
            values: Channel updates (e.g. ``messages``) in JSON-serializable form.
            timeout: RPC wait budget in seconds.
        """
        lid = str(loop_id or "").strip()
        if not lid:
            return

        payload_values = _serialize_for_json(values)
        if not isinstance(payload_values, dict):
            return

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            await self._rpc_client.request_response(
                {
                    "type": "loop_state_update",
                    "loop_id": lid,
                    "values": payload_values,
                },
                response_type="loop_state_update_response",
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
            resp = await self._rpc_client.request_response(
                {
                    "type": "loop_messages",
                    "loop_id": lid,
                    "limit": limit,
                    "offset": offset,
                    "include_events": include_events,
                },
                response_type="loop_messages_response",
                timeout=10.0,
            )

        raw = resp.get("messages")
        if not isinstance(raw, list):
            return []
        return [m for m in raw if isinstance(m, dict)]


DaemonSession = TuiDaemonSession

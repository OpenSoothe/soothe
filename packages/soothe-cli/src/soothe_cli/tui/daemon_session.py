"""Daemon-backed session helpers for the Textual TUI."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import messages_from_dict
from soothe_sdk.client import (
    WebSocketClient,
    bootstrap_loop_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)
from soothe_sdk.client.wire import envelope_langchain_message_dict, messages_from_wire_dicts

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DaemonStateSnapshot:
    """Minimal `aget_state()` compatible wrapper."""

    values: dict[str, Any]


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
        status_event = await bootstrap_loop_session(
            self._client,
            resume_loop_id=resume_loop_id,
            verbosity="normal",
            workspace=self._workspace,
        )
        if status_event.get("type") == "error":
            raise RuntimeError(str(status_event.get("message", "daemon bootstrap failed")))
        self._loop_id = status_event.get("loop_id")
        return status_event

    async def new_thread(self) -> dict[str, Any]:
        """Start a new AgentLoop conversation."""
        return await self._bootstrap_loop(resume_loop_id=None)

    async def switch_loop(self, loop_id: str) -> dict[str, Any]:
        """Subscribe to an existing loop (re-bootstrap on the same connection)."""
        return await self._bootstrap_loop(resume_loop_id=loop_id)

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
        interactive: bool = True,
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
            interactive=interactive,
            model=model,
            model_params=model_params,
            attachments=attachments,
        )

    async def cancel_remote_query(self) -> None:
        """Ask the daemon to cancel the in-flight query (same wire path as ``/cancel``)."""
        await self._client.send_command("/cancel")

    async def resume_interrupts(self, resume_payload: dict[str, Any]) -> None:
        """Resume a paused interactive turn."""
        if not self._loop_id:
            raise RuntimeError("No active loop for interrupt resume")
        await self._client.send_resume_interrupts(self._loop_id, resume_payload)

    async def iter_turn_chunks(self) -> Any:
        """Yield `(namespace, mode, data)` chunks for the active daemon turn."""
        query_started = False
        expected_loop_id = self._loop_id
        self._streaming = True
        async with self._read_lock:
            try:
                while True:
                    event = await self._client.read_event()
                    if not event:
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
                            if expected_loop_id is None:
                                expected_loop_id = loop_ev
                        state = event.get("state", "")
                        if state == "running":
                            query_started = True
                        elif query_started and state in {"idle", "stopped"}:
                            break
                        continue

                    if event_type != "event":
                        continue

                    data = event.get("data")
                    if (
                        isinstance(data, dict)
                        and data.get("type") == "soothe.system.daemon.heartbeat"
                    ):
                        continue

                    namespace = tuple(event.get("namespace", []) or [])
                    mode = str(event.get("mode", ""))
                    normalized = self._normalize_stream_data(mode, data)
                    yield (namespace, mode, normalized)
                    if (
                        mode == "updates"
                        and isinstance(normalized, dict)
                        and "__interrupt__" in normalized
                    ):
                        break
            finally:
                self._streaming = False

    def _normalize_stream_data(self, mode: str, data: Any) -> Any:
        """Convert daemon wire payloads back to TUI-friendly objects."""
        if mode != "messages":
            return data

        if not isinstance(data, (list, tuple)) or len(data) != 2:
            return data

        message, metadata = data
        if isinstance(message, dict):
            try:
                to_restore = envelope_langchain_message_dict(message)
                restored = messages_from_dict([to_restore])
                if restored:
                    message = restored[0]
            except Exception:
                logger.debug("Failed to restore message from daemon payload", exc_info=True)
        return (message, metadata)

    async def aget_state(self, config: dict[str, Any]) -> DaemonStateSnapshot:
        """Fetch thread state values through the daemon."""
        thread_id = str(config.get("configurable", {}).get("thread_id", "")).strip()
        if not thread_id:
            return DaemonStateSnapshot(values={})
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            response = await self._rpc_client.request_response(
                {"type": "thread_state", "thread_id": thread_id},
                response_type="thread_state_response",
            )
        values = response.get("values", {})
        if not isinstance(values, dict):
            values = {}
        messages = values.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            try:
                values = dict(values)
                values["messages"] = messages_from_wire_dicts(messages)
            except Exception:
                logger.debug("Failed to deserialize thread-state messages", exc_info=True)
        return DaemonStateSnapshot(values=values)

    async def fetch_conversation_log(
        self,
        conversation_id: str,
        *,
        limit: int = 10000,
        offset: int = 0,
        include_events: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch persisted conversation rows through the daemon (checkpoint / durability id).

        Args:
            conversation_id: CoreAgent checkpoint conversation id (LangGraph ``configurable.thread_id``).
            limit: Maximum records to return.
            offset: Pagination offset.
            include_events: Include non-conversation event records.

        Returns:
            Wire-safe rows from ``thread_messages_response``.
        """
        if not conversation_id:
            return []

        payload: dict[str, Any] = {
            "type": "thread_messages",
            "thread_id": conversation_id,
            "limit": limit,
            "offset": offset,
        }
        if include_events:
            payload["include_events"] = True

        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            response = await self._rpc_client.request_response(
                payload,
                response_type="thread_messages_response",
                timeout=10.0,
            )
        messages = response.get("messages", [])
        if not isinstance(messages, list):
            return []
        return [m for m in messages if isinstance(m, dict)]

    async def aupdate_state(
        self, config: dict[str, Any], values: dict[str, Any], timeout: float = 5.0
    ) -> None:
        """Persist partial thread state through the daemon.

        Args:
            config: Thread configuration containing thread_id.
            values: State values to persist.
            timeout: Timeout in seconds for daemon response. Default 5.0s.
                Use shorter timeout (e.g., 2.0s) during interrupt cleanup.
        """
        thread_id = str(config.get("configurable", {}).get("thread_id", "")).strip()
        if not thread_id:
            return
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            await self._rpc_client.request_response(
                {
                    "type": "thread_update_state",
                    "thread_id": thread_id,
                    "values": values,
                },
                response_type="thread_update_state_response",
                timeout=timeout,
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
        """Return daemon ``models_list_response`` (models + default_model from server config)."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.list_models(timeout=15.0)

    async def invoke_skill(self, skill: str, args: str = "") -> dict[str, Any]:
        """Resolve ``SKILL.md`` on the daemon and receive UI echo before the turn streams."""
        async with self._rpc_lock:
            await self._ensure_rpc_connected()
            return await self._rpc_client.invoke_skill(skill, args, timeout=120.0)

    async def _ensure_rpc_connected(self) -> None:
        """Ensure dedicated RPC client is connected."""
        if self._rpc_connected:
            return
        await connect_websocket_with_retries(self._rpc_client)
        self._rpc_connected = True

"""Daemon-backed session helpers for the Textual TUI."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import messages_from_dict
from soothe_sdk.client import WebSocketClient

from soothe_cli.client import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

if TYPE_CHECKING:
    # TODO IG-174 Phase 5: Create CLI-specific config class
# SootheConfig import kept for daemon RPC communication
from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DaemonStateSnapshot:
    """Minimal `aget_state()` compatible wrapper."""

    values: dict[str, Any]


class TuiDaemonSession:
    """Own the daemon websocket session used by the TUI."""

    def __init__(self, cfg: SootheConfig) -> None:
        self._cfg = cfg
        self._client = WebSocketClient(url=websocket_url_from_config(cfg))
        self._thread_id: str | None = None
        self._read_lock = asyncio.Lock()
        self._streaming = False

    @property
    def thread_id(self) -> str | None:
        """Current thread ID known to the session."""
        return self._thread_id

    async def connect(self, *, resume_thread_id: str | None = None) -> dict[str, Any]:
        """Connect and bootstrap a daemon thread session."""
        await connect_websocket_with_retries(self._client)
        status_event = await self._bootstrap_thread(resume_thread_id=resume_thread_id)
        return status_event

    async def _bootstrap_thread(self, *, resume_thread_id: str | None = None) -> dict[str, Any]:
        """Create or resume a daemon thread on an already-connected websocket."""
        status_event = await bootstrap_thread_session(
            self._client,
            resume_thread_id=resume_thread_id,
            verbosity=self._cfg.logging.verbosity,
        )
        if status_event.get("type") == "error":
            raise RuntimeError(str(status_event.get("message", "daemon bootstrap failed")))
        self._thread_id = status_event.get("thread_id")
        return status_event

    async def new_thread(self) -> dict[str, Any]:
        """Switch the session to a new daemon thread."""
        return await self._bootstrap_thread(resume_thread_id=None)

    async def switch_thread(self, thread_id: str) -> dict[str, Any]:
        """Switch the session to a specific persisted thread."""
        return await self._bootstrap_thread(resume_thread_id=thread_id)

    async def close(self) -> None:
        """Close the daemon websocket."""
        await self._client.close()

    async def detach(self) -> None:
        """Detach this client from the daemon."""
        await self._client.send_detach()

    async def send_turn(
        self,
        text: str,
        *,
        autonomous: bool = False,
        max_iterations: int | None = None,
        subagent: str | None = None,
        interactive: bool = True,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
    ) -> None:
        """Send a new user turn to the daemon."""
        await self._client.send_input(
            text,
            autonomous=autonomous,
            max_iterations=max_iterations,
            subagent=subagent,
            interactive=interactive,
            model=model,
            model_params=model_params,
        )

    async def cancel_remote_query(self) -> None:
        """Ask the daemon to cancel the in-flight query (same wire path as ``/cancel``)."""
        await self._client.send_command("/cancel")

    async def resume_interrupts(self, resume_payload: dict[str, Any]) -> None:
        """Resume a paused interactive turn."""
        if not self._thread_id:
            raise RuntimeError("No active daemon thread")
        await self._client.send_resume_interrupts(self._thread_id, resume_payload)

    async def iter_turn_chunks(self) -> Any:
        """Yield `(namespace, mode, data)` chunks for the active daemon turn."""
        query_started = False
        self._streaming = True
        async with self._read_lock:
            try:
                while True:
                    event = await self._client.read_event()
                    if not event:
                        break

                    event_type = event.get("type", "")
                    if event_type == "error":
                        raise RuntimeError(str(event.get("message", "daemon error")))

                    if event_type == "status":
                        thread_id = event.get("thread_id")
                        if isinstance(thread_id, str) and thread_id:
                            self._thread_id = thread_id
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
                        and data.get("type") == "soothe.lifecycle.daemon.heartbeat"
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
                restored = messages_from_dict([message])
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
        async with self._read_lock:
            response = await self._client.request_response(
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
                values["messages"] = messages_from_dict(messages)
            except Exception:
                logger.debug("Failed to deserialize thread-state messages", exc_info=True)
        return DaemonStateSnapshot(values=values)

    async def aupdate_state(self, config: dict[str, Any], values: dict[str, Any]) -> None:
        """Persist partial thread state through the daemon."""
        thread_id = str(config.get("configurable", {}).get("thread_id", "")).strip()
        if not thread_id:
            return
        async with self._read_lock:
            await self._client.request_response(
                {
                    "type": "thread_update_state",
                    "thread_id": thread_id,
                    "values": values,
                },
                response_type="thread_update_state_response",
            )

    async def list_skills(self) -> list[dict[str, Any]]:
        """Return skill rows from the daemon catalog (no filesystem paths)."""
        async with self._read_lock:
            response = await self._client.list_skills(timeout=15.0)
        skills = response.get("skills", [])
        if not isinstance(skills, list):
            return []
        return [s for s in skills if isinstance(s, dict)]

    async def list_models(self) -> dict[str, Any]:
        """Return daemon ``models_list_response`` (models + default_model from server config)."""
        async with self._read_lock:
            return await self._client.list_models(timeout=15.0)

    async def invoke_skill(self, skill: str, args: str = "") -> dict[str, Any]:
        """Resolve ``SKILL.md`` on the daemon and receive UI echo before the turn streams."""
        async with self._read_lock:
            return await self._client.invoke_skill(skill, args, timeout=120.0)

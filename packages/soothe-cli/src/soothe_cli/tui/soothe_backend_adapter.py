"""Legacy compatibility adapter over the daemon-native TUI session."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # TODO IG-174 Phase 5: CLI-specific config class complete

    from soothe_cli.tui.daemon_session import TuiDaemonSession


class SootheBackendAdapter:
    """Expose a small legacy surface over `TuiDaemonSession`.

    The new daemon-native TUI path uses `TuiDaemonSession` directly. This class
    remains only as a thin compatibility wrapper for older call sites.
    """

    def __init__(
        self,
        daemon_session: TuiDaemonSession,
        config: SootheConfig,
    ) -> None:
        """Initialize the compatibility adapter."""
        self._daemon_session = daemon_session
        self._config = config

    async def stream_messages(
        self,
        user_input: str,
    ) -> AsyncIterator[tuple[tuple[str, ...], str, Any]]:
        """Send a turn and stream daemon-native chunks."""
        await self._daemon_session.send_turn(user_input, interactive=True)
        async for chunk in self._daemon_session.iter_turn_chunks():
            yield chunk

    async def get_thread_history(
        self,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """Return basic conversation history for a thread."""
        state = await self._daemon_session.aget_state({"configurable": {"thread_id": thread_id}})
        messages = []
        for msg in state.values.get("messages", []):
            role = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"
            messages.append({"role": role, "content": content})
        return messages

    async def list_threads(self) -> list[dict[str, Any]]:
        """List threads through the daemon websocket protocol."""
        response = await self._daemon_session._client.request_response(  # noqa: SLF001
            {"type": "thread_list", "include_stats": True, "include_last_message": True},
            response_type="thread_list_response",
        )
        threads = response.get("threads", [])
        return list(threads) if isinstance(threads, list) else []

    def get_agent_metadata(self) -> dict[str, Any]:
        """Provide basic session metadata for legacy callers."""
        return {
            "model": self._config.resolve_model("default"),
            "tools": [],
            "subagents": [],
        }

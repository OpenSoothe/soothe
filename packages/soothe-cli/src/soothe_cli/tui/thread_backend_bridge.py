"""Legacy compatibility bridge over the daemon-native TUI session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # TODO IG-174 Phase 5: Create CLI-specific config class
# SootheConfig import kept for daemon RPC communication
from soothe.config import SootheConfig

    from soothe_cli.tui.daemon_session import TuiDaemonSession


class ThreadBackendBridge:
    """Expose minimal thread-selector helpers over `TuiDaemonSession`."""

    def __init__(
        self,
        daemon_session: TuiDaemonSession,
        config: SootheConfig,
    ) -> None:
        """Initialize with the daemon-backed session."""
        self._daemon_session = daemon_session
        self._config = config

    async def list_threads_for_ui(self) -> list[dict[str, Any]]:
        """List threads through the daemon protocol."""
        response = await self._daemon_session._client.request_response(  # noqa: SLF001
            {"type": "thread_list", "include_stats": True, "include_last_message": True},
            response_type="thread_list_response",
        )
        threads = response.get("threads", [])
        return list(threads) if isinstance(threads, list) else []

    async def load_thread_messages(
        self,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """Load basic thread messages from daemon thread state."""
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

    async def resume_thread(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """Resume a thread through the daemon session."""
        response = await self._daemon_session.switch_thread(thread_id)
        return {
            "thread_id": response.get("thread_id", thread_id),
            "status": "resumed",
            "thread_resumed": bool(response.get("thread_resumed", True)),
        }


class ThreadResumeError(Exception):
    """Error during thread resume operation."""

    pass

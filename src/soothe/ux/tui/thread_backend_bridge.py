"""Bridge for connecting thread_selector widget to Soothe thread persistence.

This bridge adapts Soothe's ThreadContextManager to the interface
expected by Soothe' thread_selector widget.

RFC-606: Soothe CLI TUI Migration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.core.thread.manager import ThreadContextManager
    from soothe.daemon.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)


class ThreadBackendBridge:
    """Bridge for thread_selector to use Soothe persistence.

    Mimics: Soothe SessionManager interface
    Uses: Soothe ThreadContextManager backend (RFC-402)

    This bridge converts Soothe's thread metadata to the format
    expected by Soothe' thread_selector widget, enabling
    thread resume functionality in the migrated TUI.
    """

    def __init__(
        self,
        thread_manager: ThreadContextManager,
        daemon_client: WebSocketClient,
        config: SootheConfig,
    ) -> None:
        """Initialize with Soothe thread components.

        Args:
            thread_manager: Thread persistence manager
            daemon_client: WebSocket client for daemon commands
            config: Soothe configuration
        """
        self._thread_manager = thread_manager
        self._daemon_client = daemon_client
        self._config = config

    async def list_threads_for_ui(self) -> list[dict[str, Any]]:
        """List threads in Soothe thread_selector format.

        Returns:
            List of thread metadata dicts with fields:
            - id: str
            - created_at: datetime
            - updated_at: datetime
            - message_count: int
            - preview: str (first user message, 100 chars)
            - tags: List[str]
            - has_plan: bool (SOOTHE addition)
            - status: str (SOOTHE: running/completed/archived)
        """
        # SOOTHE: List threads from ThreadContextManager
        threads = await self._thread_manager.list_threads()

        thread_list = []
        for t in threads:
            thread_list.append(
                {
                    "id": t.id,
                    "created_at": t.created_at,
                    "updated_at": t.last_activity,
                    "message_count": len(t.messages),
                    "preview": t.messages[0].content[:100] if t.messages else "",
                    "tags": t.tags or [],
                    # SOOTHE: Additional metadata for Soothe-specific indicators
                    "has_plan": t.has_active_plan,
                    "status": t.status,  # running/completed/archived
                }
            )

        return thread_list

    async def load_thread_messages(
        self,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """Load thread messages in Soothe format.

        Args:
            thread_id: Thread ID to load

        Returns:
            List of message dicts with fields:
            - role: str (user/assistant)
            - content: str
            - timestamp: datetime
            - has_protocol_events: bool (SOOTHE addition)
        """
        # SOOTHE: Load thread from ThreadContextManager
        thread_data = await self._thread_manager.load_thread(thread_id)

        messages = []
        for msg in thread_data.messages:
            messages.append(
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    # SOOTHE: Track protocol events in preview
                    "has_protocol_events": len(msg.protocol_events) > 0,
                }
            )

        return messages

    async def resume_thread(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """Resume thread via daemon.

        Args:
            thread_id: Thread ID to resume

        Returns:
            Resume status dict

        Raises:
            ThreadResumeError: If daemon fails to load thread
        """
        # SOOTHE: Send resume command to daemon
        await self._daemon_client.send(
            {
                "type": "resume_thread",
                "thread_id": thread_id,
            }
        )

        # SOOTHE: Wait for daemon confirmation
        response = await self._daemon_client.recv()

        if response.get("status") == "success":
            return {"thread_id": thread_id, "status": "resumed"}
        else:
            error_msg = response.get("error", "Unknown error")
            logger.error("Thread resume failed: %s", error_msg)
            raise ThreadResumeError(error_msg)


class ThreadResumeError(Exception):
    """Error during thread resume operation."""

    pass

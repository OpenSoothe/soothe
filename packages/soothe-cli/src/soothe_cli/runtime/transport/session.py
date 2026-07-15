"""Daemon-backed session helpers for the Textual TUI.

Thin CLI wrapper over ``soothe_client.appkit.DaemonSession`` that derives
WebSocket URL / stream delivery from CLI config and uses the richer CLI early
chunk filter (LangChain-aware).
"""

from __future__ import annotations

from typing import Any

from soothe_client.appkit import DaemonSession
from soothe_client.helpers import websocket_url_from_config

# Re-exported for test monkeypatches / historical import sites.
from soothe_client.session import (  # noqa: F401
    bootstrap_loop_session,
    connect_websocket_with_retries,
)

from soothe_cli.runtime.state.session_stats import TurnEventStats
from soothe_cli.runtime.wire.chunk_filter import should_drop_stream_chunk_early

# Match headless daemon client post-idle drain window.
_POST_IDLE_DRAIN_DEADLINE_S = 0.5

# Brief close handshake on TUI exit — the daemon cleans up on disconnect anyway.
TUI_EXIT_HANDSHAKE_TIMEOUT_S = 0.3


class TuiDaemonSession(DaemonSession):
    """Own the daemon websocket session used by the TUI."""

    def __init__(
        self,
        cfg: Any,
        *,
        workspace: str | None = None,
        post_idle_drain_deadline: float = _POST_IDLE_DRAIN_DEADLINE_S,
    ) -> None:
        self._cfg = cfg
        super().__init__(
            websocket_url_from_config(cfg),
            workspace=workspace,
            stream_delivery=self._resolve_stream_delivery_mode,
            post_idle_drain_deadline=post_idle_drain_deadline,
            early_drop_fn=should_drop_stream_chunk_early,
            stats_factory=TurnEventStats,
        )

    def _resolve_stream_delivery_mode(self) -> str:
        """Determine stream delivery mode from config (RFC-614).

        Returns one of ``batch`` | ``adaptive`` | ``streaming``. CLI override
        wins, then config; defaults to ``adaptive``.
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


# Historical alias used by some call sites / docs.
DaemonSession = TuiDaemonSession  # noqa: F811

__all__ = [
    "DaemonSession",
    "TUI_EXIT_HANDSHAKE_TIMEOUT_S",
    "TuiDaemonSession",
    "bootstrap_loop_session",
    "connect_websocket_with_retries",
]

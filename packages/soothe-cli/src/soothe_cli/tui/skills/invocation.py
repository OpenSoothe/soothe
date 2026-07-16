"""Skills discovery and invocation helpers for the Soothe Textual TUI."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from soothe_client import (
    connected_websocket,
    fetch_skills_catalog,
    websocket_url_from_config,
)

from soothe_cli.tui.skills.load import ExtendedSkillMetadata

if TYPE_CHECKING:
    from soothe_client import WebSocketClient

    from soothe_cli.config.cli_config import CLIConfig

logger = logging.getLogger(__name__)


async def discover_skills_async(
    daemon_config: CLIConfig | None = None,
    *,
    client: WebSocketClient | None = None,
) -> list[ExtendedSkillMetadata]:
    """Discover skills from daemon RPC.

    Prefers an already-connected ``client`` (e.g. ``DaemonSession.client``) so the
    TUI does not open a second WebSocket. Falls back to a one-shot connection
    when only ``daemon_config`` is provided.

    Args:
        daemon_config: Daemon config for WebSocket URL construction (oneshot path).
        client: Optional live WebSocket client to reuse.

    Returns:
        List of skill metadata dicts sorted by ascending precedence
        (built-in first, winning entry last). Empty list if daemon
        unavailable.
    """
    by_name: OrderedDict[str, ExtendedSkillMetadata] = OrderedDict()

    async def _load(ws: Any) -> None:
        skills_wire = await fetch_skills_catalog(ws, timeout=15.0)
        for skill_meta in skills_wire:
            name = skill_meta.get("name")
            if name:
                by_name[name] = skill_meta

    try:
        if client is not None:
            await _load(client)
        elif daemon_config is not None:
            ws_url = websocket_url_from_config(daemon_config)
            async with connected_websocket(ws_url, timeout=15.0) as ws:
                await _load(ws)
        else:
            logger.warning(
                "No daemon_config or client provided for skills discovery; returning empty catalog"
            )
            return []
    except Exception as e:
        logger.warning("Skills discovery failed: %s", e, exc_info=True)
        return []

    return list(by_name.values())

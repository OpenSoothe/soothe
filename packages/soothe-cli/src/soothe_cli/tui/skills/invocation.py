"""Skills discovery and invocation helpers for the Soothe Textual TUI."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

from soothe_sdk.client import fetch_skills_catalog, websocket_url_from_config

from soothe_cli.tui.skills.load import ExtendedSkillMetadata

if TYPE_CHECKING:
    from soothe_cli.config.cli_config import CLIConfig

logger = logging.getLogger(__name__)


async def discover_skills_async(
    daemon_config: CLIConfig | None = None,
) -> list[ExtendedSkillMetadata]:
    """Discover skills from daemon RPC (IG-174 Phase 2).

    Fetches wire-safe skill metadata from daemon via WebSocket RPC.
    Daemon handles all skill discovery (built-in, user, project, etc.)
    and returns wire-safe metadata. No local filesystem access.

    Args:
        daemon_config: Daemon config for WebSocket URL construction.

    Returns:
        List of skill metadata dicts sorted by ascending precedence
        (built-in first, winning entry last). Empty list if daemon
        unavailable.
    """
    from soothe_sdk.client import WebSocketClient

    if daemon_config is None:
        logger.warning("No daemon_config provided for skills discovery; returning empty catalog")
        return []

    ws_url = websocket_url_from_config(daemon_config)
    client = WebSocketClient(url=ws_url)

    by_name: OrderedDict[str, ExtendedSkillMetadata] = OrderedDict()

    try:
        await client.connect()
        skills_wire = await fetch_skills_catalog(client, timeout=15.0)
        await client.close()

        # Build by_name mapping from wire-safe metadata
        for skill_meta in skills_wire:
            name = skill_meta.get("name")
            if name:
                by_name[name] = skill_meta
    except Exception as e:
        logger.warning(f"Failed to fetch skills from daemon: {e}")
        return []

    return list(by_name.values())


def discover_skills(
    daemon_config: CLIConfig | None = None,
) -> list[ExtendedSkillMetadata]:
    """Backward-compatible sync wrapper for async skills discovery."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(discover_skills_async(daemon_config=daemon_config))
    msg = "discover_skills() cannot be called from a running event loop; use discover_skills_async() instead."
    raise RuntimeError(msg)

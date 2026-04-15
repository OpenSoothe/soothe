"""Skills discovery and invocation helpers for the Soothe Textual TUI."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_sdk.client import fetch_skills_catalog, websocket_url_from_config

from soothe_cli.tui.config import _get_settings
from soothe_cli.tui.skills.load import ExtendedSkillMetadata

if TYPE_CHECKING:
    from soothe_cli.config.cli_config import CLIConfig

logger = logging.getLogger(__name__)


async def discover_skills_and_roots_async(
    assistant_id: str,
    daemon_config: CLIConfig | None = None,
) -> tuple[list[ExtendedSkillMetadata], list[Path]]:
    """Discover skills from daemon RPC and build containment roots (IG-174 Phase 2).

    Fetches wire-safe skill metadata from daemon via WebSocket RPC instead of
    local filesystem scanning. Daemon handles all skill discovery (built-in, user,
    project, etc.) and returns wire-safe metadata.

    Args:
        assistant_id: Agent / assistant id (unused in daemon mode, kept for compat).
        daemon_config: Optional daemon config for WebSocket URL construction.

    Returns:
        Tuple of ``(skills, allowed_roots)`` where ``skills`` is ordered by
        ascending precedence (built-in first, winning entry last), and
        ``allowed_roots`` lists directories from wire-safe path strings.
    """
    from soothe_sdk.client import WebSocketClient

    settings = _get_settings()
    by_name: OrderedDict[str, ExtendedSkillMetadata] = OrderedDict()

    # Fetch skills catalog from daemon via WebSocket RPC
    if daemon_config is None:
        # Fallback: return empty if no config (should not happen in TUI)
        logger.warning("No daemon_config provided for skills discovery")
        return [], []

    ws_url = websocket_url_from_config(daemon_config)
    client = WebSocketClient(url=ws_url)

    try:
        await client.connect()
        skills_wire = await fetch_skills_catalog(client, timeout=15.0)
        await client.close()

        # Build by_name mapping from wire-safe metadata
        for skill_meta in skills_wire:
            name = skill_meta.get("name")
            if name:
                # Convert wire-safe dict to ExtendedSkillMetadata TypedDict
                by_name[name] = skill_meta
    except Exception as e:
        logger.warning(f"Failed to fetch skills from daemon: {e}")
        # Fallback: empty catalog if daemon unavailable
        return [], []

    skills = list(by_name.values())

    # Build allowed_roots from wire-safe path strings
    allowed: list[Path] = []
    seen: set[Path] = set()
    for meta in skills:
        path_str = meta.get("path")
        if path_str:
            p = Path(path_str).resolve()
            if p not in seen:
                seen.add(p)
                allowed.append(p)

    # Add extra skills dirs from settings
    for extra in settings.get_extra_skills_dirs():
        rp = extra.resolve()
        if rp not in seen:
            seen.add(rp)
            allowed.append(rp)

    return skills, allowed


async def discover_skills_and_roots(
    assistant_id: str,
    daemon_config: CLIConfig | None = None,
) -> tuple[list[ExtendedSkillMetadata], list[Path]]:
    """Backward-compatible alias for async skills discovery."""
    return await discover_skills_and_roots_async(
        assistant_id=assistant_id,
        daemon_config=daemon_config,
    )

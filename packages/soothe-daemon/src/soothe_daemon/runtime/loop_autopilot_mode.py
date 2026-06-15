"""Per-loop Solo/Autopilot mode (RFC-625).

When ``config.agent.autonomous.enabled`` is true, new loops default to
``autopilot`` without a TUI ``/autopilot-toggle``. Explicit toggles and
persisted ``autopilot_mode`` metadata override the config default.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

LoopAutopilotMode = Literal["solo", "autopilot"]


def config_default_loop_mode(config: Any) -> LoopAutopilotMode:
    """Return the default loop mode implied by agent config."""
    try:
        enabled = bool(config.agent.autonomous.enabled)
    except AttributeError:
        enabled = False
    return "autopilot" if enabled else "solo"


def _normalize_mode(raw: Any) -> LoopAutopilotMode | None:
    if raw in ("solo", "autopilot"):
        return raw
    return None


async def get_loop_autopilot_mode(daemon: Any, loop_id: str) -> LoopAutopilotMode:
    """Resolve effective autopilot mode for a loop."""
    lid = str(loop_id or "").strip()
    if not lid:
        return config_default_loop_mode(daemon._config)

    cache = getattr(daemon, "_loop_autopilot_modes", None)
    if isinstance(cache, dict):
        cached = _normalize_mode(cache.get(lid))
        if cached is not None:
            return cached

    metadata = await daemon._persistence_manager.get_loop_metadata(lid)
    if metadata:
        persisted = _normalize_mode(metadata.get("autopilot_mode"))
        if persisted is not None:
            if isinstance(cache, dict):
                cache[lid] = persisted
            return persisted

    return config_default_loop_mode(daemon._config)


async def ensure_loop_autopilot_mode(
    daemon: Any,
    loop_id: str,
    *,
    broadcast: bool = False,
) -> LoopAutopilotMode:
    """Initialize loop mode from metadata or config default; persist when missing."""
    lid = str(loop_id or "").strip()
    if not lid:
        return config_default_loop_mode(daemon._config)

    metadata = await daemon._persistence_manager.get_loop_metadata(lid)
    if metadata:
        persisted = _normalize_mode(metadata.get("autopilot_mode"))
        if persisted is not None:
            _cache_mode(daemon, lid, persisted)
            return persisted

    mode = config_default_loop_mode(daemon._config)
    try:
        await daemon._persistence_manager.update_loop_metadata(lid, autopilot_mode=mode)
    except Exception:
        logger.warning("Failed to persist autopilot_mode for loop %s", lid, exc_info=True)
    _cache_mode(daemon, lid, mode)

    if broadcast and mode == "autopilot":
        await broadcast_autopilot_mode(daemon, lid, mode, previous_mode="solo", source="config")
    return mode


async def set_loop_autopilot_mode(
    daemon: Any,
    loop_id: str,
    mode: LoopAutopilotMode,
    *,
    broadcast: bool = True,
    source: str = "toggle",
) -> LoopAutopilotMode:
    """Set loop mode explicitly (toggle or admin)."""
    lid = str(loop_id or "").strip()
    if not lid:
        msg = "loop_id required"
        raise ValueError(msg)

    previous = await get_loop_autopilot_mode(daemon, lid)
    if previous == mode:
        return mode

    try:
        await daemon._persistence_manager.update_loop_metadata(lid, autopilot_mode=mode)
    except Exception:
        logger.warning("Failed to persist autopilot_mode for loop %s", lid, exc_info=True)
    _cache_mode(daemon, lid, mode)

    if broadcast:
        await broadcast_autopilot_mode(daemon, lid, mode, previous_mode=previous, source=source)
    return mode


async def broadcast_autopilot_mode(
    daemon: Any,
    loop_id: str,
    mode: LoopAutopilotMode,
    *,
    previous_mode: LoopAutopilotMode,
    source: str,
) -> None:
    """Notify loop subscribers of a mode change."""
    await daemon._broadcast(
        {
            "type": "autopilot_mode_changed",
            "loop_id": loop_id,
            "mode": mode,
            "previous_mode": previous_mode,
            "enabled": mode == "autopilot",
            "source": source,
        }
    )


def _cache_mode(daemon: Any, loop_id: str, mode: LoopAutopilotMode) -> None:
    cache = getattr(daemon, "_loop_autopilot_modes", None)
    if isinstance(cache, dict):
        cache[loop_id] = mode


__all__ = [
    "LoopAutopilotMode",
    "broadcast_autopilot_mode",
    "config_default_loop_mode",
    "ensure_loop_autopilot_mode",
    "get_loop_autopilot_mode",
    "set_loop_autopilot_mode",
]

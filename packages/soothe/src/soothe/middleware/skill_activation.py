"""RFC-105: File-op-triggered conditional skill activation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from langchain.agents.middleware.types import AgentMiddleware

from soothe.config import SootheConfig
from soothe.skills.events import InternalSkillActivatedEvent
from soothe.skills.index import SkillIndexEntry
from soothe.skills.registry import ProgressiveSkillRegistry

logger = logging.getLogger(__name__)

FILE_OP_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "delete_file",
        "insert_lines",
        "apply_diff",
        "file_info",
    }
)
_PATH_KEYS: tuple[str, ...] = ("file_path", "path", "filepath", "file")


class SkillActivationMiddleware(AgentMiddleware):
    """Intercepts file-op tool calls; activates conditional skills on path match.

    Installed between SoothePolicyMiddleware and NetworkToolErrorsMiddleware
    in the middleware stack (RFC-105).
    """

    def __init__(
        self,
        registry: ProgressiveSkillRegistry,
        catalog_provider: Callable[[], Sequence[SkillIndexEntry]],
        config: SootheConfig,
    ) -> None:
        self._registry = registry
        self._catalog_provider = catalog_provider
        self._config = config
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def abefore_agent(self, state, runtime) -> dict | None:
        """Lazy-init ``state['skill_activation']`` if missing."""
        if isinstance(state, dict) and "skill_activation" not in state:
            return {"skill_activation": ProgressiveSkillRegistry.init_activation_state()}
        return None

    async def awrap_tool_call(self, request, handler):
        """Activate conditional skills when file-op tools touch matching paths."""
        # Fast path: skip skill activation for batched operations (IG-517)
        metadata = getattr(request, "metadata", None) or {}
        if metadata.get("_batched"):
            return await handler(request)

        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        if tool_name not in FILE_OP_TOOLS:
            return await handler(request)

        # Extract paths from tool args
        args = tool_call.get("args", {})
        if not isinstance(args, dict):
            return await handler(request)
        file_paths: list[str] = []
        for key in _PATH_KEYS:
            v = args.get(key)
            if isinstance(v, str):
                file_paths.append(v)
            elif isinstance(v, list):
                file_paths.extend(p for p in v if isinstance(p, str))
        if not file_paths:
            return await handler(request)

        # Reach state via request
        state = getattr(request, "state", None) or {}
        if not isinstance(state, dict):
            return await handler(request)
        activation_state = state.get("skill_activation")
        if not isinstance(activation_state, dict):
            activation_state = ProgressiveSkillRegistry.init_activation_state()
            state["skill_activation"] = activation_state

        # Workspace
        workspace_raw = state.get("workspace")
        if not workspace_raw:
            return await handler(request)
        workspace = Path(str(workspace_raw))

        # Partition catalog
        all_entries = list(self._catalog_provider())
        _, conditional = self._registry.partition(all_entries)
        if not conditional:
            return await handler(request)

        newly = self._registry.match_paths(activation_state, workspace, file_paths, conditional)
        if not newly:
            return await handler(request)

        thread_id = str(state.get("thread_id") or state.get("loop_id") or "")
        for skill_name, matched_path, pattern in newly:
            key = (thread_id, skill_name)
            async with await self._lock_for(key):
                if skill_name in activation_state.get("activated", set()):
                    continue
                self._registry.mark_activated(activation_state, [skill_name])
                try:
                    from soothe.skills.workspace_sync import sync_specific_skill_to_workspace

                    sync_specific_skill_to_workspace(self._config, workspace, skill_name)
                except Exception:  # noqa: BLE001
                    logger.exception("[Skill] sync failed for %s", skill_name)
                try:
                    from soothe.foundation.events.internal_bus import get_internal_event_bus

                    bus = get_internal_event_bus()
                    if bus is not None:
                        await bus.emit(
                            InternalSkillActivatedEvent(
                                skill_name=skill_name,
                                matched_path=matched_path,
                                pattern=pattern,
                                thread_id=thread_id,
                            )
                        )
                except Exception:  # noqa: BLE001
                    logger.debug("[Skill] internal bus emit failed", exc_info=True)

        state["skill_activation"] = activation_state
        return await handler(request)

    async def _lock_for(self, key: tuple[str, str]) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

"""Mirror host skill directories into the workspace when virtual mode is enabled."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

from soothe.core.workspace.tool_path_resolution import filesystem_virtual_mode_from_soothe_config
from soothe.skills.workspace_sync import sync_external_skills_to_workspace

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langgraph.runtime import Runtime

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class SkillWorkspaceSyncMiddleware(AgentMiddleware):
    """Copy external skills into ``<workspace>/.soothe/skills`` before agent tools run.

      When ``security.allow_paths_outside_workspace`` is false (virtual mode), the
    filesystem backend only allows paths under the workspace root. User skills under
      ``~/.agents/skills`` or ``~/.soothe/skills`` are mirrored into the workspace so
      execute-step ``<SKILL_CONTEXT>`` folder paths and on-demand reads work. Package
      built-in skills are not copied (reference text is inlined in prompts).
    """

    def __init__(self, config: SootheConfig) -> None:
        self._config = config

    async def abefore_agent(
        self,
        state: AgentState,  # noqa: ARG002
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Mirror external skills when virtual mode and workspace are configured."""
        if not filesystem_virtual_mode_from_soothe_config(self._config):
            return None

        from langgraph.config import get_config

        try:
            lg_config = get_config()
        except Exception:
            return None
        if not isinstance(lg_config, dict):
            return None
        configurable = lg_config.get("configurable")
        if not isinstance(configurable, dict):
            return None

        workspace = configurable.get("workspace")
        if not workspace or not str(workspace).strip():
            return None

        ws = Path(str(workspace)).expanduser().resolve()
        mirrored = sync_external_skills_to_workspace(self._config, ws)
        if mirrored:
            logger.info(
                "[SkillSync] Mirrored %d external skill(s) under %s",
                len(mirrored),
                ws / ".soothe" / "skills",
            )
        return None
